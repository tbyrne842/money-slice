"""
Query logic for browsing/filtering transactions. Kept separate from the
FastAPI route handlers so it can be tested directly against a db object
(mongomock in tests, the real connection in production) without needing
to spin up HTTP.
"""
from typing import Optional


def query_transactions(
    db,
    *,
    account_id: Optional[str] = None,
    category: Optional[str] = None,
    is_shared: Optional[bool] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    query: dict = {}
    if account_id:
        query["account_id"] = account_id
    if category:
        query["category"] = category
    if is_shared is not None:
        query["is_shared"] = is_shared
    if start or end:
        date_filter = {}
        if start:
            date_filter["$gte"] = start
        if end:
            date_filter["$lte"] = end
        query["date"] = date_filter
    if search:
        query["description_raw"] = {"$regex": search, "$options": "i"}

    total = db.transactions.count_documents(query)
    cursor = db.transactions.find(query).sort("date", -1).skip(skip).limit(limit)

    items = []
    for txn in cursor:
        txn["_id"] = str(txn["_id"])  # ObjectId isn't JSON-serializable as-is
        items.append(txn)

    return {"items": items, "total": total, "skip": skip, "limit": limit}


def list_distinct_categories(db) -> list[str]:
    return sorted(c for c in db.transactions.distinct("category") if c)


def list_distinct_accounts(db) -> list[str]:
    return sorted(db.transactions.distinct("account_id"))
