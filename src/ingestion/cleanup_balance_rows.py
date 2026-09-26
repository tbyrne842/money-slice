"""
One-off cleanup: removes any transaction whose amount was stored as
NaN. This happened because csv_importer.parse_csv() didn't originally
guard against a bank's trailing "Balance as at ..." summary row (or
any other row with a blank amount cell) - it would compute
float(nan) without raising, and Mongo happily stores a NaN double.
The bug only became visible when something tried to JSON-serialise
that value back out (GET /api/transactions).

parse_csv() now skips such rows on import via row_has_valid_amount(),
so this is only needed to clean up data imported before that fix.
Safe to re-run - it's a no-op once there's nothing left to clean up.

Usage:
    python -m ingestion.cleanup_balance_rows
"""
import math

from db.mongo import get_db


def find_nan_amount_ids(db) -> list:
    return [
        txn["_id"]
        for txn in db.transactions.find({}, {"amount": 1})
        if isinstance(txn.get("amount"), float) and math.isnan(txn["amount"])
    ]


def cleanup(db) -> int:
    bad_ids = find_nan_amount_ids(db)
    if not bad_ids:
        return 0
    result = db.transactions.delete_many({"_id": {"$in": bad_ids}})
    return result.deleted_count


def main():
    db = get_db()
    deleted = cleanup(db)
    print(f"Removed {deleted} transaction(s) with a NaN amount.")


if __name__ == "__main__":
    main()
