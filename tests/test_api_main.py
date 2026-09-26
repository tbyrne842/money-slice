"""
Integration tests through the actual HTTP layer (FastAPI's TestClient),
confirming routes are wired correctly - both the read-only browser
(filtering logic itself is tested more thoroughly in
test_api_queries.py against the db directly; these exist to catch
wiring mistakes) and the CSV import pipeline endpoint.

Only api.main.get_db needs patching for the import tests -
save_transactions() and categorisation.rules.run() both accept the db
explicitly, and api.main passes the same handle through all three
pipeline steps.
"""
import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main


@pytest.fixture
def client(monkeypatch):
    db = mongomock.MongoClient()["finance_tracker_test"]
    monkeypatch.setattr(api_main, "get_db", lambda: db)
    return TestClient(api_main.app), db


# --- read-only browser -------------------------------------------------

def test_health_endpoint(client):
    test_client, _ = client
    res = test_client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_transactions_endpoint_returns_seeded_data(client):
    test_client, db = client
    db.transactions.insert_one(
        {"account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0}
    )

    res = test_client.get("/api/transactions")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["description_raw"] == "TESCO"


def test_transactions_endpoint_applies_query_filters(client):
    test_client, db = client
    db.transactions.insert_many(
        [
            {"account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0},
            {"account_id": "a", "category": "clothing", "is_shared": False, "date": "2026-08-01", "description_raw": "ZARA", "amount": -20.0},
        ]
    )

    res = test_client.get("/api/transactions", params={"category": "clothing"})
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["description_raw"] == "ZARA"


def test_transactions_endpoint_rejects_limit_over_500(client):
    test_client, _ = client
    res = test_client.get("/api/transactions", params={"limit": 1000})
    assert res.status_code == 422  # FastAPI validation error


def test_categories_endpoint(client):
    test_client, db = client
    db.transactions.insert_many(
        [
            {"account_id": "a", "category": "groceries", "description_raw": "x", "amount": -1, "date": "2026-08-01", "is_shared": None},
            {"account_id": "a", "category": "clothing", "description_raw": "y", "amount": -1, "date": "2026-08-01", "is_shared": None},
        ]
    )

    res = test_client.get("/api/categories")
    assert res.json() == ["clothing", "groceries"]


def test_accounts_endpoint(client):
    test_client, db = client
    db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "category": None, "description_raw": "x", "amount": -1, "date": "2026-08-01", "is_shared": None}
    )

    res = test_client.get("/api/accounts")
    assert res.json() == ["natwest-tiarnan"]


def test_frontend_index_is_served(client):
    test_client, _ = client
    res = test_client.get("/")
    assert res.status_code == 200
    assert "Money Slice" in res.text


def test_frontend_index_includes_upload_form(client):
    test_client, _ = client
    res = test_client.get("/")
    assert res.status_code == 200
    assert 'id="upload-form"' in res.text


def test_static_assets_are_not_cached(client):
    test_client, _ = client
    for path in ("/", "/app.js", "/style.css"):
        res = test_client.get(path)
        assert res.headers["cache-control"] == "no-store"


# --- CSV import pipeline ------------------------------------------------

def upload(client, fixture_path, mapping="generic_uk_debit_credit", account_id="test-account"):
    with open(fixture_path, "rb") as f:
        return client.post(
            "/api/import",
            files={"file": ("statement.csv", f, "text/csv")},
            data={"account_id": account_id, "mapping": mapping, "source": "csv"},
        )


def test_upload_runs_full_pipeline(client, fixture_path):
    test_client, db = client
    response = upload(test_client, fixture_path("generic_uk_debit_credit.csv"))

    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 2
    assert body["duplicates"] == 0
    assert set(body.keys()) == {
        "inserted",
        "duplicates",
        "categorised",
        "still_uncategorised",
        "sharing",
    }
    assert db.transactions.count_documents({}) == 2


def test_reupload_is_idempotent(client, fixture_path):
    test_client, db = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    response = upload(test_client, fixture_path("generic_uk_debit_credit.csv"))

    body = response.json()
    assert body["inserted"] == 0
    assert body["duplicates"] == 2
    assert db.transactions.count_documents({}) == 2


def test_invalid_mapping_returns_400(client, fixture_path):
    test_client, _ = client
    response = upload(test_client, fixture_path("generic_uk_debit_credit.csv"), mapping="not_a_real_mapping")

    assert response.status_code == 400
    assert "not_a_real_mapping" in response.json()["detail"]


def test_get_mappings_lists_known_mappings(client):
    test_client, _ = client
    response = test_client.get("/api/mappings")

    assert response.status_code == 200
    assert "generic_uk_debit_credit" in response.json()
