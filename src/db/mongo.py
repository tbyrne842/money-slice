"""
MongoDB connection + index bootstrap.

Defaults to a local instance. Override with MONGO_URI env var
(e.g. when this moves into a docker-compose network and "localhost"
stops being correct).
"""
import os

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

DEFAULT_URI = "mongodb://localhost:27017"
DB_NAME = os.environ.get("FINANCE_DB_NAME", "finance_tracker")


def get_db() -> Database:
    uri = os.environ.get("MONGO_URI", DEFAULT_URI)
    client = MongoClient(uri)
    return client[DB_NAME]


def ensure_indexes(db: Database) -> None:
    # source_hash is the dedup key - unique index makes re-imports safe
    # (upsert on conflict, rather than needing app-level dedup logic)
    db.transactions.create_index([("source_hash", ASCENDING)], unique=True)
    db.transactions.create_index([("account_id", ASCENDING), ("date", ASCENDING)])
    db.transactions.create_index([("category", ASCENDING)])
    db.transactions.create_index([("is_shared", ASCENDING)])
    db.accounts.create_index([("id", ASCENDING)], unique=True)


if __name__ == "__main__":
    database = get_db()
    ensure_indexes(database)
    print(f"Connected to '{DB_NAME}', indexes ensured.")
