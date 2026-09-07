"""
Tests for the Transaction model - specifically source_hash, since
that's what makes re-imports safe. If this breaks, duplicate imports
stop being prevented.
"""
from datetime import date

from models import Transaction


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
