# Phase 1: Schema + CSV Ingestion + Rule-Based categorisation

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

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers every mapping in `bank_mappings.yaml` (sign conventions, date
formats, source_category capture), the source_hash idempotency logic,
and the categoriser rules - all against sample fixture CSVs in
`tests/fixtures/`, no real MongoDB or real bank data needed. Add a
fixture CSV + test whenever a new bank mapping is added.

## What's deliberately NOT here yet

- Household/shared-cost logic (Phase 2)
- GoCardless auto-sync (Phase 3)
- Any API/UI - direct Mongo queries are fine for now

## Immediate next steps for you

- [ ] Confirm/fix the column mappings against your real bank CSVs (this
      will almost certainly need edits - I wrote plausible guesses, not
      verified formats)
- [ ] Import 1-2 months for each account (yours + Deirbhile's)
- [ ] Skim `category` counts, add merchant strings to
      `category_rules.yaml` for whatever's landing in "uncategorised"
- [ ] Once categorisation looks reasonably solid, we move to Phase 2
      (household shared-cost model)
