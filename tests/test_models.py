"""
Tests for the Transaction model - specifically source_hash, since
that's what makes re-imports safe. If this breaks, duplicate imports
stop being prevented.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from models import Account, AccountOwner, Transaction


def make_txn(**overrides) -> Transaction:
    defaults = dict(
        account_id="acc-1",
        date=date(2026, 8, 17),
        amount=-10.0,
        description_raw="TEST MERCHANT",
    )
    defaults.update(overrides)
    return Transaction(**defaults).finalize()


def test_identical_transactions_produce_the_same_hash():
    t1 = make_txn()
    t2 = make_txn()
    assert t1.source_hash == t2.source_hash
    assert t1.id == t1.source_hash


def test_different_amount_produces_a_different_hash():
    t1 = make_txn(amount=-10.00)
    t2 = make_txn(amount=-10.01)
    assert t1.source_hash != t2.source_hash


def test_different_date_produces_a_different_hash():
    t1 = make_txn(date=date(2026, 8, 17))
    t2 = make_txn(date=date(2026, 8, 18))
    assert t1.source_hash != t2.source_hash


def test_different_description_produces_a_different_hash():
    t1 = make_txn(description_raw="TESCO STORES")
    t2 = make_txn(description_raw="TESCO EXPRESS")
    assert t1.source_hash != t2.source_hash


def test_different_account_produces_a_different_hash():
    # Same statement line imported for two different accounts (e.g. a
    # joint transaction visible on both feeds) must not collide.
    t1 = make_txn(account_id="acc-1")
    t2 = make_txn(account_id="acc-2")
    assert t1.source_hash != t2.source_hash


def test_whitespace_in_description_is_collapsed():
    txn = make_txn(description_raw="  TESCO   STORES   BELFAST  ")
    assert txn.description_raw == "TESCO STORES BELFAST"


def test_source_category_defaults_to_none():
    txn = make_txn()
    assert txn.source_category is None


def test_nan_amount_is_rejected():
    with pytest.raises(ValidationError):
        make_txn(amount=float("nan"))


def test_infinite_amount_is_rejected():
    with pytest.raises(ValidationError):
        make_txn(amount=float("inf"))


def make_account(**overrides) -> Account:
    defaults = dict(
        id="natwest-cc-tiarnan",
        owner=AccountOwner.TIARNAN,
        bank_name="NatWest",
        account_type="credit_card",
    )
    defaults.update(overrides)
    return Account(**defaults)


def test_account_accepts_valid_required_fields():
    account = make_account()
    assert account.id == "natwest-cc-tiarnan"
    assert account.owner == AccountOwner.TIARNAN
    assert account.bank_name == "NatWest"
    assert account.account_type == "credit_card"


def test_account_currency_defaults_to_gbp():
    account = make_account()
    assert account.currency == "GBP"


def test_account_currency_can_be_overridden():
    account = make_account(currency="EUR")
    assert account.currency == "EUR"


def test_account_created_at_is_set_automatically():
    account = make_account()
    assert account.created_at is not None


@pytest.mark.parametrize("owner", ["tiarnan", "deirbhile", "joint"])
def test_account_accepts_all_valid_owner_values(owner):
    account = make_account(owner=owner)
    assert account.owner == owner


def test_account_rejects_invalid_owner():
    # Only tiarnan / deirbhile / joint are valid - anything else (e.g. a
    # typo, or a third person) should fail validation rather than being
    # silently accepted as an arbitrary string.
    with pytest.raises(ValidationError):
        make_account(owner="not_a_real_person")


@pytest.mark.parametrize("missing_field", ["id", "owner", "bank_name", "account_type"])
def test_account_requires_all_core_fields(missing_field):
    fields = dict(
        id="natwest-cc-tiarnan",
        owner=AccountOwner.TIARNAN,
        bank_name="NatWest",
        account_type="credit_card",
    )
    del fields[missing_field]

    with pytest.raises(ValidationError):
        Account(**fields)
