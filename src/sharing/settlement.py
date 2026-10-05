"""
Calculate a household's settlement: given each member's share of joint
spend, work out each person's net balance (paid minus fair share) and
who should pay whom to square it.

Shares are per-member fractions summing to 1 (see households.py). With
no start/end this covers all-time, which keeps the figure a constantly
current "who owes what" - but it applies today's shares to all past
spend, so if shares or membership change, start a new period from that
date (--start / ?start=) rather than trusting the all-time figure.

Settle-up payments: until explicit "A paid B" recording arrives (a later
phase), a transfer between members is recognised by the category
"partner_contribution". That only identifies the recipient when the
household has exactly two members, so in larger households those rows
are ignored and counted in `unattributed_settle_ups` instead.

Usage:
    python -m sharing.settlement --user tiarnan
    python -m sharing.settlement --user tiarnan --start 2026-08-01 --end 2026-08-31
"""

import argparse
from datetime import date

from db.mongo import get_db
from households import get_household, member_shares

SETTLE_UP_CATEGORY = "partner_contribution"


def _date_filter(start: date | None, end: date | None) -> dict | None:
    if not (start or end):
        return None
    date_filter = {}
    if start:
        date_filter["$gte"] = start.isoformat()
    if end:
        date_filter["$lte"] = end.isoformat()
    return date_filter


def _transfers(balance: dict[str, float]) -> list[dict]:
    """Greedy debtor -> creditor payments that clear every balance. Works in pence."""
    pence = {u: round(b * 100) for u, b in balance.items()}
    creditors = sorted(((p, u) for u, p in pence.items() if p > 0), reverse=True)
    debtors = sorted(((-p, u) for u, p in pence.items() if p < 0), reverse=True)
    result = []
    while creditors and debtors:
        owed, creditor = creditors.pop(0)
        owes, debtor = debtors.pop(0)
        amount = min(owed, owes)
        result.append({"from": debtor, "to": creditor, "amount": amount / 100})
        if owed > amount:
            creditors.append((owed - amount, creditor))
            creditors.sort(reverse=True)
        if owes > amount:
            debtors.append((owes - amount, debtor))
            debtors.sort(reverse=True)
    return result


def calculate_settlement(
    db,
    shares: dict[str, float],
    start: date | None = None,
    end: date | None = None,
) -> dict:
    members = list(shares)
    date_filter = _date_filter(start, end)

    # --- shared spend: who paid for what was agreed to be joint cost ---
    spend_query: dict = {
        "is_shared": True,
        "owner": {"$in": members},
        # Defensive: a settle-up should always be is_shared: False per
        # sharing_defaults.yaml, but if one ever gets mis-flagged this
        # stops it being counted both as spend and as a settle-up.
        "category": {"$ne": SETTLE_UP_CATEGORY},
    }
    if date_filter:
        spend_query["date"] = date_filter

    paid = {u: 0.0 for u in members}
    for txn in db.transactions.find(spend_query):
        if txn["amount"] < 0:  # only outgoing spend is a cost to split
            paid[txn["owner"]] += abs(txn["amount"])

    total_shared = sum(paid.values())
    fair_share = {u: total_shared * shares[u] for u in members}

    # --- settle-up payments between the two members of a two-person household ---
    # Only the outgoing leg counts (amount < 0), so a transfer imported from
    # both statements is never counted twice.
    sent = {u: 0.0 for u in members}
    received = {u: 0.0 for u in members}
    unattributed = 0

    settle_query: dict = {"category": SETTLE_UP_CATEGORY, "owner": {"$in": members}, "amount": {"$lt": 0}}
    if date_filter:
        settle_query["date"] = date_filter

    for txn in db.transactions.find(settle_query):
        if len(members) != 2:
            unattributed += 1
            continue
        sender = txn["owner"]
        recipient = next(u for u in members if u != sender)
        sent[sender] += abs(txn["amount"])
        received[recipient] += abs(txn["amount"])

    # Positive = is owed money (paid more than their fair share); negative =
    # owes the pot. Sending a settle-up moves you towards zero, receiving one
    # moves you away from it.
    balance = {u: paid[u] - fair_share[u] + sent[u] - received[u] for u in members}

    transfers = _transfers(balance)
    if transfers:
        settlement_text = "; ".join(f"{t['from']} owes {t['to']} £{t['amount']:.2f}" for t in transfers)
    else:
        settlement_text = "Already settled - nothing owed either way"

    def rounded(values: dict[str, float]) -> dict[str, float]:
        return {u: round(v, 2) for u, v in values.items()}

    return {
        "shares": dict(shares),
        "total_shared": round(total_shared, 2),
        "paid_by_member": rounded(paid),
        "fair_share": rounded(fair_share),
        "settled_sent": rounded(sent),
        "settled_received": rounded(received),
        "balance": rounded(balance),
        "transfers": transfers,
        "unattributed_settle_ups": unattributed,
        "settlement_text": settlement_text,
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate the settlement for a user's household")
    parser.add_argument("--user", required=True, help="Username of any member of the household")
    parser.add_argument("--start", type=str, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD, inclusive")
    args = parser.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    db = get_db()
    household = get_household(db, args.user)
    if household is None:
        raise SystemExit(f"'{args.user}' is not in a household.")

    result = calculate_settlement(db, member_shares(household), start=start, end=end)

    print(f"Household: {household['name']}")
    print(f"Total shared spend: £{result['total_shared']}")
    for user, share in result["shares"].items():
        print(
            f"  {user}: share {share:.0%}, paid £{result['paid_by_member'][user]}, "
            f"fair share £{result['fair_share'][user]}, balance £{result['balance'][user]}"
        )
    if result["unattributed_settle_ups"]:
        print(f"Ignored {result['unattributed_settle_ups']} settle-up payment(s): recipient unknown in a 3+ person household")
    print(f"\n{result['settlement_text']}")


if __name__ == "__main__":
    main()
