# Finance Tracker

One place to track income and spending across the W-2 job, the businesses,
the nonprofits and personal life, built from [`BRIEF.md`](BRIEF.md).
It is a responsive web app: the same page works on a phone and on a desktop,
and both read the same database.

**Status:** Stage 1 (design) and Stage 2 (minimum working app) are done.
Stage 3 (CSV import, Plaid bank feeds, deduplication) is next.

## Run it

```bash
cd finance-tracker
pip install -r requirements.txt
python app.py                 # http://127.0.0.1:5000
```

To open it from your phone on the same network, run
`HOST=0.0.0.0 FINANCE_PASSWORD=choose-one python app.py` and browse to
`http://<computer-ip>:5000`. When `FINANCE_PASSWORD` is set, the browser asks
for it (any username works). Always set it when the app can be reached by
anyone but you. Data lives in `finance.db`, or wherever `FINANCE_DB` points.

Tests: `pip install pytest && python -m pytest tests`

## What's in Stage 2

- **Transactions tab:** add an expense or income; tag each one with an entity
  and a category; mark it reimbursable, record who owes it, and tick "paid
  back" once it is repaid. Search, filter by entity, or show only rows that
  still need tagging. Tags can be changed right in the list.
- **Reports tab:** every report can show everything combined, one entity
  type (e.g. all businesses), or a single entity, over any date range.
  - Spending by category: parent groups that expand into categories
  - Spending by entity: income, expenses and net, by type and by entity
  - Month-over-month trends
  - Recurring subscriptions: same payee at a steady amount in 2+ months,
    with an estimated yearly cost
  - Reimbursable summary: what is still owed and by whom
- **Settings tab:** add, rename, retype or archive entities; add, rename,
  move or archive categories and parent groups. No code changes needed.
  Archived items drop out of the pickers but stay on old transactions.

## Stage 1 design (see `schema.sql`)

- **One transaction format.** Every transaction, from manual entry, CSV or a
  bank feed, is a row in `transactions`: date, amount (integer cents,
  negative = expense), description, entity, category, `source`
  (`manual`/`csv`/`bank`), a UUID `id`, and the reimbursable fields.
  `app.insert_transaction()` is the single function that writes a
  transaction; the importers in Stage 3 will call it too.
- **Deduplication hooks.** `external_id` holds the source's own ID; a unique
  index on `(source, external_id)` makes re-importing the same file or
  feed a no-op. `duplicate_of` marks a row as a copy of another (such as a
  bank-fed copy of a manual entry). Duplicates stay stored but are left out
  of every list and report.
- **Entities have a type** (`entity_types`: W-2, Business, Nonprofit,
  Personal). **Categories belong to a parent group** (`category_groups`).
  All of these are data, not code, and are seeded on first run. I added an
  **Income** group (Wages, Business Revenue, Reimbursement Received, Other
  Income) because the brief's list only covers expenses.
- **Reports only read data.** Each report is a function in `reports.py`,
  registered with `@report(...)`. It reads the `v_transactions` view and
  returns columns and rows, and the page draws any report generically. To
  add a report, write one function. No schema or frontend change is needed.
- **Future modules** (freelancer tax, rental property) should add their own
  tables that reference `transactions.id` / `entities.id` instead of
  changing the core tables.
