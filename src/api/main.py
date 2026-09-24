"""
FastAPI app for Money Slice.

Currently exposes the CSV import pipeline: upload a bank export and
run import -> categorise -> apply sharing defaults in one call, so the
frontend never has to orchestrate three separate requests.
"""
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import categorisation.rules as categorisation_rules
import sharing.apply_defaults as apply_defaults_module
from db.mongo import get_db
from ingestion.csv_importer import list_mapping_names, parse_csv, save_transactions

app = FastAPI(title="Money Slice API")


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
