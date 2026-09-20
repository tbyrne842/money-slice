"""
Apply merchant-substring rules to any transaction missing a category.

Usage:
    python -m categorisation.rules

Run this after every import. It's idempotent - only touches
transactions where category is currently null, so manually-corrected
categories are never overwritten.
"""

from pathlib import Path

import yaml

from db.mongo import get_db

RULES_PATH = Path(__file__).parent.parent / "config" / "category_rules.yaml"


def load_rules() -> list[dict]:
    with open(RULES_PATH) as f:
        return yaml.safe_load(f)


def categorise(description: str, rules: list[dict]) -> str | None:
    desc_lower = description.lower()
    for rule in rules:
        if any(m.lower() in desc_lower for m in rule["matches"]):
            return rule["category"]
    return None


def run() -> tuple[int, int]:
    db = get_db()
    rules = load_rules()

    uncategorised = db.transactions.find({"category": None})
    matched, unmatched = 0, 0

    for txn in uncategorised:
        category = categorise(txn["description_raw"], rules)
        if category:
            db.transactions.update_one(
                {"_id": txn["_id"]}, {"$set": {"category": category}}
            )
            matched += 1
        else:
            unmatched += 1

    return matched, unmatched


if __name__ == "__main__":
    matched, unmatched = run()
    print(f"categorised {matched} transactions, {unmatched} left as 'uncategorised'")
