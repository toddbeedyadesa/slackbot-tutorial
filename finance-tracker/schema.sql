-- Finance tracker schema (Stage 1: design).
--
-- Core principle: every transaction, however it arrives (manual entry, CSV
-- import, bank feed), lands in the single `transactions` table below. Tagging,
-- reports and views read only from this table and never care about the source.
--
-- Money is stored as integer cents. Expenses are negative, income is positive.
-- Dates are ISO-8601 strings (YYYY-MM-DD).
--
-- Future modules (e.g. freelancer tax, rental property) should add their own
-- tables that reference transactions(id) / entities(id) rather than altering
-- these core tables.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entity_types (
    code  TEXT PRIMARY KEY,           -- 'w2', 'business', 'nonprofit', 'personal'
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    type       TEXT NOT NULL REFERENCES entity_types(code),
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS category_groups (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY,
    group_id    INTEGER NOT NULL REFERENCES category_groups(id),
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT PRIMARY KEY,               -- internal unique ID (UUID)
    date             TEXT NOT NULL,                  -- YYYY-MM-DD
    amount_cents     INTEGER NOT NULL,               -- negative = expense, positive = income
    description      TEXT NOT NULL DEFAULT '',
    entity_id        INTEGER REFERENCES entities(id),
    category_id      INTEGER REFERENCES categories(id),
    source           TEXT NOT NULL CHECK (source IN ('manual', 'csv', 'bank')),
    -- ID supplied by the source (bank transaction id, CSV row hash). Together
    -- with `source` it lets re-imports of the same data be skipped. Manual
    -- entries leave it NULL.
    external_id      TEXT,
    reimbursable     INTEGER NOT NULL DEFAULT 0 CHECK (reimbursable IN (0, 1)),
    reimburse_from   TEXT NOT NULL DEFAULT '',       -- who owes it back (free text)
    reimbursed_on    TEXT,                           -- date paid back; NULL = still owed
    -- Set when this row was found to be a copy of another transaction (e.g. a
    -- bank-fed copy of a manual entry). Duplicates are excluded from reports.
    duplicate_of     TEXT REFERENCES transactions(id),
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_source_external
    ON transactions(source, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_transactions_entity ON transactions(entity_id);
CREATE INDEX IF NOT EXISTS ix_transactions_category ON transactions(category_id);

-- The one view every report reads from: live (non-duplicate) transactions
-- joined to their entity and category labels.
CREATE VIEW IF NOT EXISTS v_transactions AS
SELECT t.*,
       e.name  AS entity_name,
       e.type  AS entity_type,
       c.name  AS category_name,
       g.id    AS group_id,
       g.name  AS group_name
FROM transactions t
LEFT JOIN entities e        ON e.id = t.entity_id
LEFT JOIN categories c      ON c.id = t.category_id
LEFT JOIN category_groups g ON g.id = c.group_id
WHERE t.duplicate_of IS NULL;
