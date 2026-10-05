"""
Households for Money Slice.

A household is a small group of users who can view each other's
transactions (editing stays owner-only, enforced in the API) and whose
shared spend is split by per-member shares that sum to 1.

Document shape (collection `households`):
    {name, invite_code, members: [{username, share}], created_at}

A user belongs to at most one household. Joining or leaving resets
everyone's shares to an equal split, since the old shares no longer sum
to 1; members can then set agreed shares explicitly.

Joining needs the invite code, so repeated wrong guesses trigger a short
lockout per user (in-memory, like the login lockout).
"""
import math
import secrets
import time
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

# No 0/O/1/I/L, so codes survive being read out or typed from a message.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
MAX_NAME_LENGTH = 50
SHARE_TOLERANCE = 1e-6
MAX_JOIN_FAILURES = 5
JOIN_LOCKOUT_SECONDS = 300

_join_failures: dict[str, tuple[int, float]] = {}  # username -> (count, last failure time)


class HouseholdError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def reset_join_lockouts() -> None:
    _join_failures.clear()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _equal_shares(usernames: list[str]) -> list[dict]:
    return [{"username": u, "share": 1 / len(usernames)} for u in usernames]


def get_household(db, username: str) -> dict | None:
    return db.households.find_one({"members.username": username})


def household_view(household: dict) -> dict:
    return {
        "id": str(household["_id"]),
        "name": household["name"],
        "invite_code": household["invite_code"],
        "members": [{"username": m["username"], "share": m["share"]} for m in household["members"]],
    }


def member_shares(household: dict) -> dict[str, float]:
    return {m["username"]: m["share"] for m in household["members"]}


def visible_owners(db, username: str) -> list[str]:
    """Whose transactions this user may view: their household's members, or just themselves."""
    household = get_household(db, username)
    if household is None:
        return [username]
    return [m["username"] for m in household["members"]]


def create_household(db, username: str, name: str) -> dict:
    name = " ".join(name.split())
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise HouseholdError(f"Household name must be 1-{MAX_NAME_LENGTH} characters.")
    if get_household(db, username):
        raise HouseholdError("You're already in a household. Leave it first.", 409)
    for _ in range(5):
        code = _new_code()
        try:
            db.households.insert_one(
                {
                    "name": name,
                    "invite_code": code,
                    "members": [{"username": username, "share": 1.0}],
                    "created_at": datetime.now(timezone.utc),
                }
            )
            break
        except DuplicateKeyError:  # astronomically unlikely clash with the unique index
            continue
    else:
        raise HouseholdError("Couldn't generate an invite code. Try again.", 500)
    return get_household(db, username)


def join_household(db, username: str, code: str) -> dict:
    if get_household(db, username):
        raise HouseholdError("You're already in a household. Leave it first.", 409)

    count, last = _join_failures.get(username, (0, 0.0))
    if count >= MAX_JOIN_FAILURES and time.time() - last < JOIN_LOCKOUT_SECONDS:
        raise HouseholdError("Too many invalid invite codes. Try again in a few minutes.", 429)

    household = db.households.find_one({"invite_code": normalise_code(code)})
    if household is None:
        if count >= MAX_JOIN_FAILURES:  # an old lockout has expired - start counting afresh
            count = 0
        _join_failures[username] = (count + 1, time.time())
        raise HouseholdError("Invalid invite code.", 404)

    _join_failures.pop(username, None)
    usernames = [m["username"] for m in household["members"]] + [username]
    db.households.update_one({"_id": household["_id"]}, {"$set": {"members": _equal_shares(usernames)}})
    return get_household(db, username)


def leave_household(db, username: str) -> None:
    household = get_household(db, username)
    if household is None:
        raise HouseholdError("You're not in a household.", 404)
    remaining = [m["username"] for m in household["members"] if m["username"] != username]
    if not remaining:
        db.households.delete_one({"_id": household["_id"]})
        return
    db.households.update_one({"_id": household["_id"]}, {"$set": {"members": _equal_shares(remaining)}})


def set_shares(db, username: str, shares: dict[str, float]) -> dict:
    household = get_household(db, username)
    if household is None:
        raise HouseholdError("You're not in a household.", 404)
    members = [m["username"] for m in household["members"]]
    if set(shares) != set(members):
        raise HouseholdError("Provide a share for every household member, and nobody else.")
    if not all(math.isfinite(s) and 0 <= s <= 1 for s in shares.values()):
        raise HouseholdError("Each share must be between 0 and 1.")
    if abs(sum(shares.values()) - 1) > SHARE_TOLERANCE:
        raise HouseholdError("Shares must add up to 1 (100%).")
    db.households.update_one(
        {"_id": household["_id"]},
        {"$set": {"members": [{"username": u, "share": shares[u]} for u in members]}},
    )
    return get_household(db, username)


def rotate_invite_code(db, username: str) -> dict:
    """Replaces the invite code (the old one stops working) - for when a code has leaked."""
    household = get_household(db, username)
    if household is None:
        raise HouseholdError("You're not in a household.", 404)
    for _ in range(5):
        code = _new_code()
        if not db.households.find_one({"invite_code": code}):
            db.households.update_one({"_id": household["_id"]}, {"$set": {"invite_code": code}})
            return get_household(db, username)
    raise HouseholdError("Couldn't generate an invite code. Try again.", 500)
