"""Finance tracker web app: JSON API + a single responsive page.

Run:  python app.py   (then open http://localhost:5000 on desktop or phone)
"""
import os
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory

import db
from reports import REPORTS, run_report

app = Flask(__name__, static_folder="static")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SOURCES = ("manual", "csv", "bank")


class BadRequest(Exception):
    pass


@app.errorhandler(BadRequest)
def bad_request(e):
    return jsonify(error=str(e)), 400


def get_db():
    if "db" not in g:
        g.db = db.connect(app.config.get("DB_PATH"))
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.before_request
def require_password():
    # Set FINANCE_PASSWORD when the app is reachable from outside your machine.
    password = os.environ.get("FINANCE_PASSWORD")
    if not password:
        return None
    auth = request.authorization
    if auth and auth.password == password:
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Finance"'})


# ---------------------------------------------------------------- pages

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------- reference data

@app.get("/api/meta")
def meta():
    conn = get_db()
    groups = [dict(r) for r in conn.execute("SELECT * FROM category_groups ORDER BY sort_order, name")]
    cats = [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY name")]
    for grp in groups:
        grp["categories"] = [c for c in cats if c["group_id"] == grp["id"]]
    return jsonify(
        entity_types=[dict(r) for r in conn.execute("SELECT * FROM entity_types")],
        entities=[dict(r) for r in conn.execute("SELECT * FROM entities ORDER BY archived, name")],
        category_groups=groups,
        reports=[{k: v for k, v in r.items() if k != "fn"} for r in REPORTS.values()],
    )


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Expected a JSON object")
    return data


def _name(data, required=True):
    name = str(data.get("name", "")).strip()
    if required and not name:
        raise BadRequest("Name is required")
    return name


def _write(sql, args):
    conn = get_db()
    try:
        cur = conn.execute(sql, args)
    except db.sqlite3.IntegrityError as e:
        raise BadRequest(f"Not saved: {e}") from e
    conn.commit()
    return cur


def _update(table, row_id, data, allowed):
    fields = {k: data[k] for k in allowed if k in data}
    if "name" in fields:
        fields["name"] = _name(fields)
    if "archived" in fields:
        fields["archived"] = 1 if fields["archived"] else 0
    if not fields:
        raise BadRequest("Nothing to update")
    sets = ", ".join(f"{k} = ?" for k in fields)
    cur = _write(f"UPDATE {table} SET {sets} WHERE id = ?", [*fields.values(), row_id])
    if cur.rowcount == 0:
        abort(404)
    return jsonify(dict(get_db().execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()))


@app.post("/api/entities")
def create_entity():
    data = _body()
    cur = _write("INSERT INTO entities (name, type) VALUES (?, ?)", (_name(data), data.get("type", "")))
    return jsonify(id=cur.lastrowid), 201


@app.patch("/api/entities/<int:row_id>")
def update_entity(row_id):
    return _update("entities", row_id, _body(), ("name", "type", "archived"))


@app.post("/api/category-groups")
def create_group():
    data = _body()
    order = get_db().execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM category_groups").fetchone()[0]
    cur = _write("INSERT INTO category_groups (name, sort_order) VALUES (?, ?)", (_name(data), order))
    return jsonify(id=cur.lastrowid), 201


@app.patch("/api/category-groups/<int:row_id>")
def update_group(row_id):
    return _update("category_groups", row_id, _body(), ("name", "sort_order", "archived"))


@app.post("/api/categories")
def create_category():
    data = _body()
    cur = _write(
        "INSERT INTO categories (group_id, name, description) VALUES (?, ?, ?)",
        (data.get("group_id"), _name(data), str(data.get("description", ""))),
    )
    return jsonify(id=cur.lastrowid), 201


@app.patch("/api/categories/<int:row_id>")
def update_category(row_id):
    return _update("categories", row_id, _body(), ("name", "group_id", "description", "archived"))


# ---------------------------------------------------------------- transactions

def parse_amount_cents(data):
    if "amount_cents" in data:
        try:
            return int(data["amount_cents"])
        except (TypeError, ValueError):
            raise BadRequest("amount_cents must be a whole number") from None
    raw = str(data.get("amount", "")).replace("$", "").replace(",", "").strip()
    try:
        return int((Decimal(raw) * 100).quantize(Decimal(1)))
    except InvalidOperation:
        raise BadRequest("Amount is required, e.g. -42.50 for an expense") from None


def clean_transaction(data, partial=False):
    """Validate input into the shared transaction format. Used by every source."""
    out = {}
    if not partial or "date" in data:
        d = str(data.get("date") or "")
        if not DATE_RE.match(d):
            raise BadRequest("Date must be YYYY-MM-DD")
        try:
            date.fromisoformat(d)
        except ValueError:
            raise BadRequest("Date is not a real calendar date") from None
        out["date"] = d
    if not partial or "amount" in data or "amount_cents" in data:
        out["amount_cents"] = parse_amount_cents(data)
    for key in ("description", "reimburse_from", "notes"):
        if not partial or key in data:
            out[key] = str(data.get(key) or "").strip()
    for key in ("entity_id", "category_id"):
        if not partial or key in data:
            out[key] = int(data[key]) if data.get(key) not in (None, "") else None
    if not partial or "reimbursable" in data:
        out["reimbursable"] = 1 if data.get("reimbursable") else 0
    if "reimbursed_on" in data:
        val = data["reimbursed_on"] or None
        if val and not DATE_RE.match(str(val)):
            raise BadRequest("reimbursed_on must be YYYY-MM-DD")
        out["reimbursed_on"] = val
    return out


def insert_transaction(conn, data, source, external_id=None):
    """The single entry point that stores a transaction, whatever its source."""
    if source not in SOURCES:
        raise BadRequest(f"Unknown source {source!r}")
    row = clean_transaction(data)
    row.update(id=str(uuid.uuid4()), source=source, external_id=external_id)
    cols = ", ".join(row)
    try:
        conn.execute(f"INSERT INTO transactions ({cols}) VALUES ({', '.join('?' * len(row))})",
                     list(row.values()))
    except db.sqlite3.IntegrityError as e:
        raise BadRequest(f"Not saved: {e}") from e
    return row["id"]


def get_transaction(conn, txn_id):
    row = conn.execute(
        "SELECT t.*, e.name AS entity_name, c.name AS category_name, g.name AS group_name "
        "FROM transactions t LEFT JOIN entities e ON e.id = t.entity_id "
        "LEFT JOIN categories c ON c.id = t.category_id "
        "LEFT JOIN category_groups g ON g.id = c.group_id WHERE t.id = ?", (txn_id,)).fetchone()
    if row is None:
        abort(404)
    return dict(row)


@app.get("/api/transactions")
def list_transactions():
    args = request.args
    sql = ("SELECT * FROM v_transactions WHERE 1=1")
    params = []
    for key, clause in (("start", "date >= ?"), ("end", "date <= ?"),
                        ("entity_id", "entity_id = ?"), ("category_id", "category_id = ?"),
                        ("source", "source = ?")):
        if args.get(key):
            sql += f" AND {clause}"
            params.append(args[key])
    if args.get("uncategorized"):
        sql += " AND (entity_id IS NULL OR category_id IS NULL)"
    if args.get("q"):
        sql += " AND (description LIKE ? OR notes LIKE ?)"
        params += [f"%{args['q']}%"] * 2
    sql += " ORDER BY date DESC, created_at DESC LIMIT ?"
    params.append(min(int(args.get("limit", 500)), 5000))
    rows = [dict(r) for r in get_db().execute(sql, params)]
    return jsonify(transactions=rows)


@app.post("/api/transactions")
def create_transaction():
    conn = get_db()
    txn_id = insert_transaction(conn, _body(), "manual")
    conn.commit()
    return jsonify(get_transaction(conn, txn_id)), 201


@app.patch("/api/transactions/<txn_id>")
def update_transaction(txn_id):
    conn = get_db()
    fields = clean_transaction(_body(), partial=True)
    if not fields:
        raise BadRequest("Nothing to update")
    sets = ", ".join(f"{k} = ?" for k in fields)
    try:
        cur = conn.execute(f"UPDATE transactions SET {sets}, updated_at = datetime('now') WHERE id = ?",
                           [*fields.values(), txn_id])
    except db.sqlite3.IntegrityError as e:
        raise BadRequest(f"Not saved: {e}") from e
    if cur.rowcount == 0:
        abort(404)
    conn.commit()
    return jsonify(get_transaction(conn, txn_id))


@app.delete("/api/transactions/<txn_id>")
def delete_transaction(txn_id):
    conn = get_db()
    conn.execute("UPDATE transactions SET duplicate_of = NULL WHERE duplicate_of = ?", (txn_id,))
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    if cur.rowcount == 0:
        abort(404)
    conn.commit()
    return "", 204


# ---------------------------------------------------------------- reports

@app.get("/api/reports/<key>")
def get_report(key):
    if key not in REPORTS:
        abort(404)
    filters = {k: request.args.get(k) for k in ("start", "end", "entity_id", "entity_type")}
    return jsonify(run_report(get_db(), key, filters))


def create_app(db_path=None):
    if db_path:
        app.config["DB_PATH"] = db_path
    conn = db.connect(app.config.get("DB_PATH"))
    db.init_db(conn)
    conn.close()
    return app


if __name__ == "__main__":
    create_app().run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
