"""
Thin API over the MongoDB transaction data, plus the static frontend
that consumes it.

Run with:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Then open http://localhost:8000
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from api.queries import list_distinct_accounts, list_distinct_categories, query_transactions
from db.mongo import get_db

app = FastAPI(title="Money Slice API")

STATIC_DIR = Path(__file__).parent.parent / "static"


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


# Serves index.html/app.js/style.css. Mounted last so it doesn't shadow
# the /api/* routes above - Starlette matches routes in registration order.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
