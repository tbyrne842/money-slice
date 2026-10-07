"""The one-off conversion of partner_contribution rows into settle-up records."""
import mongomock
import pytest

from households import create_household, join_household
from sharing.migrate_settle_ups import migrate
from sharing.settlement import calculate_settlement


@pytest.fixture
def household(mongo_db):
    create_household(mongo_db, "tiarnan", "Home")
    code = mongo_db.households.find_one({})["invite_code"]
    return join_household(mongo_db, "deirbhile", code)


def transfer(owner, amount, day="2026-08-05", **extra):
    return {"owner": owner, "amount": amount, "is_shared": False, "category": "partner_contribution", "date": day, **extra}


def spend(owner, amount):
    return {"owner": owner, "amount": amount, "is_shared": True, "date": "2026-08-01", "category": "groceries"}


def test_dry_run_writes_nothing_but_previews_the_balance(mongo_db, household):
    mongo_db.transactions.insert_many([spend("deirbhile", -200.0), transfer("tiarnan", -60.0)])

    result = migrate(mongo_db, household)

    assert result["applied"] is False
    assert result["converted"] == 1
    assert result["total_by_payer"] == {"tiarnan": 60.0, "deirbhile": 0.0}
    assert result["balance"] == {"tiarnan": -40.0, "deirbhile": 40.0}
    assert mongo_db.settle_ups.count_documents({}) == 0


def test_apply_creates_records_and_balance_matches_the_preview(mongo_db, household):
    mongo_db.transactions.insert_many(
        [spend("deirbhile", -200.0), transfer("tiarnan", -60.0, "2026-08-05"), transfer("deirbhile", -10.0, "2026-08-09")]
    )
    preview = migrate(mongo_db, household)

    applied = migrate(mongo_db, household, apply=True)

    docs = list(mongo_db.settle_ups.find({}))
    assert applied["converted"] == 2 and len(docs) == 2
    assert {(d["payer"], d["payee"], d["amount"], d["date"]) for d in docs} == {
        ("tiarnan", "deirbhile", 60.0, "2026-08-05"),
        ("deirbhile", "tiarnan", 10.0, "2026-08-09"),
    }
    assert all(d["household_id"] == household["_id"] and d["source_txn_id"] for d in docs)
    live = calculate_settlement(mongo_db, {"tiarnan": 0.5, "deirbhile": 0.5}, household_id=household["_id"])
    assert live["balance"] == preview["balance"] == applied["balance"]


def test_rerunning_does_not_duplicate(mongo_db, household):
    mongo_db.transactions.insert_one(transfer("tiarnan", -60.0))
    migrate(mongo_db, household, apply=True)

    again = migrate(mongo_db, household, apply=True)

    assert again["converted"] == 0 and again["already_converted"] == 1
    assert mongo_db.settle_ups.count_documents({}) == 1


def test_incoming_mirror_rows_are_not_converted(mongo_db, household):
    mongo_db.transactions.insert_many([transfer("tiarnan", -60.0), transfer("deirbhile", 60.0)])
    assert migrate(mongo_db, household, apply=True)["converted"] == 1


def test_malformed_rows_are_skipped_and_counted(mongo_db, household):
    mongo_db.transactions.insert_many([transfer("tiarnan", -60.0, day=None), transfer("tiarnan", -20.0)])
    result = migrate(mongo_db, household, apply=True)
    assert (result["converted"], result["skipped_malformed"]) == (1, 1)


def test_non_members_rows_are_ignored(mongo_db, household):
    mongo_db.transactions.insert_one(transfer("outsider", -60.0))
    assert migrate(mongo_db, household)["converted"] == 0


def test_only_two_person_households_can_be_migrated(mongo_db, household):
    code = mongo_db.households.find_one({})["invite_code"]
    third = join_household(mongo_db, "sam", code)
    with pytest.raises(ValueError):
        migrate(mongo_db, third)
