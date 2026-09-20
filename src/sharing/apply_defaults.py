"""
Apply category-based is_shared defaults to any transaction that's still
undecided (is_shared: None).

Run this after categorization. Idempotent and safe to re-run after every
import - it only touches transactions where is_shared is still None, so
anything you've manually flagged (via mongo-express, or a future review
tool) is never overwritten, regardless of what the category default says.

Usage:
    python -m sharing.apply_defaults
"""

from pathlib import Path

import yaml

from db.mongo import get_db

DEFAULTS_PATH = Path(__file__).parent.parent / "config" / "sharing_defaults.yaml"


def load_sharing_defaults() -> dict[str, bool]:
    with open(DEFAULTS_PATH) as f:
        raw = yaml.safe_load(f)

    mapping = {}
    for category in raw.get("shared", []):
        mapping[category] = True
    for category in raw.get("personal", []):
        mapping[category] = False
    return mapping


def apply_defaults(db, defaults: dict[str, bool] | None = None) -> dict[str, int]:
    if defaults is None:
        defaults = load_sharing_defaults()

    undecided = db.transactions.find({"is_shared": None})

    updated = 0
    skipped_no_category = 0
    skipped_unknown_category = 0

    for txn in undecided:
        category = txn.get("category")
        if not category:
            # Can't set a sensible default without knowing the category -
            # categorize first, then run this.
            skipped_no_category += 1
            continue
        if category not in defaults:
            # Not in sharing_defaults.yaml at all (new category since the
            # file was last updated) - falls back to "personal" per the
            # file's own documented default, but flagged separately here
            # so you know it happened.
            db.transactions.update_one(
                {"_id": txn["_id"]}, {"$set": {"is_shared": False}}
            )
            skipped_unknown_category += 1
            continue

        db.transactions.update_one(
            {"_id": txn["_id"]}, {"$set": {"is_shared": defaults[category]}}
        )
        updated += 1

    return {
        "updated": updated,
        "skipped_no_category": skipped_no_category,
        "defaulted_unknown_category": skipped_unknown_category,
    }


def main():
    db = get_db()
    result = apply_defaults(db)
    print(
        f"Set is_shared on {result['updated']} transaction(s).\n"
        f"Skipped {result['skipped_no_category']} still uncategorized "
        f"(run categorization first).\n"
        f"Defaulted {result['defaulted_unknown_category']} to personal "
        f"(category not listed in sharing_defaults.yaml)."
    )


if __name__ == "__main__":
    main()
