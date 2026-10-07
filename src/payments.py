"""
Explicit settle-up payments ("A paid B £x") within a household.

Stored in `settle_ups`:
    {household_id, payer, payee, amount, date, note, recorded_by, created_at}

Either party to a payment may record it, so one person can log a transfer
without waiting for the other; only the person who recorded it can delete
it. There is no confirmation step - the household is a small trusted group.
"""
import math
from datetime import date, datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from households import HouseholdError, get_household

MAX_AMOUNT = 1_000_000
MAX_NOTE_LENGTH = 200


def payment_view(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "payer": doc["payer"],
        "payee": doc["payee"],
        "amount": doc["amount"],
        "date": doc["date"],
        "note": doc.get("note") or "",
        "recorded_by": doc["recorded_by"],
    }


def _household(db, user: str) -> dict:
    household = get_household(db, user)
    if household is None:
        raise HouseholdError("You're not in a household.", 404)
    return household


def record_payment(
    db, user: str, payer: str, payee: str, amount: float, day: date | None = None, note: str | None = None
) -> dict:
    household = _household(db, user)
    members = {m["username"] for m in household["members"]}

    if payer == payee:
        raise HouseholdError("A payment needs two different people.")
    if payer not in members or payee not in members:
        raise HouseholdError("Both people must be members of your household.")
    if user not in (payer, payee):
        raise HouseholdError("You can only record payments you made or received.", 403)
    if not math.isfinite(amount) or amount <= 0 or amount > MAX_AMOUNT:
        raise HouseholdError(f"Amount must be more than 0 and at most £{MAX_AMOUNT:,}.")
    amount = round(amount, 2)
    if amount <= 0:
        raise HouseholdError("Amount must be at least 1p.")

    day = day or date.today()
    if day > date.today():
        raise HouseholdError("A payment can't be dated in the future.")

    note = " ".join((note or "").split())
    if len(note) > MAX_NOTE_LENGTH:
        raise HouseholdError(f"Note must be at most {MAX_NOTE_LENGTH} characters.")

    doc = {
        "household_id": household["_id"],
        "payer": payer,
        "payee": payee,
        "amount": amount,
        "date": day.isoformat(),
        "note": note,
        "recorded_by": user,
        "created_at": datetime.now(timezone.utc),
    }
    db.settle_ups.insert_one(doc)
    return payment_view(doc)


def list_payments(db, user: str, limit: int = 50) -> list[dict]:
    household = _household(db, user)
    docs = db.settle_ups.find({"household_id": household["_id"]}).sort([("date", -1), ("created_at", -1)]).limit(limit)
    return [payment_view(d) for d in docs]


def delete_payment(db, user: str, payment_id: str) -> None:
    household = _household(db, user)
    try:
        oid = ObjectId(payment_id)
    except (InvalidId, TypeError):
        raise HouseholdError("Payment not found.", 404)
    doc = db.settle_ups.find_one({"_id": oid, "household_id": household["_id"]})
    if doc is None:
        raise HouseholdError("Payment not found.", 404)
    if doc["recorded_by"] != user:
        raise HouseholdError(f"Only {doc['recorded_by']} can delete this payment.", 403)
    db.settle_ups.delete_one({"_id": oid})
