"""
Integration tests through the actual HTTP layer (FastAPI's TestClient),
confirming routes are wired correctly. The filtering logic itself is
tested more thoroughly in test_api_queries.py against the db directly -
these tests exist to catch wiring mistakes, not to re-test every filter.
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
