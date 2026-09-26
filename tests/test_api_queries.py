"""
Tests for the transaction browsing query logic, tested directly against
a db object (no HTTP involved) - the FastAPI wiring is tested separately
in test_api_main.py.
"""
from api.queries import list_distinct_accounts, list_distinct_categories, query_transactions


def _seed(db):
    db.transactions.insert_many(
        [
            {"account_id": "natwest-tiarnan", "category": "groceries", "is_shared": True, "date": "2026-08-01", "description_raw": "TESCO STORES", "amount": -45.20},
            {"account_id": "natwest-tiarnan", "category": "clothing", "is_shared": False, "date": "2026-08-05", "description_raw": "ZARA BELFAST", "amount": -30.00},
            {"account_id": "aib-deirbhile", "category": "groceries", "is_shared": True, "date": "2026-08-10", "description_raw": "SAINSBURYS", "amount": -20.00},
            {"account_id": "aib-deirbhile", "category": None, "is_shared": None, "date": "2026-08-15", "description_raw": "UNKNOWN MERCHANT", "amount": -5.00},
        ]
    )


def test_no_filters_returns_everything(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db)
    assert result["total"] == 4
    assert len(result["items"]) == 4


def test_filter_by_account_id(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, account_id="natwest-tiarnan")
    assert result["total"] == 2
    assert all(t["account_id"] == "natwest-tiarnan" for t in result["items"])


def test_filter_by_category(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, category="groceries")
    assert result["total"] == 2


def test_filter_by_is_shared_true(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, is_shared=True)
    assert result["total"] == 2
    assert all(t["is_shared"] is True for t in result["items"])


def test_filter_by_is_shared_false(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, is_shared=False)
    assert result["total"] == 1


def test_date_range_filter(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, start="2026-08-05", end="2026-08-10")
    assert result["total"] == 2


def test_search_matches_description_case_insensitively(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, search="tesco")
    assert result["total"] == 1
    assert result["items"][0]["description_raw"] == "TESCO STORES"


def test_results_sorted_by_date_descending(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db)
    dates = [t["date"] for t in result["items"]]
    assert dates == sorted(dates, reverse=True)


def test_pagination_limit_and_skip(mongo_db):
    _seed(mongo_db)
    page1 = query_transactions(mongo_db, limit=2, skip=0)
    page2 = query_transactions(mongo_db, limit=2, skip=2)

    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert page1["total"] == 4
    assert page1["items"][0]["_id"] != page2["items"][0]["_id"]


def test_object_id_is_serialized_to_string(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, limit=1)
    assert isinstance(result["items"][0]["_id"], str)


def test_combined_filters(mongo_db):
    _seed(mongo_db)
    result = query_transactions(mongo_db, category="groceries", is_shared=True, account_id="aib-deirbhile")
    assert result["total"] == 1
    assert result["items"][0]["description_raw"] == "SAINSBURYS"


def test_list_distinct_categories_excludes_none_and_sorts(mongo_db):
    _seed(mongo_db)
    cats = list_distinct_categories(mongo_db)
    assert cats == ["clothing", "groceries"]


def test_list_distinct_accounts_sorted(mongo_db):
    _seed(mongo_db)
    accounts = list_distinct_accounts(mongo_db)
    assert accounts == ["aib-deirbhile", "natwest-tiarnan"]
