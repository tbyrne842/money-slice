"""
Phase 12: deleting your own transactions, and keeping deleted imported rows
deleted when the same statement is uploaded again.
"""
from datetime import date

import mongomock
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

import api.main as api_main
from ingestion.csv_importer import save_transactions_detailed
from models import Transaction


@pytest.fixture
def client(monkeypatch):
    db = mongomock.MongoClient()["finance_tracker_test"]
    monkeypatch.setattr(api_main, "get_db", lambda: db)
    test_client = TestClient(api_main.app)
    res = test_client.post("/api/auth/register", json={"username": "tiarnan", "password": "correct horse battery"})
    assert res.status_code == 201
    return test_client, db


def upload(client, path, mapping="generic_uk_debit_credit"):
    with open(path, "rb") as f:
        return client.post(
            "/api/import",
            files={"file": ("statement.csv", f, "text/csv")},
            data={"mapping": mapping, "source": "csv"},
        )


def rows(client):
    return client.get("/api/transactions").json()["items"]


def test_delete_removes_own_row(client, fixture_path):
    test_client, db = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    target = rows(test_client)[0]

    res = test_client.delete(f"/api/transactions/{target['_id']}")

    assert res.status_code == 200
    assert res.json() == {"deleted": target["_id"]}
    assert target["_id"] not in [r["_id"] for r in rows(test_client)]
    assert db.transactions.count_documents({}) == 1


def test_delete_unknown_id_returns_404(client):
    test_client, _ = client
    assert test_client.delete(f"/api/transactions/{ObjectId()}").status_code == 404


def test_delete_invalid_id_returns_400(client):
    test_client, _ = client
    assert test_client.delete("/api/transactions/not-an-id").status_code == 400


def test_delete_requires_sign_in(client):
    test_client, _ = client
    test_client.post("/api/auth/logout")
    assert test_client.delete(f"/api/transactions/{ObjectId()}").status_code == 401


def test_cannot_delete_someone_elses_row(client):
    test_client, db = client
    other_id = ObjectId()
    db.transactions.insert_one(
        {"_id": other_id, "owner": "someone_else", "source": "csv", "source_hash": "h1", "date": "2026-09-01"}
    )

    assert test_client.delete(f"/api/transactions/{other_id}").status_code == 404
    assert db.transactions.count_documents({"_id": other_id}) == 1
    assert db.import_exclusions.count_documents({}) == 0


def test_deleted_imported_row_stays_deleted_when_statement_is_uploaded_again(client, fixture_path):
    test_client, db = client
    path = fixture_path("generic_uk_debit_credit.csv")
    upload(test_client, path)
    target = rows(test_client)[0]
    test_client.delete(f"/api/transactions/{target['_id']}")

    body = upload(test_client, path).json()

    assert body["inserted"] == 0
    assert body["previously_deleted"] == 1
    assert body["already_imported"] == 1
    assert db.transactions.count_documents({}) == 1


def test_deleting_one_of_identical_rows_keeps_it_deleted_and_the_other_untouched(client, tmp_path):
    test_client, db = client
    csv = tmp_path / "twins.csv"
    csv.write_text(
        "Date,Description,Debit Amount,Credit Amount\n"
        "19/07/2026,BA FLIGHT,59.65,\n"
        "19/07/2026,BA FLIGHT,59.65,\n"
    )
    upload(test_client, str(csv))
    assert db.transactions.count_documents({}) == 2

    test_client.delete(f"/api/transactions/{rows(test_client)[0]['_id']}")
    body = upload(test_client, str(csv)).json()

    assert (body["inserted"], body["previously_deleted"], body["already_imported"]) == (0, 1, 1)
    assert db.transactions.count_documents({}) == 1


def test_deleting_a_manual_row_leaves_no_marker_and_it_can_be_added_again(client):
    test_client, db = client
    payload = {"date": "2026-09-01", "description_raw": "CASH", "amount": -5.0}
    created = test_client.post("/api/transactions", json=payload)
    assert created.status_code == 201

    test_client.delete(f"/api/transactions/{rows(test_client)[0]['_id']}")

    assert db.import_exclusions.count_documents({}) == 0
    assert test_client.post("/api/transactions", json=payload).status_code == 201


def test_another_users_deletion_does_not_hide_rows_from_my_imports(client, fixture_path):
    test_client, db = client
    db.import_exclusions.insert_one({"user": "someone_else", "source_hash": "irrelevant"})
    body = upload(test_client, fixture_path("generic_uk_debit_credit.csv")).json()

    assert body["inserted"] == 2
    assert body["previously_deleted"] == 0


def test_save_detailed_skips_excluded_hashes_and_counts_them(mongo_db):
    txn = Transaction(
        account_id="acct", owner="tiarnan", date=date(2026, 9, 1), amount=-1.0, description_raw="X"
    ).finalize()

    result = save_transactions_detailed([txn], excluded={txn.source_hash})

    assert (result.inserted, result.previously_deleted) == (0, 1)
    assert mongo_db.transactions.count_documents({}) == 0
