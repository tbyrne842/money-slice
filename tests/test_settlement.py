"""
Tests for calculate_settlement - each member's net balance (paid minus
fair share) and who should pay whom, for households of any size.
"""
from datetime import date

from sharing.settlement import calculate_settlement

PAIR = {"tiarnan": 0.5, "deirbhile": 0.5}


def shared(owner, amount, day="2026-08-01", **extra):
    return {"owner": owner, "amount": amount, "is_shared": True, "date": day, **extra}


def settle_up(owner, amount, day="2026-08-05"):
    return {"owner": owner, "amount": amount, "is_shared": False, "category": "partner_contribution", "date": day}


def test_even_split_when_both_paid_equally(mongo_db):
    mongo_db.transactions.insert_many([shared("tiarnan", -100.0), shared("deirbhile", -100.0)])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["total_shared"] == 200.0
    assert result["balance"] == {"tiarnan": 0.0, "deirbhile": 0.0}
    assert result["transfers"] == []
    assert result["settlement_text"] == "Already settled - nothing owed either way"


def test_balance_is_paid_minus_fair_share(mongo_db):
    mongo_db.transactions.insert_one(shared("tiarnan", -200.0))

    result = calculate_settlement(mongo_db, PAIR)

    assert result["balance"] == {"tiarnan": 100.0, "deirbhile": -100.0}  # positive = owed money
    assert result["transfers"] == [{"from": "deirbhile", "to": "tiarnan", "amount": 100.0}]
    assert result["settlement_text"] == "deirbhile owes tiarnan £100.00"


def test_uneven_shares_are_respected(mongo_db):
    mongo_db.transactions.insert_one(shared("tiarnan", -100.0))

    result = calculate_settlement(mongo_db, {"tiarnan": 0.6, "deirbhile": 0.4})

    assert result["fair_share"] == {"tiarnan": 60.0, "deirbhile": 40.0}
    assert result["balance"] == {"tiarnan": 40.0, "deirbhile": -40.0}


def test_three_people_with_unequal_shares(mongo_db):
    mongo_db.transactions.insert_many([shared("a", -300.0), shared("b", -100.0)])

    result = calculate_settlement(mongo_db, {"a": 0.5, "b": 0.25, "c": 0.25})

    assert result["total_shared"] == 400.0
    assert result["fair_share"] == {"a": 200.0, "b": 100.0, "c": 100.0}
    assert result["balance"] == {"a": 100.0, "b": 0.0, "c": -100.0}
    assert result["transfers"] == [{"from": "c", "to": "a", "amount": 100.0}]


def test_balances_sum_to_zero_and_transfers_clear_them(mongo_db):
    mongo_db.transactions.insert_many([shared("a", -90.0), shared("b", -10.0), shared("c", -20.0)])

    result = calculate_settlement(mongo_db, {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})

    assert round(sum(result["balance"].values()), 2) == 0
    settled = dict(result["balance"])
    for t in result["transfers"]:
        settled[t["from"]] += t["amount"]
        settled[t["to"]] -= t["amount"]
    assert all(abs(v) < 0.011 for v in settled.values())


def test_only_household_members_are_counted(mongo_db):
    mongo_db.transactions.insert_many([shared("tiarnan", -100.0), shared("outsider", -900.0)])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["total_shared"] == 100.0
    assert "outsider" not in result["paid_by_member"]


def test_non_shared_transactions_are_excluded(mongo_db):
    mongo_db.transactions.insert_many(
        [
            shared("tiarnan", -100.0),
            {"owner": "tiarnan", "amount": -500.0, "is_shared": False, "date": "2026-08-01"},
            {"owner": "tiarnan", "amount": -50.0, "is_shared": None, "date": "2026-08-01"},
        ]
    )
    assert calculate_settlement(mongo_db, PAIR)["total_shared"] == 100.0


def test_incoming_transactions_do_not_count_as_shared_cost(mongo_db):
    mongo_db.transactions.insert_one(shared("tiarnan", 50.0))
    assert calculate_settlement(mongo_db, PAIR)["total_shared"] == 0.0


def test_date_range_filters_correctly(mongo_db):
    mongo_db.transactions.insert_many([shared("tiarnan", -100.0, "2026-07-15"), shared("tiarnan", -50.0, "2026-08-15")])

    result = calculate_settlement(mongo_db, PAIR, start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert result["total_shared"] == 50.0


def test_row_without_owner_is_ignored(mongo_db):
    mongo_db.transactions.insert_one({"amount": -100.0, "is_shared": True, "date": "2026-08-01"})
    assert calculate_settlement(mongo_db, PAIR)["total_shared"] == 0.0


# --- settle-up payments (two-person households) ---------------------------

def test_settle_up_from_the_debtor_reduces_what_they_owe(mongo_db):
    mongo_db.transactions.insert_many([shared("deirbhile", -200.0), settle_up("tiarnan", -60.0)])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["settled_sent"]["tiarnan"] == 60.0
    assert result["settled_received"]["deirbhile"] == 60.0
    assert result["balance"] == {"tiarnan": -40.0, "deirbhile": 40.0}  # owed £100, paid £60


def test_settle_up_in_full_clears_the_balance(mongo_db):
    mongo_db.transactions.insert_many([shared("tiarnan", -200.0), settle_up("deirbhile", -100.0)])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["balance"] == {"tiarnan": 0.0, "deirbhile": 0.0}
    assert result["settlement_text"] == "Already settled - nothing owed either way"


def test_settle_up_overpayment_flips_who_is_owed(mongo_db):
    mongo_db.transactions.insert_many([shared("deirbhile", -200.0), settle_up("tiarnan", -150.0)])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["balance"] == {"tiarnan": 50.0, "deirbhile": -50.0}
    assert result["settlement_text"] == "deirbhile owes tiarnan £50.00"


def test_incoming_mirrored_settle_up_leg_is_not_double_counted(mongo_db):
    mirrored = {**settle_up("deirbhile", 60.0)}  # credit leg of the same transfer
    mongo_db.transactions.insert_many([shared("deirbhile", -200.0), settle_up("tiarnan", -60.0), mirrored])

    result = calculate_settlement(mongo_db, PAIR)

    assert result["settled_sent"]["tiarnan"] == 60.0  # not 120.0
    assert result["balance"]["tiarnan"] == -40.0


def test_mis_flagged_shared_settle_up_is_not_counted_as_spend(mongo_db):
    mongo_db.transactions.insert_one({**settle_up("tiarnan", -60.0), "is_shared": True})

    result = calculate_settlement(mongo_db, PAIR)

    assert result["total_shared"] == 0.0
    assert result["settled_sent"]["tiarnan"] == 60.0


def test_settle_ups_are_ignored_but_counted_in_larger_households(mongo_db):
    mongo_db.transactions.insert_many([shared("a", -300.0), settle_up("b", -50.0)])

    result = calculate_settlement(mongo_db, {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})

    assert result["unattributed_settle_ups"] == 1
    assert result["settled_sent"] == {"a": 0.0, "b": 0.0, "c": 0.0}
    assert result["balance"] == {"a": 200.0, "b": -100.0, "c": -100.0}
