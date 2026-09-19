"""
Tests for the uncategorized-merchant summary query.
"""
from categorization.summarize_uncategorized import summarize_uncategorized


def test_groups_by_description_and_counts_correctly(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "TESCO STORES 123", "amount": -10, "category": None, "source_category": None},
            {"description_raw": "TESCO STORES 123", "amount": -15, "category": None, "source_category": None},
            {"description_raw": "NETFLIX.COM", "amount": -9.99, "category": None, "source_category": None},
        ]
    )

    rows = summarize_uncategorized(mongo_db)
    assert len(rows) == 2

    tesco = next(r for r in rows if r["_id"] == "TESCO STORES 123")
    assert tesco["count"] == 2
    assert tesco["total_amount"] == 25.0


def test_already_categorized_transactions_are_excluded(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "TESCO STORES 123", "amount": -10, "category": None, "source_category": None},
            {"description_raw": "SALARY ACME LTD", "amount": 2000, "category": "income", "source_category": None},
        ]
    )

    rows = summarize_uncategorized(mongo_db)
    assert len(rows) == 1
    assert rows[0]["_id"] == "TESCO STORES 123"


def test_sort_by_count_puts_most_frequent_first(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "RARE BIG PURCHASE", "amount": -500, "category": None, "source_category": None},
            {"description_raw": "FREQUENT SMALL", "amount": -2, "category": None, "source_category": None},
            {"description_raw": "FREQUENT SMALL", "amount": -2, "category": None, "source_category": None},
            {"description_raw": "FREQUENT SMALL", "amount": -2, "category": None, "source_category": None},
        ]
    )

    rows = summarize_uncategorized(mongo_db, sort_by="count")
    assert rows[0]["_id"] == "FREQUENT SMALL"


def test_sort_by_amount_puts_highest_total_spend_first(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "RARE BIG PURCHASE", "amount": -500, "category": None, "source_category": None},
            {"description_raw": "FREQUENT SMALL", "amount": -2, "category": None, "source_category": None},
            {"description_raw": "FREQUENT SMALL", "amount": -2, "category": None, "source_category": None},
        ]
    )

    rows = summarize_uncategorized(mongo_db, sort_by="amount")
    assert rows[0]["_id"] == "RARE BIG PURCHASE"


def test_total_amount_uses_absolute_value_so_income_and_spend_both_count(mongo_db):
    # A large incoming transfer shouldn't cancel out large outgoing spend
    # when both happen to share a description (edge case, but cheap to guard).
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "BANK TRANSFER", "amount": -100, "category": None, "source_category": None},
            {"description_raw": "BANK TRANSFER", "amount": 100, "category": None, "source_category": None},
        ]
    )

    rows = summarize_uncategorized(mongo_db)
    assert rows[0]["total_amount"] == 200.0


def test_captures_source_category_hint_when_present(mongo_db):
    mongo_db.transactions.insert_one(
        {
            "description_raw": "SAINSBURYS SUPERMARKETS BELFAST",
            "amount": -31.08,
            "category": None,
            "source_category": "General Purchases-Groceries",
        }
    )

    rows = summarize_uncategorized(mongo_db)
    assert rows[0]["source_category"] == "General Purchases-Groceries"


def test_no_uncategorized_transactions_returns_empty_list(mongo_db):
    mongo_db.transactions.insert_one(
        {"description_raw": "SALARY", "amount": 2000, "category": "income", "source_category": None}
    )

    rows = summarize_uncategorized(mongo_db)
    assert rows == []
