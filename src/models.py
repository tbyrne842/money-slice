"""
Normalized schema for the finance tracker.

Every ingestion source (CSV today, GoCardless later) must produce
objects matching these models. This is the contract that keeps
ingestion adapters decoupled from everything downstream
(categorisation, household splitting, reporting).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AccountOwner(str, Enum):
    TIARNAN = "tiarnan"
    DEIRBHILE = "deirbhile"
    JOINT = "joint"


class Account(BaseModel):
    id: str  # e.g. "danske-current-tiarnan" - human-assigned, stable
    owner: AccountOwner
    bank_name: str
    account_type: str  # "current", "savings", "credit_card"
    currency: str = "GBP"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Transaction(BaseModel):
    id: Optional[str] = None  # set to source_hash on save
    account_id: str
    date: date
    amount: float  # negative = money out, positive = money in
    currency: str = "GBP"
    description_raw: str
    merchant: Optional[str] = None  # cleaned/extracted, filled by categoriser
    category: Optional[str] = None
    source_category: Optional[str] = (
        None  # provider's own category, if the CSV includes one (e.g. Amex) - kept for reference, not auto-applied to `category`
    )
    is_shared: bool = False
    split_ratio: Optional[float] = None  # None = use household default
    source: str = "csv"  # "csv" | "gocardless" | "manual"
    source_hash: Optional[str] = None
    imported_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("description_raw")
    @classmethod
    def strip_description(cls, v: str) -> str:
        return " ".join(v.split())  # collapse whitespace, banks are messy

    def compute_source_hash(self) -> str:
        """
        Idempotency key. Same account + date + amount + description
        should never be imported twice, even if you re-run a CSV import
        with overlapping date ranges (which you will, constantly).
        """
        key = f"{self.account_id}|{self.date.isoformat()}|{self.amount}|{self.description_raw}"
        return hashlib.sha256(key.encode()).hexdigest()

    def finalize(self) -> "Transaction":
        self.source_hash = self.compute_source_hash()
        self.id = self.source_hash
        return self
