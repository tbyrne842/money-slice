"""Recording, listing and deleting settle-up payments through the HTTP layer."""
from datetime import date, timedelta

import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main

PASSWORD = "correct horse battery"


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient()["finance_tracker_test"]
    monkeypatch.setattr(api_main, "get_db", lambda: database)
    return database


def user(username):
    client = TestClient(api_main.app)
    assert client.post("/api/auth/register", json={"username": username, "password": PASSWORD}).status_code == 201
    return client


def household_with(*names):
    clients = [user(n) for n in names]
    code = clients[0].post("/api/households", json={"name": "Home"}).json()["invite_code"]
    for c in clients[1:]:
        assert c.post("/api/households/join", json={"invite_code": code}).status_code == 200
    return clients


def pay(client, payer, payee, amount, **extra):
    return client.post("/api/households/me/payments", json={"payer": payer, "payee": payee, "amount": amount, **extra})


def shared_txn(owner, amount):
    return {"owner": owner, "amount": amount, "is_shared": True, "date": "2026-08-01", "category": "groceries"}


def test_login_required(db):
    c = TestClient(api_main.app)
    assert c.post("/api/households/me/payments", json={}).status_code == 401
    assert c.get("/api/households/me/payments").status_code == 401
    assert c.delete("/api/households/me/payments/abc").status_code == 401


def test_record_payment_defaults_date_to_today_and_shows_in_list(db):
    tiarnan, deirbhile = household_with("tiarnan", "deirbhile")

    res = pay(tiarnan, "tiarnan", "deirbhile", 25.5, note="  for  the shop ")

    assert res.status_code == 201
    body = res.json()
    assert (body["payer"], body["payee"], body["amount"]) == ("tiarnan", "deirbhile", 25.5)
    assert body["date"] == date.today().isoformat()
    assert body["note"] == "for the shop"
    assert body["recorded_by"] == "tiarnan"
    assert deirbhile.get("/api/households/me/payments").json() == [body]


def test_payment_moves_the_settlement(db):
    tiarnan, deirbhile = household_with("tiarnan", "deirbhile")
    db.transactions.insert_one(shared_txn("deirbhile", -200.0))
    assert tiarnan.get("/api/settlement").json()["balance"] == {"tiarnan": -100.0, "deirbhile": 100.0}

    pay(tiarnan, "tiarnan", "deirbhile", 100.0)

    body = tiarnan.get("/api/settlement").json()
    assert body["balance"] == {"tiarnan": 0.0, "deirbhile": 0.0}
    assert body["settlement_text"] == "Already settled - nothing owed either way"


def test_either_party_can_record_but_not_a_third_person(db):
    tiarnan, deirbhile, sam = household_with("tiarnan", "deirbhile", "sam")

    assert pay(deirbhile, "tiarnan", "deirbhile", 10.0).status_code == 201  # recipient records it
    assert pay(sam, "tiarnan", "deirbhile", 10.0).status_code == 403
    assert db.settle_ups.count_documents({}) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"payer": "tiarnan", "payee": "tiarnan", "amount": 5},  # same person
        {"payer": "tiarnan", "payee": "stranger", "amount": 5},  # not a member
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 0},
        {"payer": "tiarnan", "payee": "deirbhile", "amount": -5},
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 0.001},  # rounds to nothing
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 5_000_000},
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 5, "note": "x" * 201},
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 5, "date": (date.today() + timedelta(days=1)).isoformat()},
        {"payer": "tiarnan", "payee": "deirbhile", "amount": 5, "date": "not-a-date"},
    ],
)
def test_invalid_payments_are_rejected(db, payload):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    assert tiarnan.post("/api/households/me/payments", json=payload).status_code in (400, 422)
    assert db.settle_ups.count_documents({}) == 0


def test_nan_amount_is_rejected(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    res = tiarnan.post(
        "/api/households/me/payments",
        content='{"payer": "tiarnan", "payee": "deirbhile", "amount": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code in (400, 422)
    assert db.settle_ups.count_documents({}) == 0


def test_amount_is_rounded_to_pence(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    assert pay(tiarnan, "tiarnan", "deirbhile", 10.456).json()["amount"] == 10.46


def test_list_is_newest_first(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    pay(tiarnan, "tiarnan", "deirbhile", 1, date="2026-08-01")
    pay(tiarnan, "tiarnan", "deirbhile", 3, date="2026-08-20")
    pay(tiarnan, "tiarnan", "deirbhile", 2, date="2026-08-10")
    assert [p["amount"] for p in tiarnan.get("/api/households/me/payments").json()] == [3, 2, 1]


def test_only_the_recorder_can_delete(db):
    tiarnan, deirbhile = household_with("tiarnan", "deirbhile")
    payment_id = pay(tiarnan, "tiarnan", "deirbhile", 10.0).json()["id"]

    assert deirbhile.delete(f"/api/households/me/payments/{payment_id}").status_code == 403
    assert db.settle_ups.count_documents({}) == 1
    assert tiarnan.delete(f"/api/households/me/payments/{payment_id}").status_code == 200
    assert db.settle_ups.count_documents({}) == 0
    assert tiarnan.delete(f"/api/households/me/payments/{payment_id}").status_code == 404


def test_deleting_a_payment_restores_the_balance(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    db.transactions.insert_one(shared_txn("deirbhile", -200.0))
    payment_id = pay(tiarnan, "tiarnan", "deirbhile", 100.0).json()["id"]
    tiarnan.delete(f"/api/households/me/payments/{payment_id}")
    assert tiarnan.get("/api/settlement").json()["balance"]["tiarnan"] == -100.0


def test_delete_with_garbage_id_is_404(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    assert tiarnan.delete("/api/households/me/payments/not-an-id").status_code == 404


# --- non-members and other households see nothing ----------------------------

def test_non_member_cannot_record_list_or_delete(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    payment_id = pay(tiarnan, "tiarnan", "deirbhile", 10.0).json()["id"]
    outsider = user("sam")

    assert pay(outsider, "tiarnan", "deirbhile", 10.0).status_code == 404
    assert outsider.get("/api/households/me/payments").status_code == 404
    assert outsider.delete(f"/api/households/me/payments/{payment_id}").status_code == 404
    assert db.settle_ups.count_documents({}) == 1


def test_another_household_cannot_see_or_delete_payments(db):
    tiarnan, _ = household_with("tiarnan", "deirbhile")
    other_a, other_b = household_with("alice", "adam")
    payment_id = pay(tiarnan, "tiarnan", "deirbhile", 10.0).json()["id"]

    assert other_a.get("/api/households/me/payments").json() == []
    assert other_b.delete(f"/api/households/me/payments/{payment_id}").status_code == 404
    assert other_a.get("/api/settlement").json()["settled_sent"] == {"alice": 0.0, "adam": 0.0}


def test_last_member_leaving_deletes_the_households_payments(db):
    tiarnan, deirbhile = household_with("tiarnan", "deirbhile")
    pay(tiarnan, "tiarnan", "deirbhile", 10.0)
    deirbhile.post("/api/households/me/leave")
    assert db.settle_ups.count_documents({}) == 1  # household still exists
    tiarnan.post("/api/households/me/leave")
    assert db.settle_ups.count_documents({}) == 0
