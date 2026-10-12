"""Report registry.

Every report reads only the shared transaction view (`v_transactions`) via
`fetch_transactions`, so adding a report never needs schema changes. To add
one, write a function that takes (conn, filters) and returns a dict with
`columns` and `rows`, and decorate it with @report.

Row values for "money" columns are integer cents. A row may carry `children`
(same columns) for drill-down.
"""
from collections import defaultdict
from statistics import median

REPORTS = {}


def report(key, title, description=""):
    def register(fn):
        REPORTS[key] = {"key": key, "title": title, "description": description, "fn": fn}
        return fn
    return register


def fetch_transactions(conn, filters):
    """Live transactions matching the common filters: start, end, entity_id, entity_type."""
    sql = "SELECT * FROM v_transactions WHERE 1=1"
    args = []
    if filters.get("start"):
        sql += " AND date >= ?"
        args.append(filters["start"])
    if filters.get("end"):
        sql += " AND date <= ?"
        args.append(filters["end"])
    if filters.get("entity_id"):
        sql += " AND entity_id = ?"
        args.append(int(filters["entity_id"]))
    if filters.get("entity_type"):
        sql += " AND entity_type = ?"
        args.append(filters["entity_type"])
    return conn.execute(sql + " ORDER BY date, created_at", args).fetchall()


def run_report(conn, key, filters):
    meta = REPORTS[key]
    result = meta["fn"](conn, filters)
    return {"key": key, "title": meta["title"], "description": meta["description"], **result}


def _money(key, label):
    return {"key": key, "label": label, "type": "money"}


def _text(key, label):
    return {"key": key, "label": label, "type": "text"}


@report("by_category", "Spending by category",
        "Expenses grouped by parent group; expand a group to see its categories.")
def by_category(conn, filters):
    groups = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for t in fetch_transactions(conn, filters):
        if t["amount_cents"] >= 0:
            continue
        cell = groups[t["group_name"] or "Uncategorized"][t["category_name"] or "Uncategorized"]
        cell[0] += -t["amount_cents"]
        cell[1] += 1
    total = sum(v[0] for cats in groups.values() for v in cats.values())
    rows = []
    for group, cats in groups.items():
        g_total = sum(v[0] for v in cats.values())
        children = [
            {"name": c, "spent": v[0], "count": v[1], "share": _pct(v[0], total)}
            for c, v in sorted(cats.items(), key=lambda kv: -kv[1][0])
        ]
        rows.append({"name": group, "spent": g_total, "count": sum(v[1] for v in cats.values()),
                     "share": _pct(g_total, total), "children": children})
    rows.sort(key=lambda r: -r["spent"])
    return {
        "columns": [_text("name", "Category"), _money("spent", "Spent"),
                    {"key": "count", "label": "#", "type": "number"},
                    {"key": "share", "label": "Share", "type": "percent"}],
        "rows": rows,
        "totals": {"name": "Total", "spent": total, "count": sum(r["count"] for r in rows), "share": 100.0 if total else None},
    }


@report("by_entity", "Spending by entity",
        "Income, expenses and net for W-2, business, nonprofit and personal; expand a type to see each entity.")
def by_entity(conn, filters):
    labels = dict(conn.execute("SELECT code, label FROM entity_types").fetchall())
    types = defaultdict(lambda: defaultdict(lambda: {"income": 0, "expenses": 0}))
    for t in fetch_transactions(conn, filters):
        cell = types[t["entity_type"] or ""][t["entity_name"] or "Unassigned"]
        if t["amount_cents"] >= 0:
            cell["income"] += t["amount_cents"]
        else:
            cell["expenses"] += -t["amount_cents"]
    rows = []
    for etype, ents in types.items():
        children = [{"name": n, **v, "net": v["income"] - v["expenses"]}
                    for n, v in sorted(ents.items(), key=lambda kv: -kv[1]["expenses"])]
        inc = sum(c["income"] for c in children)
        exp = sum(c["expenses"] for c in children)
        rows.append({"name": labels.get(etype, "Unassigned"), "income": inc, "expenses": exp,
                     "net": inc - exp, "children": children})
    rows.sort(key=lambda r: -r["expenses"])
    inc = sum(r["income"] for r in rows)
    exp = sum(r["expenses"] for r in rows)
    return {
        "columns": [_text("name", "Entity"), _money("income", "Income"),
                    _money("expenses", "Expenses"), _money("net", "Net")],
        "rows": rows,
        "totals": {"name": "Total", "income": inc, "expenses": exp, "net": inc - exp},
    }


@report("monthly", "Month-over-month trends",
        "Income, expenses and net per month, with the change in spending from the prior month.")
def monthly(conn, filters):
    months = defaultdict(lambda: {"income": 0, "expenses": 0})
    for t in fetch_transactions(conn, filters):
        cell = months[t["date"][:7]]
        if t["amount_cents"] >= 0:
            cell["income"] += t["amount_cents"]
        else:
            cell["expenses"] += -t["amount_cents"]
    rows, prev = [], None
    for month in sorted(months):
        v = months[month]
        change = None if prev in (None, 0) else round((v["expenses"] - prev) / prev * 100, 1)
        rows.append({"month": month, **v, "net": v["income"] - v["expenses"], "change": change})
        prev = v["expenses"]
    return {
        "columns": [_text("month", "Month"), _money("income", "Income"), _money("expenses", "Expenses"),
                    _money("net", "Net"), {"key": "change", "label": "Spend vs prior", "type": "percent"}],
        "rows": rows,
    }


def _normalize(desc):
    """Collapse a description to its merchant-ish words so 'NETFLIX.COM 0412' ~ 'Netflix.com 0513'."""
    words = "".join(ch if ch.isalpha() or ch.isspace() else " " for ch in desc.lower()).split()
    return " ".join(words[:3])


@report("recurring", "Recurring subscriptions",
        "Charges from the same payee at a steady amount in 2+ different months — candidates to cut.")
def recurring(conn, filters):
    by_payee = defaultdict(list)
    for t in fetch_transactions(conn, filters):
        if t["amount_cents"] < 0 and _normalize(t["description"]):
            by_payee[_normalize(t["description"])].append(t)
    rows = []
    for payee, txns in by_payee.items():
        months = {t["date"][:7] for t in txns}
        if len(months) < 2:
            continue
        amounts = [-t["amount_cents"] for t in txns]
        typical = median(amounts)
        # Steady amount: every charge within 15% of the typical one.
        if any(abs(a - typical) > typical * 0.15 for a in amounts):
            continue
        last = txns[-1]
        rows.append({
            "name": last["description"], "entity": last["entity_name"] or "",
            "typical": int(typical), "months": len(months), "last": last["date"],
            "annual": int(typical * 12 * len(txns) / len(months)),
        })
    rows.sort(key=lambda r: -r["annual"])
    return {
        "columns": [_text("name", "Payee"), _text("entity", "Entity"), _money("typical", "Typical charge"),
                    {"key": "months", "label": "Months seen", "type": "number"},
                    _text("last", "Last charged"), _money("annual", "Est. per year")],
        "rows": rows,
        "totals": {"name": "Total", "annual": sum(r["annual"] for r in rows)},
    }


@report("reimbursable", "Reimbursable summary",
        "What is owed back, grouped by who owes it. Expand to see the outstanding items.")
def reimbursable(conn, filters):
    owers = defaultdict(lambda: {"owed": 0, "paid": 0, "items": []})
    for t in fetch_transactions(conn, filters):
        if not t["reimbursable"] or t["amount_cents"] >= 0:
            continue
        who = t["reimburse_from"].strip() or t["entity_name"] or "Unassigned"
        amt = -t["amount_cents"]
        if t["reimbursed_on"]:
            owers[who]["paid"] += amt
        else:
            owers[who]["owed"] += amt
            owers[who]["items"].append({"name": f"{t['date']} · {t['description']}", "owed": amt})
    rows = [{"name": who, "owed": v["owed"], "paid": v["paid"], "children": v["items"]}
            for who, v in sorted(owers.items(), key=lambda kv: -kv[1]["owed"])]
    return {
        "columns": [_text("name", "Owed by"), _money("owed", "Still owed"), _money("paid", "Paid back")],
        "rows": rows,
        "totals": {"name": "Total", "owed": sum(r["owed"] for r in rows), "paid": sum(r["paid"] for r in rows)},
    }


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None
