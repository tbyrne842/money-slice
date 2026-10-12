"""
Phase 10: upload summary fields, the import log, and the import-status
endpoint (last mapping used, per-bank recency, stale-data warning).
"""
from datetime import date, datetime

import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from ingestion.import_log import import_status


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


# --- upload summary ---------------------------------------------------------

def test_upload_summary_reports_rows_dates_and_new_preview(client, fixture_path):
    test_client, _ = client
    body = upload(test_client, fixture_path("generic_uk_debit_credit.csv")).json()

    assert body["rows_in_file"] == 2
    assert body["skipped_no_amount"] == 0
    assert body["already_imported"] == 0
    assert body["identical_extra_rows"] == 0
    assert body["date_from"] == "2026-08-15"
    assert body["date_to"] == "2026-08-20"
    assert [p["date"] for p in body["new_preview"]] == ["2026-08-20", "2026-08-15"]  # newest first
    assert set(body["new_preview"][0]) == {"date", "description", "amount"}


def test_upload_summary_reports_skipped_balance_row(client, fixture_path):
    test_client, _ = client
    body = upload(test_client, fixture_path("natwest_with_balance_row.csv"), mapping="natwest").json()

    assert body["rows_in_file"] == 3
    assert body["skipped_no_amount"] == 1
    assert body["inserted"] == 2


def test_reupload_summary_counts_everything_as_already_imported(client, fixture_path):
    test_client, _ = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    body = upload(test_client, fixture_path("generic_uk_debit_credit.csv")).json()

    assert body["inserted"] == 0
    assert body["already_imported"] == 2
    assert body["duplicates"] == 2
    assert body["new_preview"] == []


def test_upload_imports_identical_rows_as_separate_purchases_and_lists_them(client, tmp_path):
    test_client, db = client
    csv = tmp_path / "repeat.csv"
    csv.write_text(
        "Date,Description,Debit Amount,Credit Amount\n"
        "01/09/2026,COFFEE SHOP,2.50,\n"
        "01/09/2026,COFFEE SHOP,2.50,\n"
        "02/09/2026,BUS,1.80,\n"
    )
    body = upload(test_client, str(csv)).json()

    assert body["inserted"] == 3
    assert body["already_imported"] == 0
    assert body["identical_extra_rows"] == 1
    assert body["identical_rows"] == [
        {"date": "2026-09-01", "description": "COFFEE SHOP", "amount": -2.5, "copies": 2}
    ]
    assert db.transactions.count_documents({"description_raw": "COFFEE SHOP"}) == 2

    again = upload(test_client, str(csv)).json()
    assert (again["inserted"], again["already_imported"]) == (0, 3)


# --- import status ------------------------------------------------------------

def test_status_is_empty_before_any_import(client):
    test_client, _ = client
    body = test_client.get("/api/import/status").json()

    assert body["last_mapping"] is None
    assert body["banks"] == []
    assert body["stale_after_days"] == 35


def test_status_remembers_last_mapping_and_lists_banks(client, fixture_path):
    test_client, _ = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    upload(test_client, fixture_path("natwest.csv"), mapping="natwest")
    body = test_client.get("/api/import/status").json()

    assert body["last_mapping"] == "natwest"
    assert [b["mapping"] for b in body["banks"]] == ["natwest", "generic_uk_debit_credit"]
    assert body["banks"][1]["latest_data_date"] == "2026-08-20"


def test_failed_upload_does_not_change_last_mapping(client, fixture_path):
    test_client, _ = client
    upload(test_client, fixture_path("generic_uk_debit_credit.csv"))
    assert upload(test_client, fixture_path("natwest.csv"), mapping="nope").status_code == 400

    assert test_client.get("/api/import/status").json()["last_mapping"] == "generic_uk_debit_credit"


def test_status_requires_sign_in(client):
    test_client, _ = client
    test_client.post("/api/auth/logout")
    assert test_client.get("/api/import/status").status_code == 401


def test_status_only_shows_the_signed_in_users_imports(client):
    test_client, db = client
    db.import_log.insert_one(
        {"user": "someone_else", "mapping": "monzo", "at": datetime(2026, 10, 1), "date_to": "2026-09-30"}
    )
    body = test_client.get("/api/import/status").json()

    assert body["last_mapping"] is None
    assert body["banks"] == []


# --- staleness (pure function, fixed 'today') ----------------------------------

def _log(db, mapping, at, date_to):
    db.import_log.insert_one({"user": "u", "mapping": mapping, "at": at, "date_to": date_to})


def test_bank_is_stale_when_data_stops_over_35_days_ago():
    db = mongomock.MongoClient()["t"]
    _log(db, "monzo", datetime(2026, 10, 9), "2026-08-31")  # uploaded yesterday, but data ends 40 days back
    bank = import_status(db, "u", today=date(2026, 10, 10))["banks"][0]

    assert bank["days_since_data"] == 40
    assert bank["stale"] is True


def test_bank_is_not_stale_at_exactly_35_days():
    db = mongomock.MongoClient()["t"]
    _log(db, "monzo", datetime(2026, 9, 6), "2026-09-05")
    bank = import_status(db, "u", today=date(2026, 10, 10))["banks"][0]

    assert bank["days_since_data"] == 35
    assert bank["stale"] is False


def test_staleness_uses_newest_data_date_across_imports():
    db = mongomock.MongoClient()["t"]
    _log(db, "monzo", datetime(2026, 10, 1), "2026-09-30")
    _log(db, "monzo", datetime(2026, 10, 2), "2026-06-30")  # older statement uploaded later
    bank = import_status(db, "u", today=date(2026, 10, 10))["banks"][0]

    assert bank["latest_data_date"] == "2026-09-30"
    assert bank["stale"] is False


def test_empty_file_import_falls_back_to_upload_date_for_staleness():
    db = mongomock.MongoClient()["t"]
    _log(db, "monzo", datetime(2026, 10, 9), None)
    bank = import_status(db, "u", today=date(2026, 10, 10))["banks"][0]

    assert bank["latest_data_date"] is None
    assert bank["days_since_data"] == 1
    assert bank["stale"] is False
