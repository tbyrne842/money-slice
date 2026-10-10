"""
Tests for the config-driven CSV importer.

Covers every mapping currently in bank_mappings.yaml. If a new mapping
is added, add a matching fixture CSV under tests/fixtures/ and a test
here - that's what catches sign-convention or date-format mistakes
before a real import does.
"""
from datetime import date

from ingestion.csv_importer import (
    parse_csv,
    parse_csv_detailed,
    save_transactions,
    save_transactions_detailed,
)
from models import Transaction


def test_generic_uk_debit_credit_signs_debit_negative_and_credit_positive(fixture_path):
    txns = parse_csv(
        fixture_path("generic_uk_debit_credit.csv"), "test-generic", "generic_uk_debit_credit"
    )
    assert len(txns) == 2

    debit_txn = next(t for t in txns if "TESCO" in t.description_raw)
    assert debit_txn.amount == -45.20

    credit_txn = next(t for t in txns if "SALARY" in t.description_raw)
    assert credit_txn.amount == 2100.00


def test_natwest_parses_real_column_layout_and_date_format(fixture_path):
    txns = parse_csv(fixture_path("natwest.csv"), "test-natwest", "natwest")
    assert len(txns) == 2

    spend = next(t for t in txns if t.amount < 0)
    assert spend.amount == -24.50
    assert spend.date.isoformat() == "2026-08-17"  # "17 Aug 2026" parsed correctly

    credit = next(t for t in txns if t.amount > 0)
    assert credit.amount == 2300.00


def test_natwest_skips_trailing_balance_summary_row(fixture_path):
    # NatWest exports sometimes end with a "Balance as at ..." row that
    # reuses the same columns but leaves Value blank - not a real
    # transaction, and previously produced a NaN amount that broke
    # JSON serialisation downstream rather than raising here.
    txns = parse_csv(fixture_path("natwest_with_balance_row.csv"), "test-natwest", "natwest")
    assert len(txns) == 2
    assert all(t.description_raw != "Balance as at 25 Aug 2026" for t in txns)


def test_monzo_single_signed_amount_used_as_is(fixture_path):
    txns = parse_csv(fixture_path("monzo.csv"), "test-monzo", "monzo")
    assert len(txns) == 2

    spend = next(t for t in txns if "COSTA" in t.description_raw)
    assert spend.amount == -12.50

    refund = next(t for t in txns if "REFUND" in t.description_raw)
    assert refund.amount == 18.00


def test_starling_single_signed_amount_used_as_is(fixture_path):
    txns = parse_csv(fixture_path("starling.csv"), "test-starling", "starling")
    assert len(txns) == 2

    spend = next(t for t in txns if "GREGGS" in t.description_raw)
    assert spend.amount == -8.99


def test_amex_inverts_sign_for_spend_and_payment(fixture_path):
    txns = parse_csv(fixture_path("amex.csv"), "test-amex", "amex")
    assert len(txns) == 3

    # Amex reports spend as positive - we invert to our negative=out convention
    groceries = next(t for t in txns if "SAINSBURYS" in t.description_raw)
    assert groceries.amount == -31.08

    pharmacy = next(t for t in txns if "FORESTSI" in t.description_raw)
    assert pharmacy.amount == -16.24

    # Amex reports a payment received as negative - inverts to positive (money in)
    payment = next(t for t in txns if "PAYMENT RECEIVED" in t.description_raw)
    assert payment.amount == 4328.89


def test_amex_captures_source_category_where_present(fixture_path):
    txns = parse_csv(fixture_path("amex.csv"), "test-amex", "amex")

    groceries = next(t for t in txns if "SAINSBURYS" in t.description_raw)
    assert groceries.source_category == "General Purchases-Groceries"

    pharmacy = next(t for t in txns if "FORESTSI" in t.description_raw)
    assert pharmacy.source_category == "General Purchases-Pharmacies"


def test_amex_blank_category_column_becomes_none(fixture_path):
    txns = parse_csv(fixture_path("amex.csv"), "test-amex", "amex")

    payment = next(t for t in txns if "PAYMENT RECEIVED" in t.description_raw)
    assert payment.source_category is None


def test_amex_multiline_quoted_address_does_not_break_row_count(fixture_path):
    # The first fixture row has an embedded newline inside a quoted Address
    # field, mirroring a real Amex export - this checks pandas parses that
    # as one row, not two.
    txns = parse_csv(fixture_path("amex.csv"), "test-amex", "amex")
    assert len(txns) == 3


def test_other_bank_mappings_do_not_populate_source_category(fixture_path):
    # Only mappings with a category_col set should populate source_category
    txns = parse_csv(fixture_path("natwest.csv"), "test-natwest", "natwest")
    assert all(t.source_category is None for t in txns)


def test_reimporting_the_same_file_produces_no_duplicates(fixture_path, mongo_db):
    first_pass = parse_csv(fixture_path("natwest.csv"), "test-natwest", "natwest")
    inserted, duplicates = save_transactions(first_pass)
    assert inserted == 2
    assert duplicates == 0

    # Simulates re-importing an overlapping statement period - every
    # row should now be recognised as already-imported via source_hash
    second_pass = parse_csv(fixture_path("natwest.csv"), "test-natwest", "natwest")
    inserted_again, duplicates_again = save_transactions(second_pass)
    assert inserted_again == 0
    assert duplicates_again == 2

    assert mongo_db.transactions.count_documents({}) == 2


def test_unknown_mapping_name_raises_a_clear_error(fixture_path):
    import pytest

    with pytest.raises(ValueError, match="No mapping 'not_a_real_bank'"):
        parse_csv(fixture_path("natwest.csv"), "test-natwest", "not_a_real_bank")


# --- detailed results (Phase 10) -----------------------------------------

def test_parse_csv_detailed_counts_rows_skipped_and_date_range(fixture_path):
    result = parse_csv_detailed(fixture_path("natwest_with_balance_row.csv"), "test-natwest", "natwest")

    assert len(result.transactions) == 2
    assert result.skipped_no_amount == 1
    assert result.rows_in_file == 3
    assert result.date_from == min(t.date for t in result.transactions)
    assert result.date_to == max(t.date for t in result.transactions)


def test_parse_csv_detailed_date_range_is_none_for_no_rows(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("Date,Description,Debit Amount,Credit Amount\n")
    result = parse_csv_detailed(str(empty), "acct", "generic_uk_debit_credit")

    assert result.transactions == []
    assert result.date_from is None
    assert result.date_to is None


def test_save_detailed_separates_already_imported_from_repeated_in_file(mongo_db):
    def coffee():
        return Transaction(
            account_id="acct", owner="tiarnan", date=date(2026, 9, 1), amount=-2.5, description_raw="COFFEE SHOP"
        ).finalize()

    first = save_transactions_detailed([coffee(), coffee()])
    assert (first.inserted, first.already_imported, first.repeated_in_file) == (1, 0, 1)
    assert first.duplicates == 1
    assert len(first.new_transactions) == 1

    again = save_transactions_detailed([coffee()])
    assert (again.inserted, again.already_imported, again.repeated_in_file) == (0, 1, 0)
    assert mongo_db.transactions.count_documents({}) == 1


def test_save_transactions_tuple_total_matches_detailed_duplicates(mongo_db):
    txn = Transaction(
        account_id="acct", owner="tiarnan", date=date(2026, 9, 1), amount=-1.0, description_raw="X"
    ).finalize()
    twin = txn.model_copy()

    assert save_transactions([txn, twin]) == (1, 1)
