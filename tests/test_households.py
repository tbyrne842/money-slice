"""Households: create/join/leave, shares, and who can see or edit what through the HTTP layer."""
import mongomock
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from households import MAX_JOIN_FAILURES

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


def txn(owner, amount=-10.0, is_shared=True, desc="X"):
    return {"owner": owner, "account_id": owner, "category": "groceries", "is_shared": is_shared,
            "date": "2026-08-01", "description_raw": desc, "amount": amount}


def household_with(db, *names):
    clients = [user(n) for n in names]
    code = clients[0].post("/api/households", json={"name": "Home"}).json()["invite_code"]
    for c in clients[1:]:
        assert c.post("/api/households/join", json={"invite_code": code}).status_code == 200
    return clients, code


# --- create / join / leave ------------------------------------------------

def test_login_required(db):
    c = TestClient(api_main.app)
    assert c.post("/api/households", json={"name": "x"}).status_code == 401
    assert c.post("/api/households/join", json={"invite_code": "x"}).status_code == 401
    assert c.get("/api/households/me").status_code == 401
    assert c.put("/api/households/me/shares", json={"shares": {}}).status_code == 401
    assert c.post("/api/households/me/leave").status_code == 401
    assert c.post("/api/households/me/invite-code").status_code == 401


def test_create_household_makes_creator_sole_member(db):
    body = user("tiarnan").post("/api/households", json={"name": "  Home  "}).json()
    assert body["name"] == "Home"
    assert body["members"] == [{"username": "tiarnan", "share": 1.0}]
    assert len(body["invite_code"]) == 8


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
def test_create_rejects_bad_names(db, name):
    assert user("tiarnan").post("/api/households", json={"name": name}).status_code == 400


def test_cannot_be_in_two_households(db):
    c = user("tiarnan")
    c.post("/api/households", json={"name": "Home"})
    assert c.post("/api/households", json={"name": "Other"}).status_code == 409
    other_code = user("sam").post("/api/households", json={"name": "Sam"}).json()["invite_code"]
    assert c.post("/api/households/join", json={"invite_code": other_code}).status_code == 409


def test_join_resets_shares_to_equal_and_is_forgiving_about_code_format(db):
    (tiarnan, deirbhile), code = household_with(db, "tiarnan", "deirbhile")
    members = tiarnan.get("/api/households/me").json()["members"]
    assert [m["share"] for m in members] == [0.5, 0.5]

    third = user("sam")
    sloppy = f" {code[:4].lower()}-{code[4:].lower()} "
    assert third.post("/api/households/join", json={"invite_code": sloppy}).status_code == 200
    shares = [m["share"] for m in tiarnan.get("/api/households/me").json()["members"]]
    assert shares == [1 / 3] * 3


def test_invalid_code_is_404_then_locks_out(db):
    c = user("sam")
    for _ in range(MAX_JOIN_FAILURES):
        assert c.post("/api/households/join", json={"invite_code": "WRONGCODE"}).status_code == 404
    assert c.post("/api/households/join", json={"invite_code": "WRONGCODE"}).status_code == 429


def test_lockout_blocks_even_the_right_code(db):
    code = user("tiarnan").post("/api/households", json={"name": "Home"}).json()["invite_code"]
    c = user("sam")
    for _ in range(MAX_JOIN_FAILURES):
        c.post("/api/households/join", json={"invite_code": "WRONGCODE"})
    assert c.post("/api/households/join", json={"invite_code": code}).status_code == 429


def test_leave_resets_shares_and_last_leaver_deletes_household(db):
    (tiarnan, deirbhile), _ = household_with(db, "tiarnan", "deirbhile")
    assert deirbhile.post("/api/households/me/leave").status_code == 200
    assert deirbhile.get("/api/households/me").status_code == 404
    assert tiarnan.get("/api/households/me").json()["members"] == [{"username": "tiarnan", "share": 1.0}]

    tiarnan.post("/api/households/me/leave")
    assert db.households.count_documents({}) == 0
    assert tiarnan.post("/api/households/me/leave").status_code == 404


def test_rotating_the_invite_code_invalidates_the_old_one(db):
    (tiarnan,), old = household_with(db, "tiarnan")
    new = tiarnan.post("/api/households/me/invite-code").json()["invite_code"]
    assert new != old
    assert user("sam").post("/api/households/join", json={"invite_code": old}).status_code == 404
    assert user("alex").post("/api/households/join", json={"invite_code": new}).status_code == 200


# --- shares ---------------------------------------------------------------

def test_set_shares(db):
    (tiarnan, deirbhile), _ = household_with(db, "tiarnan", "deirbhile")
    res = deirbhile.put("/api/households/me/shares", json={"shares": {"tiarnan": 0.6, "deirbhile": 0.4}})
    assert res.status_code == 200
    assert {m["username"]: m["share"] for m in tiarnan.get("/api/households/me").json()["members"]} == {
        "tiarnan": 0.6, "deirbhile": 0.4}


@pytest.mark.parametrize(
    "shares",
    [
        {"tiarnan": 0.6, "deirbhile": 0.5},  # sums to 1.1
        {"tiarnan": 0.4, "deirbhile": 0.4},  # sums to 0.8
        {"tiarnan": 1.5, "deirbhile": -0.5},  # sums to 1 but out of range
        {"tiarnan": 1.0},  # missing a member
        {"tiarnan": 0.5, "deirbhile": 0.25, "stranger": 0.25},  # not a member
    ],
)
def test_set_shares_rejects_invalid(db, shares):
    (tiarnan, _), _ = household_with(db, "tiarnan", "deirbhile")
    assert tiarnan.put("/api/households/me/shares", json={"shares": shares}).status_code in (400, 422)
    assert [m["share"] for m in tiarnan.get("/api/households/me").json()["members"]] == [0.5, 0.5]


def test_set_shares_rejects_nan(db):
    (tiarnan, _), _ = household_with(db, "tiarnan", "deirbhile")
    res = tiarnan.put(
        "/api/households/me/shares",
        content='{"shares": {"tiarnan": NaN, "deirbhile": 0.5}}',
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code in (400, 422)


def test_non_member_cannot_set_shares(db):
    household_with(db, "tiarnan", "deirbhile")
    outsider = user("sam")
    assert outsider.put("/api/households/me/shares", json={"shares": {"tiarnan": 1.0, "deirbhile": 0.0}}).status_code == 404


# --- view yes, edit no ----------------------------------------------------

def test_members_see_each_others_transactions_and_can_filter_by_owner(db):
    (tiarnan, deirbhile), _ = household_with(db, "tiarnan", "deirbhile")
    db.transactions.insert_many([txn("tiarnan"), txn("deirbhile", is_shared=False)])

    assert tiarnan.get("/api/transactions").json()["total"] == 2
    assert {t["owner"] for t in deirbhile.get("/api/transactions").json()["items"]} == {"tiarnan", "deirbhile"}
    assert tiarnan.get("/api/transactions", params={"owner": "deirbhile"}).json()["total"] == 1
    assert tiarnan.get("/api/accounts").json() == ["deirbhile", "tiarnan"]


def test_members_cannot_edit_each_others_transactions(db):
    (tiarnan, deirbhile), _ = household_with(db, "tiarnan", "deirbhile")
    theirs = db.transactions.insert_one(txn("deirbhile")).inserted_id

    assert tiarnan.patch(f"/api/transactions/{theirs}", json={"category": "hacked"}).status_code == 404
    assert db.transactions.find_one({"_id": theirs})["category"] == "groceries"
    assert deirbhile.patch(f"/api/transactions/{theirs}", json={"category": "fuel"}).status_code == 200


# --- non-members see nothing ----------------------------------------------

def test_non_member_sees_only_their_own_transactions(db):
    household_with(db, "tiarnan", "deirbhile")
    outsider = user("sam")
    db.transactions.insert_many([txn("tiarnan"), txn("deirbhile"), txn("sam", desc="MINE")])

    items = outsider.get("/api/transactions").json()["items"]
    assert [t["description_raw"] for t in items] == ["MINE"]
    assert outsider.get("/api/accounts").json() == ["sam"]
    assert outsider.get("/api/categories").json() == ["groceries"]


@pytest.mark.parametrize("target", ["tiarnan", "deirbhile", "nobody"])
def test_non_member_cannot_filter_by_a_household_members_name(db, target):
    household_with(db, "tiarnan", "deirbhile")
    res = user("sam").get("/api/transactions", params={"owner": target})
    assert res.status_code == 404


def test_non_member_cannot_see_household_settlement_or_details(db):
    household_with(db, "tiarnan", "deirbhile")
    outsider = user("sam")
    assert outsider.get("/api/settlement").status_code == 404
    assert outsider.get("/api/households/me").status_code == 404


def test_non_member_cannot_edit_a_household_members_transaction(db):
    household_with(db, "tiarnan", "deirbhile")
    theirs = db.transactions.insert_one(txn("tiarnan")).inserted_id
    assert user("sam").patch(f"/api/transactions/{theirs}", json={"category": "x"}).status_code == 404


def test_separate_households_cannot_see_each_other(db):
    (a1, a2), _ = household_with(db, "alice", "adam")
    (b1, b2), _ = household_with(db, "bella", "ben")
    db.transactions.insert_many([txn("alice", -100.0), txn("bella", -40.0, desc="BELLA")])

    assert {t["owner"] for t in b2.get("/api/transactions").json()["items"]} == {"bella"}
    assert a1.get("/api/transactions", params={"owner": "bella"}).status_code == 404
    assert a2.get("/api/settlement").json()["total_shared"] == 100.0
    assert b1.get("/api/settlement").json()["total_shared"] == 40.0


def test_leaving_removes_access_to_the_household(db):
    (tiarnan, deirbhile), _ = household_with(db, "tiarnan", "deirbhile")
    db.transactions.insert_one(txn("deirbhile"))
    assert tiarnan.get("/api/transactions").json()["total"] == 1
    tiarnan.post("/api/households/me/leave")
    assert tiarnan.get("/api/transactions").json()["total"] == 0
    assert tiarnan.get("/api/settlement").status_code == 404


# --- settlement through the API -------------------------------------------

def test_settlement_uses_household_shares_and_member_balances(db):
    (tiarnan, deirbhile, sam), _ = household_with(db, "tiarnan", "deirbhile", "sam")
    tiarnan.put("/api/households/me/shares", json={"shares": {"tiarnan": 0.5, "deirbhile": 0.25, "sam": 0.25}})
    db.transactions.insert_many([txn("tiarnan", -300.0), txn("deirbhile", -100.0)])

    body = sam.get("/api/settlement").json()

    assert body["balance"] == {"tiarnan": 100.0, "deirbhile": 0.0, "sam": -100.0}
    assert body["transfers"] == [{"from": "sam", "to": "tiarnan", "amount": 100.0}]
