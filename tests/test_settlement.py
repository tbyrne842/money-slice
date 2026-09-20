"""
Tests for calculate_settlement - who owes whom, given a ratio and the
shared transactions recorded so far.
"""
from datetime import date

from sharing.settlement import calculate_settlement

OWNERS = {"natwest-tiarnan": "tiarnan", "aib-deirbhile": "deirbhile"}


def test_even_split_when_both_paid_equally_at_50_50(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"account_id": "natwest-tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-08-01"},
            {"account_id": "aib-deirbhile", "amount": -100.0, "is_shared": True, "date": "2026-08-02"},
        ]
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["total_shared"] == 200.0
    assert result["balance"]["tiarnan"] == 0.0
    assert result["balance"]["deirbhile"] == 0.0
    assert result["settlement_text"] == "Already settled - nothing owed either way"


def test_one_partner_owes_when_they_paid_less_than_their_ratio(mongo_db):
    # Tiarnan paid everything, 50/50 split -> Deirbhile owes half
    mongo_db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "amount": -200.0, "is_shared": True, "date": "2026-08-01"}
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["balance"]["deirbhile"] == 100.0
    assert result["balance"]["tiarnan"] == -100.0
    assert "Deirbhile owes Tiarnan" in result["settlement_text"]
    assert "100.00" in result["settlement_text"]


def test_uneven_ratio_is_respected(mongo_db):
    # 60/40 split (Tiarnan 60%), Tiarnan paid everything (£100)
    # Tiarnan's fair share = £60, but he paid £100 -> he's owed £40 back
    mongo_db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-08-01"}
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.6, account_owners=OWNERS)

    assert result["fair_share"]["tiarnan"] == 60.0
    assert result["fair_share"]["deirbhile"] == 40.0
    assert result["balance"]["deirbhile"] == 40.0


def test_non_shared_transactions_are_excluded(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"account_id": "natwest-tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-08-01"},
            {"account_id": "natwest-tiarnan", "amount": -500.0, "is_shared": False, "date": "2026-08-01"},
            {"account_id": "natwest-tiarnan", "amount": -50.0, "is_shared": None, "date": "2026-08-01"},
        ]
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)
    assert result["total_shared"] == 100.0


def test_incoming_transactions_do_not_count_as_shared_cost(mongo_db):
    # A refund or income transaction incorrectly flagged shared shouldn't
    # count - only outgoing spend is a cost to split.
    mongo_db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "amount": 50.0, "is_shared": True, "date": "2026-08-01"}
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)
    assert result["total_shared"] == 0.0


def test_date_range_filters_correctly(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"account_id": "natwest-tiarnan", "amount": -100.0, "is_shared": True, "date": "2026-07-15"},
            {"account_id": "natwest-tiarnan", "amount": -50.0, "is_shared": True, "date": "2026-08-15"},
        ]
    )

    result = calculate_settlement(
        mongo_db,
        tiarnan_ratio=0.5,
        start=date(2026, 8, 1),
        end=date(2026, 8, 31),
        account_owners=OWNERS,
    )
    assert result["total_shared"] == 50.0


def test_unmapped_account_is_excluded_and_flagged(mongo_db):
    mongo_db.transactions.insert_one(
        {"account_id": "some-unmapped-account", "amount": -100.0, "is_shared": True, "date": "2026-08-01"}
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["total_shared"] == 0.0
    assert "some-unmapped-account" in result["unmapped_accounts"]
