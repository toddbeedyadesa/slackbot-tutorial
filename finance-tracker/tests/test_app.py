import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as finance  # noqa: E402


@pytest.fixture
def client(tmp_path):
    flask_app = finance.create_app(str(tmp_path / "test.db"))
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def ids(client):
    meta = client.get("/api/meta").get_json()
    ents = {e["name"]: e["id"] for e in meta["entities"]}
    cats = {c["name"]: c["id"] for g in meta["category_groups"] for c in g["categories"]}
    return ents, cats


def add(client, **kw):
    res = client.post("/api/transactions", json=kw)
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_seed_matches_brief(client):
    meta = client.get("/api/meta").get_json()
    types = {e["name"]: e["type"] for e in meta["entities"]}
    assert types["Carvana"] == "w2"
    assert types["Paul's Pipe Shop"] == "business"
    assert types["American Legion"] == "nonprofit"
    assert len(types) == 7
    groups = {g["name"]: [c["name"] for c in g["categories"]] for g in meta["category_groups"]}
    assert set(groups["Food"]) == {"Groceries", "Dining Out"}
    assert "Giving / Donations" in groups["Other"]
    assert len(meta["reports"]) == 5


def test_manual_entry_and_tagging(client):
    ents, cats = ids(client)
    t = add(client, date="2026-10-01", amount="-42.50", description="Duke Energy",
            entity_id=ents["Personal"], category_id=cats["Electric"])
    assert t["amount_cents"] == -4250 and t["source"] == "manual" and t["reimbursable"] == 0
    assert t["group_name"] == "Utilities"

    res = client.patch(f"/api/transactions/{t['id']}", json={
        "entity_id": ents["D&T Computer Consultants"], "reimbursable": True, "reimburse_from": "Client X"})
    assert res.get_json()["entity_name"] == "D&T Computer Consultants"
    assert res.get_json()["reimbursable"] == 1

    rows = client.get("/api/transactions").get_json()["transactions"]
    assert [r["id"] for r in rows] == [t["id"]]


def test_validation(client):
    assert client.post("/api/transactions", json={"date": "2026-13-01", "amount": "1"}).status_code == 400
    assert client.post("/api/transactions", json={"date": "2026-10-01", "amount": "abc"}).status_code == 400
    assert client.post("/api/transactions", json={"date": "2026-10-01", "amount": "1", "entity_id": 999}).status_code == 400


def test_entities_and_categories_editable(client):
    res = client.post("/api/entities", json={"name": "Rental House", "type": "business"})
    eid = res.get_json()["id"]
    client.patch(f"/api/entities/{eid}", json={"name": "Rental Duplex", "archived": True})
    ent = next(e for e in client.get("/api/meta").get_json()["entities"] if e["id"] == eid)
    assert ent["name"] == "Rental Duplex" and ent["archived"] == 1
    assert client.post("/api/entities", json={"name": "X", "type": "bogus"}).status_code == 400

    gid = client.post("/api/category-groups", json={"name": "Pets"}).get_json()["id"]
    cid = client.post("/api/categories", json={"group_id": gid, "name": "Vet"}).get_json()["id"]
    client.patch(f"/api/categories/{cid}", json={"name": "Veterinary"})
    groups = client.get("/api/meta").get_json()["category_groups"]
    assert any(c["name"] == "Veterinary" for g in groups if g["id"] == gid for c in g["categories"])


def report(client, key, **params):
    return client.get(f"/api/reports/{key}", query_string=params).get_json()


def test_reports(client):
    ents, cats = ids(client)
    P, DT, CV = ents["Personal"], ents["D&T Computer Consultants"], ents["Carvana"]
    add(client, date="2026-08-03", amount="3000", description="Paycheck", entity_id=CV, category_id=cats["Wages"])
    add(client, date="2026-08-05", amount="-100", description="Kroger", entity_id=P, category_id=cats["Groceries"])
    add(client, date="2026-08-09", amount="-40", description="Olive Garden", entity_id=P, category_id=cats["Dining Out"])
    add(client, date="2026-08-15", amount="-15.99", description="NETFLIX.COM 0815", entity_id=P,
        category_id=cats["Software & Subscriptions"])
    add(client, date="2026-09-15", amount="-15.99", description="Netflix.com 0915", entity_id=P,
        category_id=cats["Software & Subscriptions"])
    add(client, date="2026-09-20", amount="-200", description="Laptop bag", entity_id=DT,
        category_id=cats["Equipment"], reimbursable=True, reimburse_from="Acme client")

    cat = report(client, "by_category")
    food = next(r for r in cat["rows"] if r["name"] == "Food")
    assert food["spent"] == 14000
    assert {c["name"] for c in food["children"]} == {"Groceries", "Dining Out"}
    assert cat["totals"]["spent"] == 10000 + 4000 + 1599 * 2 + 20000

    # per-entity scope
    only_dt = report(client, "by_category", entity_id=DT)
    assert only_dt["totals"]["spent"] == 20000
    by_type = report(client, "by_entity", entity_type="business")
    assert [r["name"] for r in by_type["rows"]] == ["Business"]

    ent = report(client, "by_entity")
    w2 = next(r for r in ent["rows"] if r["name"] == "W-2")
    assert w2["income"] == 300000 and w2["net"] == 300000

    months = report(client, "monthly")["rows"]
    assert [m["month"] for m in months] == ["2026-08", "2026-09"]
    assert months[0]["expenses"] == 15599 and months[1]["expenses"] == 21599

    rec = report(client, "recurring")["rows"]
    assert len(rec) == 1 and rec[0]["typical"] == 1599 and rec[0]["months"] == 2

    reimb = report(client, "reimbursable")
    assert reimb["rows"][0]["name"] == "Acme client" and reimb["rows"][0]["owed"] == 20000

    # date filter
    assert report(client, "by_category", start="2026-09-01")["totals"]["spent"] == 1599 + 20000


def test_reimbursed_moves_to_paid(client):
    ents, cats = ids(client)
    t = add(client, date="2026-09-01", amount="-50", description="Supplies", entity_id=ents["American Legion"],
            category_id=cats["Supplies"], reimbursable=True)
    client.patch(f"/api/transactions/{t['id']}", json={"reimbursed_on": "2026-09-10"})
    row = report(client, "reimbursable")["rows"][0]
    assert row["name"] == "American Legion" and row["owed"] == 0 and row["paid"] == 5000


def test_duplicates_excluded_and_delete(client):
    a = add(client, date="2026-09-01", amount="-10", description="Coffee")
    b = add(client, date="2026-09-01", amount="-10", description="COFFEE SHOP")
    conn = finance.db.connect(finance.app.config["DB_PATH"])
    conn.execute("UPDATE transactions SET duplicate_of = ? WHERE id = ?", (a["id"], b["id"]))
    conn.commit()
    conn.close()
    assert report(client, "by_category")["totals"]["spent"] == 1000
    assert client.delete(f"/api/transactions/{a['id']}").status_code == 204
    # the former duplicate becomes live again rather than dangling
    assert report(client, "by_category")["totals"]["spent"] == 1000


def test_password(client, monkeypatch):
    monkeypatch.setenv("FINANCE_PASSWORD", "s3cret")
    assert client.get("/api/meta").status_code == 401
    import base64
    tok = base64.b64encode(b"me:s3cret").decode()
    assert client.get("/api/meta", headers={"Authorization": f"Basic {tok}"}).status_code == 200
