# Phase 1: Schema + CSV Ingestion + Rule-Based Categorization

## Setup

```bash
cd finance-tracker
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Make sure your local MongoDB instance is running and reachable at
`mongodb://localhost:27017` (or set `MONGO_URI` env var if different).

## First run

1. Export a CSV statement from one account (a month or two of history is
   plenty to start with).
2. Check the CSV's actual column headers against `config/bank_mappings.yaml`.
   **The mappings in there are best-guess placeholders** - open your CSV
   and confirm the column names match, or add a new mapping block.
3. Run the import:

```bash
cd src
python -m ingestion.csv_importer \
    --file /path/to/statement.csv \
    --account-id danske-current-tiarnan \
    --mapping generic_uk_debit_credit
```

4. categorise what was imported:

```bash
python -m categorisation.rules
```

5. Sanity check in Mongo shell / Compass:

```js
use finance_tracker
db.transactions.find().sort({date: -1}).limit(10)
db.transactions.countDocuments({category: null})  // your "uncategorised" backlog
```

## Repeat for every account

Same two commands, different `--account-id` and `--mapping`. Account IDs
are just strings you choose - keep them stable and descriptive
(`bank-type-owner`), you'll reference them everywhere downstream.

## Accounts with no CSV export (manual entry)

If a bank only offers PDF statements (AIB, for example), don't build a
PDF parser for it - use manual entry instead. It goes through the exact
same pipeline as every other account, just hand-typed:

1. Copy `manual_entry_template.csv` somewhere convenient.
2. Read the PDF statement and fill in one row per transaction. Note:
   this template uses OUR sign convention directly (negative = spend),
   unlike Amex/NatWest credit card - so just type what you see as a
   negative for anything spent, positive for anything received.
3. Import as normal, but tag it as manual so it's distinguishable later:

```bash
python -m ingestion.csv_importer \
    --file /path/to/manual_entry.csv \
    --account-id aib-current-deirbhile \
    --mapping manual_entry \
    --source manual
```

## Household shared-cost splitting (Phase 2)

Three steps, run in this order:

1. **One-time migration** (only if you already imported transactions before
   this feature existed - your data will have `is_shared: False` from the
   old default, which needs resetting to "undecided" first):

```bash
python -m sharing.reset_sharing_status
```

2. **Fill in `config/account_owners.yaml`** with your real account IDs
   mapped to `tiarnan`, `deirbhile`, or `joint` - settlement can't tell
   who paid for anything without this.

3. **Apply category-based sharing defaults**, then run settlement for a
   period with whatever ratio you've agreed for it:

```bash
python -m sharing.apply_defaults
python -m sharing.settlement --tiarnan-ratio 0.5712 --start 2026-08-01 --end 2026-08-31
```

`apply_defaults` only touches transactions still marked undecided - open
`config/sharing_defaults.yaml` to see or change which categories default
to shared vs personal. To override an individual transaction, edit it
directly via mongo-express (http://localhost:8081) - set `is_shared` to
`true`/`false` and it's protected from ever being touched by
`apply_defaults` again.

The ratio isn't stored anywhere - it's a per-run argument, since you
decide this per period rather than fixing it once.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers every mapping in `bank_mappings.yaml` (sign conventions, date
formats, source_category capture), the source_hash idempotency logic,
the categorizer rules, and the sharing-defaults/settlement logic - all
against sample fixture data or mongomock, no real MongoDB needed. Add a
fixture CSV + test whenever a new bank mapping is added.

## What's deliberately NOT here yet

- GoCardless auto-sync (Phase 3)
- Any API/UI - direct Mongo queries (or mongo-express) are fine for now

## Immediate next steps for you

- [ ] Run `sharing.reset_sharing_status` once (only needed if you already
      imported transactions before this feature existed)
- [ ] Fill in `config/account_owners.yaml` with your real account IDs
- [ ] Run `sharing.apply_defaults`, then spot-check a sample of what got
      marked shared vs personal - adjust `config/sharing_defaults.yaml`
      if any category default feels wrong
- [ ] Run a real `sharing.settlement` for last month and sanity-check the
      numbers against what you'd expect
- [x] Fixed the recurring `"Balance as at ..."` / NaN-amount row: there
      was no skip-blank-row logic despite this being noted as if it
      existed - `parse_csv()` now guards against it via
      `row_has_valid_amount()`, `Transaction.amount` rejects
      non-finite values at the model level as a fallback, and
      `ingestion/cleanup_balance_rows.py` removes any already-imported
      NaN rows from the database.


uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
