"""
Tests for calculate_settlement - who owes whom, given a ratio and the
shared transactions recorded so far.
"""
from datetime import date

from sharing.settlement import calculate_settlement, load_default_tiarnan_ratio

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


# --- settle-up payments (partner_contribution) ----------------------------

def test_settle_up_payment_from_tiarnan_reduces_what_he_owes(mongo_db):
    mongo_db.transactions.insert_many(
        [
            # Tiarnan paid nothing, Deirbhile paid it all - he'd owe £100 at 50/50
            {"account_id": "aib-deirbhile", "amount": -200.0, "is_shared": True, "date": "2026-08-01"},
            # He then sends her £60 to partially settle up
            {
                "account_id": "natwest-tiarnan",
                "amount": -60.0,
                "is_shared": False,
                "category": "partner_contribution",
                "date": "2026-08-05",
            },
        ]
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["settled_by_owner"]["tiarnan"] == 60.0
    assert result["balance"]["tiarnan"] == 40.0  # owed £100, paid £60, £40 left
    assert result["balance"]["deirbhile"] == -40.0


def test_settle_up_payment_from_deirbhile_increases_what_tiarnan_is_owed(mongo_db):
    # Tiarnan paid it all - Deirbhile owes £100 at 50/50
    mongo_db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "amount": -200.0, "is_shared": True, "date": "2026-08-01"}
    )
    # She sends him £100 to fully settle up
    mongo_db.transactions.insert_one(
        {
            "account_id": "aib-deirbhile",
            "amount": -100.0,
            "is_shared": False,
            "category": "partner_contribution",
            "date": "2026-08-05",
        }
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["settled_by_owner"]["deirbhile"] == 100.0
    assert result["balance"]["tiarnan"] == 0.0
    assert result["settlement_text"] == "Already settled - nothing owed either way"


def test_settle_up_overpayment_flips_who_is_owed(mongo_db):
    # Tiarnan owes £100, but sends £150 - now Deirbhile owes him the difference
    mongo_db.transactions.insert_one(
        {"account_id": "aib-deirbhile", "amount": -200.0, "is_shared": True, "date": "2026-08-01"}
    )
    mongo_db.transactions.insert_one(
        {
            "account_id": "natwest-tiarnan",
            "amount": -150.0,
            "is_shared": False,
            "category": "partner_contribution",
            "date": "2026-08-05",
        }
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)

    assert result["balance"]["tiarnan"] == -50.0
    assert result["balance"]["deirbhile"] == 50.0
    assert "Deirbhile owes Tiarnan" in result["settlement_text"]
    assert "50.00" in result["settlement_text"]


def test_incoming_mirrored_settle_up_leg_is_not_double_counted(mongo_db):
    # The same real-world transfer, if both partners' statements get
    # imported, can show up twice: a debit on the sender's account and
    # a credit on the receiver's. Only the debit should count.
    mongo_db.transactions.insert_many(
        [
            {"account_id": "aib-deirbhile", "amount": -200.0, "is_shared": True, "date": "2026-08-01"},
            {
                "account_id": "natwest-tiarnan",
                "amount": -60.0,
                "is_shared": False,
                "category": "partner_contribution",
                "date": "2026-08-05",
            },
            {
                "account_id": "aib-deirbhile",
                "amount": 60.0,  # mirrored credit leg of the same transfer
                "is_shared": False,
                "category": "partner_contribution",
                "date": "2026-08-05",
            },
        ]
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)
    assert result["settled_by_owner"]["tiarnan"] == 60.0  # not 120.0
    assert result["balance"]["tiarnan"] == 40.0


def test_mis_flagged_shared_partner_contribution_is_not_double_counted(mongo_db):
    # A settle-up payment should always be is_shared: False per
    # sharing_defaults.yaml, but if one ever gets mis-flagged (manual
    # edit, mongo-express, etc.), it must not also count as new shared
    # spend on top of being recognised as a settle-up.
    mongo_db.transactions.insert_one(
        {
            "account_id": "natwest-tiarnan",
            "amount": -60.0,
            "is_shared": True,
            "category": "partner_contribution",
            "date": "2026-08-05",
        }
    )

    result = calculate_settlement(mongo_db, tiarnan_ratio=0.5, account_owners=OWNERS)
    assert result["total_shared"] == 0.0  # excluded from shared spend...
    assert result["settled_by_owner"]["tiarnan"] == 60.0  # ...only counted as a settle-up


def test_default_ratio_comes_from_config_when_not_specified(mongo_db):
    mongo_db.transactions.insert_one(
        {"account_id": "natwest-tiarnan", "amount": -200.0, "is_shared": True, "date": "2026-08-01"}
    )

    result = calculate_settlement(mongo_db, account_owners=OWNERS)  # no tiarnan_ratio passed
    assert result["tiarnan_ratio"] == load_default_tiarnan_ratio()
