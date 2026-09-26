"""
Tests for cleanup_balance_rows.py - the one-off script that removes
transactions with a NaN amount (from before parse_csv() guarded
against trailing balance-summary rows).
"""
from ingestion.cleanup_balance_rows import cleanup, find_nan_amount_ids


def test_finds_and_removes_only_nan_amount_transactions(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"account_id": "a", "date": "2026-08-17", "amount": -24.50, "description_raw": "TESCO"},
            {"account_id": "a", "date": "2026-08-20", "amount": 2300.0, "description_raw": "SALARY"},
            {"account_id": "a", "date": "2026-08-25", "amount": float("nan"), "description_raw": "Balance as at 25 Aug 2026"},
        ]
    )

    bad_ids = find_nan_amount_ids(mongo_db)
    assert len(bad_ids) == 1

    deleted = cleanup(mongo_db)
    assert deleted == 1
    assert mongo_db.transactions.count_documents({}) == 2
    assert mongo_db.transactions.find_one({"description_raw": "Balance as at 25 Aug 2026"}) is None


def test_is_a_no_op_when_nothing_needs_cleaning(mongo_db):
    mongo_db.transactions.insert_one(
        {"account_id": "a", "date": "2026-08-17", "amount": -24.50, "description_raw": "TESCO"}
    )

    deleted = cleanup(mongo_db)
    assert deleted == 0
    assert mongo_db.transactions.count_documents({}) == 1
