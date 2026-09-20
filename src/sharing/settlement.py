"""
Calculate a settlement for a period: given a split ratio, work out who
owes whom based on shared transactions and who actually paid for them.

The ratio is a per-run input, not stored anywhere - pass whatever you've
agreed for that period.

Usage:
    python -m sharing.settlement --tiarnan-ratio 0.5 --start 2026-08-01 --end 2026-08-31
"""

import argparse
from datetime import date
from pathlib import Path

import yaml

from db.mongo import get_db

OWNERS_PATH = Path(__file__).parent.parent / "config" / "account_owners.yaml"


def load_account_owners() -> dict[str, str]:
    with open(OWNERS_PATH) as f:
        return yaml.safe_load(f) or {}


def calculate_settlement(
    db,
    tiarnan_ratio: float,
    start: date | None = None,
    end: date | None = None,
    account_owners: dict[str, str] | None = None,
) -> dict:
    if account_owners is None:
        account_owners = load_account_owners()

    query: dict = {"is_shared": True}
    if start or end:
        date_filter = {}
        if start:
            date_filter["$gte"] = start.isoformat()
        if end:
            date_filter["$lte"] = end.isoformat()
        query["date"] = date_filter

    paid_by_owner: dict[str, float] = {"tiarnan": 0.0, "deirbhile": 0.0, "joint": 0.0}
    unmapped_accounts: set[str] = set()

    for txn in db.transactions.find(query):
        if txn["amount"] >= 0:
            continue  # only outgoing spend counts as a shared cost

        owner = account_owners.get(txn["account_id"])
        if owner is None:
            unmapped_accounts.add(txn["account_id"])
            continue

        paid_by_owner[owner] = paid_by_owner.get(owner, 0.0) + abs(txn["amount"])

    total_shared = sum(paid_by_owner.values())
    fair_share = {
        "tiarnan": total_shared * tiarnan_ratio,
        "deirbhile": total_shared * (1 - tiarnan_ratio),
    }

    # Positive balance = paid less than their fair share (owes the pot).
    # Negative balance = paid more than their fair share (is owed back).
    balance = {
        "tiarnan": fair_share["tiarnan"] - paid_by_owner["tiarnan"],
        "deirbhile": fair_share["deirbhile"] - paid_by_owner["deirbhile"],
    }

    if balance["tiarnan"] > 0:
        settlement_text = f"Tiarnan owes Deirbhile £{balance['tiarnan']:.2f}"
    elif balance["deirbhile"] > 0:
        settlement_text = f"Deirbhile owes Tiarnan £{balance['deirbhile']:.2f}"
    else:
        settlement_text = "Already settled - nothing owed either way"

    return {
        "total_shared": round(total_shared, 2),
        "paid_by_owner": {k: round(v, 2) for k, v in paid_by_owner.items()},
        "fair_share": {k: round(v, 2) for k, v in fair_share.items()},
        "balance": {k: round(v, 2) for k, v in balance.items()},
        "settlement_text": settlement_text,
        "unmapped_accounts": sorted(unmapped_accounts),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calculate a household settlement for a period"
    )
    parser.add_argument(
        "--tiarnan-ratio",
        type=float,
        required=True,
        help="Tiarnan's share, e.g. 0.5 for 50/50, 0.6 for 60/40",
    )
    parser.add_argument("--start", type=str, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD, inclusive")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    db = get_db()
    result = calculate_settlement(db, args.tiarnan_ratio, start=start, end=end)

    print(f"Total shared spend: £{result['total_shared']}")
    print(
        f"Paid - Tiarnan: £{result['paid_by_owner']['tiarnan']}, Deirbhile: £{result['paid_by_owner']['deirbhile']}"
    )
    print(
        f"Fair share at this ratio - Tiarnan: £{result['fair_share']['tiarnan']}, Deirbhile: £{result['fair_share']['deirbhile']}"
    )
    print(f"\n{result['settlement_text']}")

    if result["unmapped_accounts"]:
        print(
            f"\nWarning: these accounts had shared transactions but no owner mapping in account_owners.yaml, so were excluded:"
        )
        for acc in result["unmapped_accounts"]:
            print(f"  {acc}")


if __name__ == "__main__":
    main()
