"""
Per-user log of CSV imports.

One document per successful upload. It backs three upload-panel features:
remembering the mapping a user picked last time, listing each bank
mapping's most recent import, and warning when a bank's data has stopped
at an old date. A mapping is the closest thing to a "bank" for now; if
account labels per upload are added later they can refine this.

Dates are stored as ISO strings because BSON has no date-only type.
"""
from datetime import date, datetime, timezone
from typing import Optional

STALE_AFTER_DAYS = 35  # a monthly statement plus a few days' grace


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_import(db, user: str, mapping: str, source: str, parsed, saved) -> None:
    db.import_log.insert_one(
        {
            "user": user,
            "mapping": mapping,
            "source": source,
            "at": _utcnow(),
            "rows_in_file": parsed.rows_in_file,
            "skipped_no_amount": parsed.skipped_no_amount,
            "inserted": saved.inserted,
            "already_imported": saved.already_imported,
            "repeated_in_file": saved.repeated_in_file,
            "identical_extra_rows": parsed.identical_extra_rows,
            "date_from": parsed.date_from.isoformat() if parsed.date_from else None,
            "date_to": parsed.date_to.isoformat() if parsed.date_to else None,
        }
    )


def import_status(db, user: str, today: Optional[date] = None, stale_after_days: int = STALE_AFTER_DAYS) -> dict:
    """Last mapping used, plus per-mapping recency (newest import first)."""
    today = today or _utcnow().date()
    entries = list(db.import_log.find({"user": user}).sort("at", -1))

    banks: dict[str, dict] = {}
    for entry in entries:  # newest first, so the first sighting is the latest import
        bank = banks.setdefault(
            entry["mapping"],
            {"mapping": entry["mapping"], "last_imported_at": entry["at"].isoformat(), "latest_data_date": None},
        )
        date_to = entry.get("date_to")
        if date_to and (bank["latest_data_date"] is None or date_to > bank["latest_data_date"]):
            bank["latest_data_date"] = date_to

    for bank in banks.values():
        # Judge staleness by the newest transaction date seen, not the upload
        # date: uploading an old statement yesterday doesn't make the data current.
        basis = bank["latest_data_date"] or bank["last_imported_at"][:10]
        bank["days_since_data"] = (today - date.fromisoformat(basis)).days
        bank["stale"] = bank["days_since_data"] > stale_after_days

    return {
        "last_mapping": entries[0]["mapping"] if entries else None,
        "stale_after_days": stale_after_days,
        "banks": sorted(banks.values(), key=lambda b: b["last_imported_at"], reverse=True),
    }
