"""
FastAPI app for Money Slice.

Exposes a read-only browser over the transaction data (filter/search/
paginate, backed by api.queries), the CSV import pipeline (upload a
bank export and run import -> categorise -> apply sharing defaults in
one call, so the frontend never has to orchestrate three separate
requests), and the static frontend that consumes both.

Run with:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Then open http://localhost:8000
"""
import tempfile
from datetime import date as date_type
from pathlib import Path
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

import categorisation.rules as categorisation_rules
import sharing.apply_defaults as apply_defaults_module
from api.queries import list_distinct_accounts, list_distinct_categories, query_transactions
from db.mongo import get_db
from ingestion.csv_importer import list_mapping_names, parse_csv, save_transactions
from models import Transaction

app = FastAPI(title="Money Slice API")

STATIC_DIR = Path(__file__).parent.parent / "static"


class NoCacheMiddleware(BaseHTTPMiddleware):
    """
    Disables caching on every response.

    This is a small homelab tool, not something sitting behind a CDN, so
    there's no real cost to turning caching off outright - the
    alternative (StaticFiles' default of no explicit Cache-Control,
    which lets browsers apply heuristic freshness off the Last-Modified
    header) means an ordinary reload can silently keep serving an old
    app.js/style.css/index.html after they've been edited, requiring a
    hard refresh to see changes. Not worth the confusion during active
    development.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheMiddleware)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/transactions")
def get_transactions(
    account_id: Optional[str] = None,
    category: Optional[str] = None,
    is_shared: Optional[bool] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    db = get_db()
    return query_transactions(
        db,
        account_id=account_id,
        category=category,
        is_shared=is_shared,
        start=start,
        end=end,
        search=search,
        skip=skip,
        limit=limit,
    )


@app.get("/api/categories")
def get_categories():
    return list_distinct_categories(get_db())


@app.get("/api/accounts")
def get_accounts():
    return list_distinct_accounts(get_db())


@app.get("/api/mappings")
def get_mappings() -> list[str]:
    return list_mapping_names()


@app.post("/api/import")
async def import_csv(
    file: UploadFile = File(...),
    account_id: str = Form(...),
    mapping: str = Form(...),
    source: str = Form("csv"),
) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        transactions = parse_csv(tmp_path, account_id, mapping)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    for txn in transactions:
        txn.source = source

    db = get_db()
    inserted, duplicates = save_transactions(transactions, db=db)
    matched, unmatched = categorisation_rules.run(db=db)
    sharing_result = apply_defaults_module.apply_defaults(db)

    return {
        "inserted": inserted,
        "duplicates": duplicates,
        "categorised": matched,
        "still_uncategorised": unmatched,
        "sharing": sharing_result,
    }


class ManualTransactionIn(BaseModel):
    account_id: str
    date: date_type
    amount: float
    description_raw: str
    category: Optional[str] = None
    is_shared: Optional[bool] = None


class TransactionPatch(BaseModel):
    category: Optional[str] = None
    is_shared: Optional[bool] = None


@app.post("/api/transactions", status_code=201)
def create_transaction(payload: ManualTransactionIn) -> dict:
    txn = Transaction(
        account_id=payload.account_id,
        date=payload.date,
        amount=payload.amount,
        description_raw=payload.description_raw,
        category=payload.category,
        is_shared=payload.is_shared,
        source="manual",
    ).finalize()

    db = get_db()
    inserted, duplicates = save_transactions([txn], db=db)
    if duplicates:
        raise HTTPException(
            status_code=409,
            detail="A transaction with the same account, date, amount, and description already exists.",
        )

    # Only fills in category/is_shared if the caller didn't already
    # supply them - both only ever touch null values (see their own
    # modules for why), so this never overwrites what was just set.
    categorisation_rules.run(db=db)
    apply_defaults_module.apply_defaults(db)

    saved = db.transactions.find_one({"source_hash": txn.source_hash})
    saved["_id"] = str(saved["_id"])
    return saved


@app.patch("/api/transactions/{transaction_id}")
def patch_transaction(transaction_id: str, patch: TransactionPatch) -> dict:
    update_fields = patch.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    try:
        object_id = ObjectId(transaction_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=400, detail=f"'{transaction_id}' is not a valid transaction id."
        ) from exc

    db = get_db()
    result = db.transactions.update_one({"_id": object_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"No transaction with id '{transaction_id}'.")

    updated = db.transactions.find_one({"_id": object_id})
    updated["_id"] = str(updated["_id"])
    return updated


# Serves index.html/app.js/style.css. Mounted last so it doesn't shadow
# the /api/* routes above - Starlette matches routes in registration order.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
