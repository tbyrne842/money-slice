"""
Tests for the API's import pipeline endpoint.

Only api.main.get_db needs patching here - save_transactions() and
categorisation.rules.run() both accept the db explicitly, and
api.main passes the same handle through to all three pipeline steps.
"""
import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import app


@pytest.fixture
def client(monkeypatch):
    database = mongomock.MongoClient()["finance_tracker_test"]
    monkeypatch.setattr(api_main, "get_db", lambda: database)
    return TestClient(app), database


def upload(client, fixture_path, mapping="generic_uk_debit_credit", account_id="test-account"):
    with open(fixture_path, "rb") as f:
        return client.post(
            "/api/import",
            files={"file": ("statement.csv", f, "text/csv")},
            data={"account_id": account_id, "mapping": mapping, "source": "csv"},
        )


def test_upload_runs_full_pipeline(client, fixture_path):
    test_client, database = client
    response = upload(test_client, fixture_path("generic_uk_debit_credit.csv"))

    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 2
    assert body["duplicates"] == 0
    # Both rows should have gone through categorisation + sharing too,
    # whatever their outcome, so the keys must all be present.
    assert set(body.keys()) == {
        "inserted",
        "duplicates",
        "categorised",
        "still_uncategorised",
        "sharing",
    }
    assert database.transactions.count_documents({}) == 2


def test_reupload_is_idempotent(client, fixture_path):
    test_client, database = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    response = upload(test_client, fixture_path("generic_uk_debit_credit.csv"))

    body = response.json()
    assert body["inserted"] == 0
    assert body["duplicates"] == 2
    assert database.transactions.count_documents({}) == 2


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
