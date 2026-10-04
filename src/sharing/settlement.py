"""
Calculate the household settlement: given a split ratio, work out who
owes whom based on shared transactions and who actually paid for them -
then apply any settle-up payments already sent between Tiarnan and
Deirbhile (category "partner_contribution") so the result is the
actual outstanding balance, not just what the raw spend implies.

With no start/end given, this covers all-time - which is what makes it
safe to treat as a constantly-current "who owes what" figure: every
settle-up payment discharges exactly what it's worth (not weighted by
the ratio), so the running total stays correct no matter how far back
the calculation looks, as long as the ratio itself hasn't changed
over that period. If you ever renegotiate the ratio, start a new
period from that date rather than trusting the all-time figure.

Usage:
    python -m sharing.settlement --start 2026-08-01 --end 2026-08-31
    python -m sharing.settlement --tiarnan-ratio 0.6  # overrides config/settlement.yaml
"""

import argparse
from datetime import date
from pathlib import Path

import yaml

from db.mongo import get_db

SETTLEMENT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settlement.yaml"


def load_default_tiarnan_ratio() -> float:
    with open(SETTLEMENT_CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}
    return config.get("tiarnan_ratio", 0.5)


def _date_filter(start: date | None, end: date | None) -> dict | None:
    if not (start or end):
        return None
    date_filter = {}
    if start:
        date_filter["$gte"] = start.isoformat()
    if end:
        date_filter["$lte"] = end.isoformat()
    return date_filter


def calculate_settlement(
    db,
    tiarnan_ratio: float | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    if tiarnan_ratio is None:
        tiarnan_ratio = load_default_tiarnan_ratio()

    date_filter = _date_filter(start, end)

    # --- shared spend: who paid for what was agreed to be joint cost ---
    spend_query: dict = {
        "is_shared": True,
        # Defensive: a partner_contribution transaction should always be
        # is_shared: False per sharing_defaults.yaml, but if one ever
        # gets mis-flagged (manual edit, mongo-express, etc.) this stops
        # it being double-counted - once here, once as a settle-up below.
        "category": {"$ne": "partner_contribution"},
    }
    if date_filter:
        spend_query["date"] = date_filter

    paid_by_owner: dict[str, float] = {"tiarnan": 0.0, "deirbhile": 0.0}

    for txn in db.transactions.find(spend_query):
        if txn["amount"] >= 0:
            continue  # only outgoing spend counts as a shared cost

        owner = txn.get("owner")
        if owner not in paid_by_owner:
            continue  # no owner recorded (legacy row) - re-upload to attribute it

        paid_by_owner[owner] += abs(txn["amount"])

    total_shared = sum(paid_by_owner.values())
    fair_share = {
        "tiarnan": total_shared * tiarnan_ratio,
        "deirbhile": total_shared * (1 - tiarnan_ratio),
    }

    # Positive = paid less than their fair share of shared spend (owes
    # the pot); negative = paid more (is owed back). Before settle-ups.
    balance_before_settlements = {
        "tiarnan": fair_share["tiarnan"] - paid_by_owner["tiarnan"],
        "deirbhile": fair_share["deirbhile"] - paid_by_owner["deirbhile"],
    }

    # --- settle-up payments already sent between the two of them ---
    # A partner_contribution transaction is a direct cash transfer, not
    # new shared spend - it's excluded from spend_query above (it's
    # always is_shared: False, see sharing_defaults.yaml) and instead
    # discharges the balance pound-for-pound, unweighted by the ratio.
    # Only the outgoing leg is counted (amount < 0, i.e. money leaving
    # the sender's account) so that if both partners' statements get
    # imported, the same real-world transfer is never counted twice.
    settlement_query: dict = {"category": "partner_contribution"}
    if date_filter:
        settlement_query["date"] = date_filter

    settled_by_owner: dict[str, float] = {"tiarnan": 0.0, "deirbhile": 0.0}

    for txn in db.transactions.find(settlement_query):
        if txn["amount"] >= 0:
            continue  # the mirrored incoming leg, if present - ignore it

        owner = txn.get("owner")
        if owner not in settled_by_owner:
            continue

        settled_by_owner[owner] += abs(txn["amount"])

    # Tiarnan paying Deirbhile discharges what he owes her; Deirbhile
    # paying Tiarnan discharges what she owes him (pushing his balance
    # further negative, i.e. more owed back to him).
    balance = {
        "tiarnan": balance_before_settlements["tiarnan"] - settled_by_owner["tiarnan"] + settled_by_owner["deirbhile"],
        "deirbhile": balance_before_settlements["deirbhile"] - settled_by_owner["deirbhile"] + settled_by_owner["tiarnan"],
    }

    if round(balance["tiarnan"], 2) > 0:
        settlement_text = f"Tiarnan owes Deirbhile £{balance['tiarnan']:.2f}"
    elif round(balance["deirbhile"], 2) > 0:
        settlement_text = f"Deirbhile owes Tiarnan £{balance['deirbhile']:.2f}"
    else:
        settlement_text = "Already settled - nothing owed either way"

    return {
        "tiarnan_ratio": tiarnan_ratio,
        "total_shared": round(total_shared, 2),
        "paid_by_owner": {k: round(v, 2) for k, v in paid_by_owner.items()},
        "fair_share": {k: round(v, 2) for k, v in fair_share.items()},
        "settled_by_owner": {k: round(v, 2) for k, v in settled_by_owner.items()},
        "balance": {k: round(v, 2) for k, v in balance.items()},
        "settlement_text": settlement_text,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calculate the household settlement, including any settle-up payments already sent"
    )
    parser.add_argument(
        "--tiarnan-ratio",
        type=float,
        default=None,
        help="Tiarnan's share, e.g. 0.5 for 50/50. Defaults to config/settlement.yaml if not given.",
    )
    parser.add_argument("--start", type=str, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD, inclusive")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    db = get_db()
    result = calculate_settlement(db, args.tiarnan_ratio, start=start, end=end)

    print(f"Ratio used - Tiarnan: {result['tiarnan_ratio']:.0%}")
    print(f"Total shared spend: £{result['total_shared']}")
    print(
        f"Paid - Tiarnan: £{result['paid_by_owner']['tiarnan']}, Deirbhile: £{result['paid_by_owner']['deirbhile']}"
    )
    print(
        f"Fair share at this ratio - Tiarnan: £{result['fair_share']['tiarnan']}, Deirbhile: £{result['fair_share']['deirbhile']}"
    )
    print(
        f"Settle-up payments already sent - Tiarnan: £{result['settled_by_owner']['tiarnan']}, Deirbhile: £{result['settled_by_owner']['deirbhile']}"
    )
    print(f"\n{result['settlement_text']}")


if __name__ == "__main__":
    main()
