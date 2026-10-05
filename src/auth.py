"""
User accounts and login for Money Slice.

Passwords are hashed with argon2 (never stored or logged in plain text).
Login state lives in a signed session cookie (Starlette SessionMiddleware),
and the username doubles as the transaction `owner` id, so usernames are
immutable once created.

Repeated failed logins for a username trigger a short lockout. The
counters are in-memory, which is fine for a single local process; they
reset on restart.
"""
import re
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from pymongo.errors import DuplicateKeyError

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

_hasher = PasswordHasher()
# Verified against when the username doesn't exist, so response timing
# doesn't reveal which usernames are registered.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

_failures: dict[str, tuple[int, float]] = {}  # username -> (count, last failure time)


class AccountLocked(Exception):
    pass


def normalise_username(username: str) -> str:
    return username.strip().lower()


def create_user(db, username: str, password: str) -> str:
    username = normalise_username(username)
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-32 characters: letters, numbers, '-' or '_'.")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters."
        )
    if db.users.find_one({"username": username}):
        raise ValueError("That username is already taken.")
    try:
        db.users.insert_one({"username": username, "password_hash": _hasher.hash(password)})
    except DuplicateKeyError as exc:  # race against the unique index
        raise ValueError("That username is already taken.") from exc
    return username


def _is_locked(username: str) -> bool:
    count, last = _failures.get(username, (0, 0.0))
    return count >= MAX_FAILURES and time.time() - last < LOCKOUT_SECONDS


def authenticate(db, username: str, password: str) -> str | None:
    """Returns the username on success, None on bad credentials; raises AccountLocked."""
    username = normalise_username(username)
    if _is_locked(username):
        raise AccountLocked
    user = db.users.find_one({"username": username})
    stored_hash = user["password_hash"] if user else _DUMMY_HASH
    try:
        _hasher.verify(stored_hash, password)
        ok = user is not None
    except (VerificationError, InvalidHashError):
        ok = False

    if ok:
        _failures.pop(username, None)
        return username

    count, last = _failures.get(username, (0, 0.0))
    if count >= MAX_FAILURES:  # an old lockout has expired - start counting afresh
        count = 0
    _failures[username] = (count + 1, time.time())
    return None


def reset_lockouts() -> None:
    _failures.clear()


def current_user(request: Request) -> str:
    """FastAPI dependency: the logged-in username, or 401."""
    username = request.session.get("user")
    if not username:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return username
