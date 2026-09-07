"""
Shared fixtures for the test suite.

Notably: `mongo_db` swaps the real MongoDB connection for an in-memory
mongomock instance, patched directly into the ingestion module. Tests
that need to check dedup/idempotency behaviour use this instead of
requiring a running MongoDB instance.
"""
from pathlib import Path

import mongomock
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_path():
    """Returns the absolute path to a file under tests/fixtures/."""

    def _path(filename: str) -> str:
        return str(FIXTURES_DIR / filename)

    return _path


@pytest.fixture
def mongo_db(monkeypatch):
    import ingestion.csv_importer as csv_importer

    client = mongomock.MongoClient()
    database = client["finance_tracker_test"]

    # Patch the name as imported into csv_importer, not the original
    # module - `from db.mongo import get_db` already bound the name
    # locally, so patching db.mongo.get_db wouldn't affect it.
    monkeypatch.setattr(csv_importer, "get_db", lambda: database)

    return database
