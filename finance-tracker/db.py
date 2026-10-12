"""Database connection, schema setup and default seed data."""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(HERE, "finance.db")

ENTITY_TYPES = [
    ("w2", "W-2"),
    ("business", "Business"),
    ("nonprofit", "Nonprofit"),
    ("personal", "Personal"),
]

ENTITIES = [
    ("Carvana", "w2"),
    ("Environmental Vanguardians", "business"),
    ("Paul's Pipe Shop", "business"),
    ("D&T Computer Consultants", "business"),
    ("American Legion", "nonprofit"),
    ("Spiritual Warfare Unit", "nonprofit"),
    ("Personal", "personal"),
]

# (group, [(category, description)])
CATEGORIES = [
    ("Utilities", [
        ("Electric", ""), ("Gas", ""), ("Water", ""), ("Internet", ""), ("Cell Phone", ""),
    ]),
    ("Food", [
        ("Groceries", "Food eaten at home"),
        ("Dining Out", "Restaurants, takeout"),
    ]),
    ("Transportation", [
        ("Fuel & Vehicle", ""),
    ]),
    ("Other", [
        ("Insurance", ""), ("Software & Subscriptions", ""), ("Professional Services", ""),
        ("Repairs & Maintenance", ""), ("Taxes & Licensing", ""), ("Supplies", ""),
        ("Equipment", ""), ("Travel", ""), ("Advertising & Marketing", ""),
        ("Rent or Lease", ""), ("Housing", ""), ("Healthcare", ""),
        ("Giving / Donations", ""), ("Other", "Catch-all"),
    ]),
    # Not in the brief's expense list, but income needs somewhere to go.
    ("Income", [
        ("Wages", "W-2 paychecks"),
        ("Business Revenue", ""),
        ("Reimbursement Received", ""),
        ("Other Income", ""),
    ]),
]


def connect(path=None):
    conn = sqlite3.connect(path or os.environ.get("FINANCE_DB", DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    with open(os.path.join(HERE, "schema.sql")) as f:
        conn.executescript(f.read())
    if conn.execute("SELECT COUNT(*) FROM entity_types").fetchone()[0] == 0:
        seed(conn)
    conn.commit()


def seed(conn):
    conn.executemany("INSERT INTO entity_types (code, label) VALUES (?, ?)", ENTITY_TYPES)
    conn.executemany("INSERT INTO entities (name, type) VALUES (?, ?)", ENTITIES)
    for order, (group, cats) in enumerate(CATEGORIES):
        gid = conn.execute(
            "INSERT INTO category_groups (name, sort_order) VALUES (?, ?)", (group, order)
        ).lastrowid
        conn.executemany(
            "INSERT INTO categories (group_id, name, description) VALUES (?, ?, ?)",
            [(gid, name, desc) for name, desc in cats],
        )
