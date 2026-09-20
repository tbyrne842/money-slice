"""
Test for the one-time is_shared reset migration.
"""
from sharing.reset_sharing_status import reset_sharing_status


def test_resets_false_to_none(mongo_db):
    mongo_db.transactions.insert_many(
        [
            {"description_raw": "A", "is_shared": False},
            {"description_raw": "B", "is_shared": True},
            {"description_raw": "C", "is_shared": None},
        ]
    )

    count = reset_sharing_status(mongo_db)
    assert count == 1

    assert mongo_db.transactions.find_one({"description_raw": "A"})["is_shared"] is None
    assert mongo_db.transactions.find_one({"description_raw": "B"})["is_shared"] is True
    assert mongo_db.transactions.find_one({"description_raw": "C"})["is_shared"] is None
