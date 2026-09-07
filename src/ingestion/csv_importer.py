"""
Config-driven CSV importer.

Usage:
    python -m ingestion.csv_importer \
        --file statements/danske_july.csv \
        --account-id danske-current-tiarnan \
        --mapping generic_uk_debit_credit

Adding a new bank format = adding a block to bank_mappings.yaml.
No code changes needed unless a bank does something genuinely unusual
(e.g. multi-row headers, embedded balances) - that's the point of
keeping mapping declarative.
"""
import argparse
from datetime import datetime
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


def parse_csv(file_path: str, account_id: str, mapping_name: str) -> list[Transaction]:
    mapping = load_mapping(mapping_name)
    df = pd.read_csv(file_path)

    transactions = []
    for _, row in df.iterrows():
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
            date=txn_date,
            amount=amount,
            description_raw=description,
            source_category=source_category,
            source="csv",
        ).finalize()
        transactions.append(txn)

    return transactions


def save_transactions(transactions: list[Transaction]) -> tuple[int, int]:
    """Returns (inserted_count, duplicate_count)."""
    db = get_db()
    ensure_indexes(db)

    inserted, duplicates = 0, 0
    for txn in transactions:
        try:
            db.transactions.insert_one(txn.model_dump(mode="json"))
            inserted += 1
        except DuplicateKeyError:
            duplicates += 1  # already imported - expected on re-runs

    return inserted, duplicates


def main():
    parser = argparse.ArgumentParser(description="Import a bank CSV export into MongoDB")
    parser.add_argument("--file", required=True, help="Path to CSV file")
    parser.add_argument("--account-id", required=True, help="Account id, e.g. danske-current-tiarnan")
    parser.add_argument("--mapping", required=True, help="Mapping name from bank_mappings.yaml")
    args = parser.parse_args()

    transactions = parse_csv(args.file, args.account_id, args.mapping)
    inserted, duplicates = save_transactions(transactions)

    print(f"Parsed {len(transactions)} rows -> {inserted} new, {duplicates} already imported (skipped)")


if __name__ == "__main__":
    main()
