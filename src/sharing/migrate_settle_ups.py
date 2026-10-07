"""
One-off migration: turn the old name-matched settle-ups into explicit records.

Before explicit recording, a transfer between the two members of a
household was recognised by its bank category, "partner_contribution".
This converts each outgoing row (amount < 0) into a `settle_ups` record
(payer = the row's owner, payee = the other member, same date), so the
household balance carries on unchanged. The incoming mirror of a transfer
is skipped so nothing is counted twice, and re-running is safe: rows that
were already converted are recognised by `source_txn_id`.

Only two-person households can be migrated - with more members the
recipient of an old row is unknowable.

Dry run by default; nothing is written without --apply.

Usage:
    python -m sharing.migrate_settle_ups --user tiarnan
    python -m sharing.migrate_settle_ups --user tiarnan --apply
"""
import argparse
from datetime import datetime, timezone

from db.mongo import get_db
from households import get_household, member_shares
from sharing.settlement import TRANSFER_CATEGORY, calculate_settlement

NOTE = "Migrated from bank transaction"


def migrate(db, household: dict, apply: bool = False) -> dict:
    members = [m["username"] for m in household["members"]]
    if len(members) != 2:
        raise ValueError("Only two-person households can be migrated.")

    household_id = household["_id"]
    existing = list(db.settle_ups.find({"household_id": household_id}))
    done = {p["source_txn_id"] for p in existing if p.get("source_txn_id")}

    new_payments, already, skipped = [], 0, 0
    rows = db.transactions.find(
        {"category": TRANSFER_CATEGORY, "owner": {"$in": members}, "amount": {"$lt": 0}}
    ).sort("date", 1)
    for txn in rows:
        if str(txn["_id"]) in done:
            already += 1
            continue
        if not isinstance(txn.get("date"), str) or not isinstance(txn.get("amount"), (int, float)):
            skipped += 1  # malformed row - can't make a dated payment from it
            continue
        payee = next(u for u in members if u != txn["owner"])
        new_payments.append(
            {
                "household_id": household_id,
                "payer": txn["owner"],
                "payee": payee,
                "amount": round(abs(txn["amount"]), 2),
                "date": txn["date"],
                "note": NOTE,
                "recorded_by": txn["owner"],
                "source_txn_id": str(txn["_id"]),
                "created_at": datetime.now(timezone.utc),
            }
        )

    # Work out the resulting balance before writing anything.
    after = calculate_settlement(db, member_shares(household), payments=existing + new_payments)
    if apply and new_payments:
        db.settle_ups.insert_many(new_payments)

    total_by_payer = {u: 0.0 for u in members}
    for p in new_payments:
        total_by_payer[p["payer"]] = round(total_by_payer[p["payer"]] + p["amount"], 2)
    return {
        "applied": apply,
        "converted": len(new_payments),
        "already_converted": already,
        "skipped_malformed": skipped,
        "total_by_payer": total_by_payer,
        "settlement_text": after["settlement_text"],
        "balance": after["balance"],
    }


def main():
    parser = argparse.ArgumentParser(description="Convert partner_contribution rows into settle-up records")
    parser.add_argument("--user", required=True, help="Username of either member of the household")
    parser.add_argument("--apply", action="store_true", help="Write the records (default is a dry run)")
    args = parser.parse_args()

    db = get_db()
    household = get_household(db, args.user)
    if household is None:
        raise SystemExit(f"'{args.user}' is not in a household.")

    try:
        result = migrate(db, household, apply=args.apply)
    except ValueError as exc:
        raise SystemExit(str(exc))

    print("APPLIED" if result["applied"] else "DRY RUN - nothing written (use --apply)")
    print(f"To convert: {result['converted']}  already converted: {result['already_converted']}  skipped (malformed): {result['skipped_malformed']}")
    for user, total in result["total_by_payer"].items():
        print(f"  {user} paid £{total:.2f} in converted settle-ups")
    print(f"Balances after: {result['balance']}")
    print(result["settlement_text"])


if __name__ == "__main__":
    main()
