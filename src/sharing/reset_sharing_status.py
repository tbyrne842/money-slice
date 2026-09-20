"""
ONE-TIME migration: resets is_shared to None (undecided) for every
transaction currently at the old default (False).

Why this is needed: is_shared used to default to False ("not shared").
This release changes it to a three-state field (None = undecided, True/
False = decided) so the bulk sharing-defaults script knows what it
hasn't looked at yet. Transactions you already imported before this
change are stuck at the old False default, which looks identical to a
transaction someone deliberately marked "not shared" - so apply_defaults
can't safely tell them apart on its own.

Since nothing has been manually reviewed for sharing yet (this is a new
feature), it's safe to reset everything to undecided and let
apply_defaults.py re-populate it properly from categories.

Run this ONCE, before the first run of apply_defaults.py. Do not run it
again after you've started manually flagging transactions - it would
wipe those decisions back to undecided too.

Usage:
    python -m sharing.reset_sharing_status
"""

from db.mongo import get_db


def reset_sharing_status(db) -> int:
    result = db.transactions.update_many(
        {"is_shared": False}, {"$set": {"is_shared": None}}
    )
    return result.modified_count


def main():
    db = get_db()
    count = input(
        "This resets is_shared to 'undecided' for every transaction currently "
        "set to False. Only run this once, before first use of apply_defaults.py. "
        "Type 'yes' to continue: "
    )
    if count.strip().lower() != "yes":
        print("Cancelled.")
        return

    n = reset_sharing_status(db)
    print(f"Reset {n} transaction(s) to undecided.")


if __name__ == "__main__":
    main()
