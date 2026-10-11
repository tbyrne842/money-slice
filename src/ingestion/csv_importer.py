"""
Config-driven CSV importer.

Usage:
    python -m ingestion.csv_importer \
        --file statements/danske_july.csv \
        --account-id danske-current-tiarnan \
        --owner tiarnan \
        --mapping generic_uk_debit_credit

Adding a new bank format = adding a block to bank_mappings.yaml.
No code changes needed unless a bank does something genuinely unusual
(e.g. multi-row headers, embedded balances) - that's the point of
keeping mapping declarative.
"""
import argparse
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml
from pymongo.errors import DuplicateKeyError

from db.mongo import ensure_indexes, get_db
from models import Transaction

MAPPINGS_PATH = Path(__file__).parent.parent / "config" / "bank_mappings.yaml"


def load_mapping(name: str) -> dict:
    with open(MAPPINGS_PATH) as f:
        mappings = yaml.safe_load(f)
    if name not in mappings:
        raise ValueError(
            f"No mapping '{name}' in bank_mappings.yaml. "
            f"Available: {list(mappings.keys())}"
        )
    return mappings[name]


def row_has_valid_amount(row: pd.Series, mapping: dict) -> bool:
    """
    Guards against rows with no real amount - e.g. a bank's trailing
    "Balance as at ..." summary row, which reuses the same column
    layout but leaves the amount column(s) blank. Skipping these here
    means parse_csv() never produces a NaN amount that would otherwise
    sail straight through save_transactions() (Mongo happily stores a
    NaN double) and only blow up later, when something tries to
    JSON-serialise it back out.
    """
    if mapping["amount_mode"] == "single_signed":
        return pd.notna(row.get(mapping["amount_col"]))

    debit = row.get(mapping["debit_col"])
    credit = row.get(mapping["credit_col"])
    debit_present = pd.notna(debit) and str(debit).strip()
    credit_present = pd.notna(credit) and str(credit).strip()
    return bool(debit_present or credit_present)


def row_to_amount(row: pd.Series, mapping: dict) -> float:
    if mapping["amount_mode"] == "single_signed":
        val = float(row[mapping["amount_col"]])
        return -val if mapping.get("invert_sign", False) else val

    # debit_credit mode: exactly one of debit/credit will be populated
    debit = row.get(mapping["debit_col"])
    credit = row.get(mapping["credit_col"])

    if pd.notna(debit) and str(debit).strip():
        val = float(debit)
        return -val if mapping.get("debit_is_positive", True) else val
    if pd.notna(credit) and str(credit).strip():
        return float(credit)
    return 0.0


@dataclass
class ParseResult:
    transactions: list[Transaction]
    rows_in_file: int
    skipped_no_amount: int

    @property
    def date_from(self) -> date | None:
        return min((t.date for t in self.transactions), default=None)

    @property
    def date_to(self) -> date | None:
        return max((t.date for t in self.transactions), default=None)


def parse_csv_detailed(file_path: str, account_id: str, mapping_name: str, owner: str | None = None) -> ParseResult:
    mapping = load_mapping(mapping_name)
    df = pd.read_csv(file_path)

    transactions = []
    skipped_no_amount = 0
    for _, row in df.iterrows():
        if not row_has_valid_amount(row, mapping):
            skipped_no_amount += 1
            continue

        txn_date = datetime.strptime(
            str(row[mapping["date_col"]]).strip(), mapping["date_format"]
        ).date()
        amount = row_to_amount(row, mapping)
        description = str(row[mapping["description_col"]])

        source_category = None
        cat_col = mapping.get("category_col")
        if cat_col and pd.notna(row.get(cat_col)):
            source_category = str(row[cat_col]).strip() or None

        txn = Transaction(
            account_id=account_id,
            owner=owner,
            date=txn_date,
            amount=amount,
            description_raw=description,
            source_category=source_category,
            source="csv",
        ).finalize()
        transactions.append(txn)

    return ParseResult(transactions, rows_in_file=len(df), skipped_no_amount=skipped_no_amount)


def parse_csv(file_path: str, account_id: str, mapping_name: str, owner: str | None = None) -> list[Transaction]:
    result = parse_csv_detailed(file_path, account_id, mapping_name, owner=owner)
    if result.skipped_no_amount:
        print(f"Skipped {result.skipped_no_amount} row(s) with no amount (e.g. a trailing balance summary row).")
    return result.transactions


def list_mapping_names() -> list[str]:
    with open(MAPPINGS_PATH) as f:
        mappings = yaml.safe_load(f)
    return sorted(mappings.keys())


@dataclass
class SaveResult:
    inserted: int = 0
    already_imported: int = 0  # hash already in the database from an earlier import
    repeated_in_file: int = 0  # same hash earlier in this same file (see note below)
    repeated_rows: list[dict] = field(default_factory=list)  # which rows, with extra_copies skipped
    new_transactions: list[Transaction] = field(default_factory=list)

    @property
    def duplicates(self) -> int:
        return self.already_imported + self.repeated_in_file


def save_transactions_detailed(transactions: list[Transaction], db=None) -> SaveResult:
    """Insert transactions, reporting why each non-inserted row was skipped.

    repeated_in_file matters because the dedup hash has no occurrence
    number: two genuine identical purchases on one day (same account,
    date, amount and description) share a hash, so the second is dropped.
    Counting these separately lets the UI flag them instead of hiding them
    among re-imported rows.
    """
    if db is None:
        db = get_db()
    ensure_indexes(db)

    result = SaveResult()
    seen_in_file: set[str] = set()
    repeats: dict[str, dict] = {}
    for txn in transactions:
        if txn.source_hash in seen_in_file:
            result.repeated_in_file += 1
            row = repeats.setdefault(
                txn.source_hash,
                {
                    "date": txn.date.isoformat(),
                    "description": txn.description_raw,
                    "amount": txn.amount,
                    "extra_copies": 0,
                },
            )
            row["extra_copies"] += 1
            continue
        seen_in_file.add(txn.source_hash)
        try:
            db.transactions.insert_one(txn.model_dump(mode="json"))
            result.inserted += 1
            result.new_transactions.append(txn)
        except DuplicateKeyError:
            result.already_imported += 1  # already imported - expected on re-runs

    result.repeated_rows = sorted(repeats.values(), key=lambda r: (r["date"], r["description"]))
    return result


def save_transactions(transactions: list[Transaction], db=None) -> tuple[int, int]:
    """Returns (inserted_count, duplicate_count).

    db is optional so callers that already have a handle (e.g. an API
    endpoint running the full pipeline) can pass it through and only
    need to patch one get_db in tests. Falls back to get_db() for the
    CLI / existing call sites that don't pass one.
    """
    result = save_transactions_detailed(transactions, db=db)
    return result.inserted, result.duplicates


def main():
    parser = argparse.ArgumentParser(description="Import a bank CSV export into MongoDB")
    parser.add_argument("--file", required=True, help="Path to CSV file")
    parser.add_argument("--account-id", required=True, help="Account id, e.g. danske-current-tiarnan")
    parser.add_argument("--owner", required=True, help="Username that owns this statement")
    parser.add_argument("--mapping", required=True, help="Mapping name from bank_mappings.yaml")
    args = parser.parse_args()

    transactions = parse_csv(args.file, args.account_id, args.mapping, owner=args.owner)
    inserted, duplicates = save_transactions(transactions, db=None)

    print(f"Parsed {len(transactions)} rows -> {inserted} new, {duplicates} already imported (skipped)")


if __name__ == "__main__":
    main()
