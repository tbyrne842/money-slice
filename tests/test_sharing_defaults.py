"""
Tests for apply_sharing_defaults - the bulk script that sets is_shared
based on category, without ever touching already-decided transactions.
"""

from sharing.apply_defaults import apply_defaults, load_sharing_defaults


def test_loads_shared_and_personal_categories_from_yaml():
    defaults = load_sharing_defaults()
    assert defaults["groceries"] is True
    assert defaults["clothing"] is False


def test_sets_is_shared_true_for_shared_categories(mongo_db):
    mongo_db.transactions.insert_one(
        {"description_raw": "TESCO", "category": "groceries", "is_shared": None}
    )

    result = apply_defaults(mongo_db)
    assert result["updated"] == 1

    txn = mongo_db.transactions.find_one({"description_raw": "TESCO"})
    assert txn["is_shared"] is True


def test_sets_is_shared_false_for_personal_categories(mongo_db):
    mongo_db.transactions.insert_one(
        {"description_raw": "ZARA", "category": "clothing", "is_shared": None}
    )

    apply_defaults(mongo_db)

    txn = mongo_db.transactions.find_one({"description_raw": "ZARA"})
    assert txn["is_shared"] is False


def test_never_overwrites_an_already_decided_transaction(mongo_db):
    # Manually flagged as shared, even though clothing defaults to personal -
    # a re-run must not stomp on that manual decision.
    mongo_db.transactions.insert_one(
        {
            "description_raw": "ZARA - shared with Deirbhile",
            "category": "clothing",
            "is_shared": True,
        }
    )

    apply_defaults(mongo_db)

    txn = mongo_db.transactions.find_one(
        {"description_raw": "ZARA - shared with Deirbhile"}
    )
    assert txn["is_shared"] is True


def test_skips_transactions_with_no_category_yet(mongo_db):
    mongo_db.transactions.insert_one(
        {"description_raw": "UNKNOWN MERCHANT", "category": None, "is_shared": None}
    )

    result = apply_defaults(mongo_db)
    assert result["skipped_no_category"] == 1

    txn = mongo_db.transactions.find_one({"description_raw": "UNKNOWN MERCHANT"})
    assert txn["is_shared"] is None  # left untouched, still undecided


def test_unknown_category_defaults_to_personal_and_is_flagged(mongo_db):
    mongo_db.transactions.insert_one(
        {
            "description_raw": "SOMETHING NEW",
            "category": "a_future_category",
            "is_shared": None,
        }
    )

    result = apply_defaults(mongo_db)
    assert result["defaulted_unknown_category"] == 1

    txn = mongo_db.transactions.find_one({"description_raw": "SOMETHING NEW"})
    assert txn["is_shared"] is False


def test_rerunning_after_new_imports_only_touches_new_undecided_transactions(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "TESCO", "category": "groceries", "is_shared": None},
            {
                "description_raw": "ZARA (manually flagged shared)",
                "category": "clothing",
                "is_shared": True,
            },
        ]
    )
    apply_defaults(mongo_db)

    # Simulate a later import adding a new undecided transaction
    mongo_db.transactions.insert_one(
        {"description_raw": "SAINSBURYS", "category": "groceries", "is_shared": None}
    )
    result = apply_defaults(mongo_db)

    assert result["updated"] == 1  # only the new one
    zara = mongo_db.transactions.find_one(
        {"description_raw": "ZARA (manually flagged shared)"}
    )
    assert zara["is_shared"] is True  # untouched by either run
