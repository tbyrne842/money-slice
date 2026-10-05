"""Sign-in, session handling and per-user data isolation through the HTTP layer."""
import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from auth import MAX_FAILURES

PASSWORD = "correct horse battery"


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient()["finance_tracker_test"]
    monkeypatch.setattr(api_main, "get_db", lambda: database)
    return database


def new_client(username=None, password=PASSWORD):
    client = TestClient(api_main.app)
    if username:
        assert client.post("/api/auth/register", json={"username": username, "password": password}).status_code == 201
    return client


PROTECTED_GETS = ["/api/transactions", "/api/categories", "/api/accounts", "/api/mappings", "/api/settlement", "/api/auth/me", "/api/households/me"]


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_protected_endpoints_require_login(db, path):
    assert new_client().get(path).status_code == 401


def test_write_endpoints_require_login(db):
    client = new_client()
    assert client.post("/api/transactions", json={"date": "2026-08-01", "amount": -1, "description_raw": "x"}).status_code == 401
    assert client.patch("/api/transactions/64b1f0c2e1a2b3c4d5e6f708", json={"category": "x"}).status_code == 401
    assert client.post("/api/import", data={"mapping": "m"}, files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401


def test_health_and_static_pages_stay_public(db):
    client = new_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


def test_register_logs_in_and_stores_a_hash_not_the_password(db):
    client = new_client("Tiarnan")
    assert client.get("/api/auth/me").json() == {"username": "tiarnan"}
    stored = db.users.find_one({"username": "tiarnan"})
    assert stored["password_hash"] != PASSWORD
    assert PASSWORD not in str(stored)


@pytest.mark.parametrize(
    "username,password",
    [("ab", PASSWORD), ("has space", PASSWORD), ("bad/name", PASSWORD), ("validname", "short")],
)
def test_register_rejects_invalid_credentials(db, username, password):
    res = new_client().post("/api/auth/register", json={"username": username, "password": password})
    assert res.status_code == 400


def test_register_rejects_duplicate_username_case_insensitively(db):
    new_client("tiarnan")
    res = new_client().post("/api/auth/register", json={"username": "TIARNAN", "password": PASSWORD})
    assert res.status_code == 400


def test_login_and_logout(db):
    new_client("tiarnan")
    client = new_client()
    assert client.post("/api/auth/login", json={"username": "tiarnan", "password": PASSWORD}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_login_wrong_password_and_unknown_user_look_identical(db):
    new_client("tiarnan")
    client = new_client()
    wrong = client.post("/api/auth/login", json={"username": "tiarnan", "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_repeated_failures_lock_the_account_even_for_the_right_password(db):
    new_client("tiarnan")
    client = new_client()
    for _ in range(MAX_FAILURES):
        assert client.post("/api/auth/login", json={"username": "tiarnan", "password": "wrong password!"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "tiarnan", "password": PASSWORD}).status_code == 429


def test_users_only_see_their_own_transactions(db):
    tiarnan, deirbhile = new_client("tiarnan"), new_client("deirbhile")
    db.transactions.insert_many(
        [
            {"owner": "tiarnan", "account_id": "tiarnan", "category": "groceries", "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0},
            {"owner": "deirbhile", "account_id": "deirbhile", "category": "clothing", "date": "2026-08-01", "description_raw": "ZARA", "amount": -20.0},
        ]
    )

    assert [t["description_raw"] for t in tiarnan.get("/api/transactions").json()["items"]] == ["TESCO"]
    assert [t["description_raw"] for t in deirbhile.get("/api/transactions").json()["items"]] == ["ZARA"]
    assert tiarnan.get("/api/categories").json() == ["groceries"]
    assert deirbhile.get("/api/accounts").json() == ["deirbhile"]


def test_cannot_edit_another_users_transaction(db):
    tiarnan, deirbhile = new_client("tiarnan"), new_client("deirbhile")
    txn_id = db.transactions.insert_one(
        {"owner": "tiarnan", "account_id": "tiarnan", "category": "groceries", "date": "2026-08-01", "description_raw": "TESCO", "amount": -10.0}
    ).inserted_id

    res = deirbhile.patch(f"/api/transactions/{txn_id}", json={"category": "eating_out"})

    assert res.status_code == 404
    assert db.transactions.find_one({"_id": txn_id})["category"] == "groceries"
    assert tiarnan.patch(f"/api/transactions/{txn_id}", json={"category": "eating_out"}).status_code == 200


def test_created_and_imported_transactions_belong_to_the_signed_in_user(db, fixture_path):
    deirbhile = new_client("deirbhile")
    res = deirbhile.post("/api/transactions", json={"date": "2026-08-01", "amount": -5.0, "description_raw": "COFFEE"})
    assert res.status_code == 201
    with open(fixture_path("generic_uk_debit_credit.csv"), "rb") as f:
        assert deirbhile.post("/api/import", data={"mapping": "generic_uk_debit_credit"}, files={"file": ("s.csv", f, "text/csv")}).status_code == 200

    owners = {t["owner"] for t in db.transactions.find()}
    assert owners == {"deirbhile"}
    assert new_client("tiarnan").get("/api/transactions").json()["total"] == 0
