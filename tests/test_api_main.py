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
    test_client = TestClient(api_main.app)
    # Everything except /api/health needs a session, so sign in as tiarnan.
    res = test_client.post("/api/auth/register", json={"username": "tiarnan", "password": "correct horse battery"})
    assert res.status_code == 201
    return test_client, db


# --- read-only browser -------------------------------------------------

def test_health_endpoint(client):
    test_client, _ = client
    res = test_client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_transactions_endpoint_returns_seeded_data(client):
    test_client, db = client
    db.transactions.insert_one(
        {"owner": "tiarnan", "account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0}
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
            {"owner": "tiarnan", "account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0},
            {"owner": "tiarnan", "account_id": "a", "category": "clothing", "is_shared": False, "date": "2026-08-01", "description_raw": "ZARA", "amount": -20.0},
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
            {"owner": "tiarnan", "account_id": "a", "category": "groceries", "description_raw": "x", "amount": -1, "date": "2026-08-01", "is_shared": None},
            {"owner": "tiarnan", "account_id": "a", "category": "clothing", "description_raw": "y", "amount": -1, "date": "2026-08-01", "is_shared": None},
        ]
    )

    res = test_client.get("/api/categories")
    assert res.json() == ["clothing", "groceries"]


def test_accounts_endpoint(client):
    test_client, db = client
    db.transactions.insert_one(
        {"owner": "tiarnan", "account_id": "natwest-tiarnan", "category": None, "description_raw": "x", "amount": -1, "date": "2026-08-01", "is_shared": None}
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


def test_frontend_index_includes_add_transaction_form(client):
    test_client, _ = client
    res = test_client.get("/")
    assert res.status_code == 200
    assert 'id="add-form"' in res.text


def test_frontend_index_includes_balance_widget(client):
    test_client, _ = client
    res = test_client.get("/")
    assert res.status_code == 200
    assert 'id="balance-widget"' in res.text


def test_frontend_index_includes_household_panel_and_owner_column(client):
    test_client, _ = client
    res = test_client.get("/")
    assert res.status_code == 200
    assert 'id="household-body"' in res.text
    assert 'id="scope"' in res.text
    assert 'data-tab="household"' in res.text
    assert "<th>Owner</th>" in res.text
    assert 'id="account"' not in res.text


def test_static_assets_are_not_cached(client):
    test_client, _ = client
    for path in ("/", "/app.js", "/style.css"):
        res = test_client.get(path)
        assert res.headers["cache-control"] == "no-store"


# --- CSV import pipeline ------------------------------------------------

def upload(client, fixture_path, mapping="generic_uk_debit_credit"):
    with open(fixture_path, "rb") as f:
        return client.post(
            "/api/import",
            files={"file": ("statement.csv", f, "text/csv")},
            data={"mapping": mapping, "source": "csv"},
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


# --- settlement -----------------------------------------------------------

def test_settlement_requires_a_household(client):
    test_client, _ = client
    assert test_client.get("/api/settlement").status_code == 404


def test_settlement_endpoint_returns_household_balance(client):
    test_client, db = client
    test_client.post("/api/households", json={"name": "Home"})
    db.transactions.insert_one({"owner": "tiarnan", "amount": -200.0, "is_shared": True, "date": "2026-08-01"})

    response = test_client.get("/api/settlement")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "shares",
        "total_shared",
        "paid_by_member",
        "fair_share",
        "settled_sent",
        "settled_received",
        "balance",
        "transfers",
        "settlement_text",
    }
    assert body["total_shared"] == 200.0


def test_settlement_endpoint_respects_date_range(client):
    test_client, db = client
    test_client.post("/api/households", json={"name": "Home"})
    db.transactions.insert_many(
        [
            {"owner": "tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-07-15"},
            {"owner": "tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-08-15"},
        ]
    )

    body = test_client.get("/api/settlement", params={"start": "2026-08-01", "end": "2026-08-31"}).json()

    assert body["total_shared"] == 100.0  # only the August transaction


# --- manual add + inline edit -------------------------------------------

def test_create_transaction_runs_categorisation_and_sharing(client):
    test_client, db = client
    response = test_client.post(
        "/api/transactions",
        json={
            "date": "2026-09-01",
            "amount": -12.50,
            "description_raw": "TESCO STORES 123",
        },
    )

    assert response.status_code == 201
    body = response.json()
    # TESCO should hit an existing category_rules.yaml rule and then get
    # a sharing default from it - not asserting on a specific category
    # name here since that's a config detail, just that the pipeline ran.
    assert body["category"] is not None
    assert body["is_shared"] is not None
    assert db.transactions.count_documents({}) == 1


def test_create_transaction_respects_explicit_category_and_is_shared(client):
    test_client, db = client
    response = test_client.post(
        "/api/transactions",
        json={
            "date": "2026-09-01",
            "amount": -12.50,
            "description_raw": "SOME UNUSUAL MERCHANT XYZ",
            "category": "personal_care",
            "is_shared": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "personal_care"
    assert body["is_shared"] is True


def test_create_transaction_duplicate_returns_409(client):
    test_client, _ = client
    payload = {
        "date": "2026-09-01",
        "amount": -12.50,
        "description_raw": "TESCO STORES 123",
    }
    test_client.post("/api/transactions", json=payload)
    response = test_client.post("/api/transactions", json=payload)

    assert response.status_code == 409


def test_patch_updates_provided_fields_only(client):
    test_client, db = client
    result = db.transactions.insert_one(
        {"owner": "tiarnan", "account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-09-01", "description_raw": "TESCO", "amount": -10.0}
    )
    transaction_id = str(result.inserted_id)

    response = test_client.patch(f"/api/transactions/{transaction_id}", json={"category": "eating_out"})

    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "eating_out"
    assert body["is_shared"] is True  # untouched - only category was in the payload


def test_patch_unknown_id_returns_404(client):
    test_client, _ = client
    response = test_client.patch("/api/transactions/64b1f0c2e1a2b3c4d5e6f708", json={"category": "eating_out"})
    assert response.status_code == 404


def test_patch_invalid_id_returns_400(client):
    test_client, _ = client
    response = test_client.patch("/api/transactions/not-an-object-id", json={"category": "eating_out"})
    assert response.status_code == 400


def test_patch_no_fields_returns_400(client):
    test_client, db = client
    result = db.transactions.insert_one(
        {"owner": "tiarnan", "account_id": "a", "category": "groceries", "is_shared": True, "date": "2026-09-01", "description_raw": "TESCO", "amount": -10.0}
    )
    response = test_client.patch(f"/api/transactions/{result.inserted_id}", json={})
    assert response.status_code == 400
