"""
Summarize uncategorized transactions, grouped by merchant description
and ranked by how often (or how much) they occur.

This is the input for BULK categorization: run this, copy the output,
hand it to whoever/whatever is doing the classifying (a person, or an
LLM) in one go, and turn the results into category_rules.yaml entries -
much faster than answering a prompt per merchant one at a time.

Usage:
    python -m categorization.summarize_uncategorized
    python -m categorization.summarize_uncategorized --sort amount
"""
import argparse

from db.mongo import get_db


def summarize_uncategorized(db, sort_by: str = "count") -> list[dict]:
    sort_field = "count" if sort_by == "count" else "total_amount"
    pipeline = [
        {"$match": {"category": None}},
        {
            "$group": {
                "_id": "$description_raw",
                "count": {"$sum": 1},
                "total_amount": {"$sum": {"$abs": "$amount"}},
                "source_category": {"$first": "$source_category"},
            }
        },
        {"$sort": {sort_field: -1}},
    ]
    return list(db.transactions.aggregate(pipeline))


def print_summary(rows: list[dict]) -> None:
    for row in rows:
        hint = f"  [Amex: {row['source_category']}]" if row.get("source_category") else ""
        print(f"{row['count']:>4}x  £{row['total_amount']:>8.2f}  {row['_id']}{hint}")


def main():
    parser = argparse.ArgumentParser(
        description="Summarize uncategorized transactions by merchant, for bulk categorization"
    )
    parser.add_argument("--sort", choices=["count", "amount"], default="count")
    args = parser.parse_args()

    db = get_db()
    rows = summarize_uncategorized(db, sort_by=args.sort)

    if not rows:
        print("Nothing uncategorized - you're all caught up.")
        return

    print(f"{len(rows)} distinct uncategorized merchants:\n")
    print_summary(rows)


if __name__ == "__main__":
    main()
