"""Stage 3: POS check, system POS orders against the terminal total, per driver and day."""
from datetime import date

from app.database import SessionLocal
from app.models import Collection, PosOrder
from app.seed import DAYS as DAY_COUNT, PLANTED, business_days
from tests.conftest import END

DAYS = business_days(END)
OTHER_DAY = date(2026, 7, 1)  # far from the demo data and from other test files


def did(client, code):
    return next(d["id"] for d in client.get("/api/drivers").json() if d["code"] == code)


def test_demo_data_has_exactly_the_planted_pos_differences(client):
    found = []
    for pos in range(DAY_COUNT):
        for r in client.get("/api/pos", params={"date": DAYS[pos].isoformat()}).json()["rows"]:
            if r["status"] != "agrees":
                found.append((pos, r["driver_code"], r["difference"]))
    assert sorted(found) == sorted(PLANTED["pos_differences"])


def test_a_day_compares_system_orders_with_the_terminal(client):
    pos, code, diff = PLANTED["pos_differences"][0]  # D-105 terminal 150 short
    day = client.get("/api/pos", params={"date": DAYS[pos].isoformat()}).json()
    row = next(r for r in day["rows"] if r["driver_code"] == code)
    assert row["status"] == "terminal_short" and row["difference"] == diff and row["open"]
    assert row["terminal"] == "60311105" and row["order_count"] > 0
    assert row["terminal_total"] == round(row["system_total"] + diff, 2)
    orders = client.get("/api/pos/orders", params={"date": DAYS[pos].isoformat(), "driver_id": row["driver_id"]}).json()
    assert len(orders) == row["order_count"] and round(sum(o["amount"] for o in orders), 2) == row["system_total"]
    t = day["totals"]
    assert t["differences"] == 1 and t["open"] == 1 and t["short"] == 150.0 and t["agrees"] == 10
    assert day["orders_imported"] is True


def test_review_explain_follow_up_reopen_and_stale(client):
    pos, code, _ = PLANTED["pos_differences"][1]  # D-102 terminal over 85.50
    d, driver = DAYS[pos].isoformat(), did(client, code)
    body = {"business_date": d, "driver_id": driver, "status": "explained", "note": ""}
    assert client.put("/api/pos/review", json=body).status_code == 422  # a reason is required
    r = client.put("/api/pos/review", json={**body, "note": "Card  swiped twice, refund issued"}).json()
    assert r["review"]["status"] == "explained" and not r["open"] and not r["review"]["stale"]
    assert "Card swiped twice" in client.get("/api/audit").json()[0]["summary"]
    r = client.put("/api/pos/review", json={**body, "status": "follow_up", "note": ""}).json()
    assert r["open"] and r["review"]["status"] == "follow_up"
    client.put("/api/pos/review", json={**body, "note": "Refund issued"})
    # the terminal total changes after the review: the review is now out of date and the row is open again
    with SessionLocal() as db:
        h = db.query(Collection).filter_by(business_date=DAYS[pos], driver_id=driver).one()
        h.pos_amount += 100
        db.commit()
    row = next(x for x in client.get("/api/pos", params={"date": d}).json()["rows"] if x["driver_id"] == driver)
    assert row["review"]["stale"] and row["open"]
    assert client.delete("/api/pos/review", params={"business_date": d, "driver_id": driver}).json() == {"reopened": True}
    with SessionLocal() as db:
        h = db.query(Collection).filter_by(business_date=DAYS[pos], driver_id=driver).one()
        h.pos_amount -= 100
        db.commit()


def test_only_differences_can_be_reviewed(client):
    r = client.put("/api/pos/review", json={"business_date": DAYS[0].isoformat(), "driver_id": did(client, "D-101"),
                                            "status": "explained", "note": "nothing to explain"})
    assert r.status_code == 409


def upload(name, text):
    return {"file": (name, text.encode(), "text/csv")}


def test_order_import_checks_skips_cash_rows_and_saves(client):
    d = OTHER_DAY.isoformat()
    text = ("Waybill No,Courier ID,COD Amount,Payment Method\n"
            "WB-1,D-101,100.00,POS\n"
            "WB-2,D-101,SAR 50.50,mada\n"
            "WB-3,D-101,70,Cash\n"         # not POS: skipped, not an error
            "WB-1,D-101,100,POS\n"         # repeated
            "WB-4,D-999,10,POS\n"          # unknown driver
            "WB-5,D-102,abc,POS\n")        # bad amount
    r = client.post("/api/pos/import/orders", files=upload("orders.csv", text), data={"business_date": d}).json()
    assert r["counts"] == {"new": 2, "update": 0, "same": 0, "skipped": 1, "error": 3} and r["saved"] == 0
    r = client.post("/api/pos/import/orders", files=upload("orders.csv", text), data={"business_date": d, "commit": "true"}).json()
    assert r["saved"] == 2
    day = client.get("/api/pos", params={"date": d}).json()
    row = next(x for x in day["rows"] if x["driver_code"] == "D-101")
    assert row["system_total"] == 150.5 and row["order_count"] == 2 and row["status"] == "no_terminal"
    # the same file again changes nothing; a corrected amount is an update
    r = client.post("/api/pos/import/orders", files=upload("o.csv", "Order no,Driver ID,Amount\nWB-1,D-101,100\nWB-2,D-101,55\n"),
                    data={"business_date": d}).json()
    assert r["counts"]["same"] == 1 and r["counts"]["update"] == 1


def test_terminal_sheet_sets_terminal_totals(client):
    d = OTHER_DAY.isoformat()
    client.put("/api/collections", json={"business_date": d, "driver_id": did(client, "D-101"),
                                         "expected_cash": 0, "cash_received": 0, "pos_amount": 0})
    text = ("TID,Total Sales\n"
            "6031 1101,150.50\n"     # D-101's terminal, spaces are ignored
            "60311102,10\n"          # D-102 has no handover that day
            "99999999,10\n")         # nobody's terminal
    r = client.post("/api/pos/import/terminals", files=upload("terminals.csv", text), data={"business_date": d}).json()
    assert r["counts"]["update"] == 1 and r["counts"]["error"] == 2
    problems = " | ".join(p for x in r["rows"] for p in x["problems"])
    assert "no handover on this day" in problems and "not given to any driver" in problems
    client.post("/api/pos/import/terminals", files=upload("terminals.csv", text), data={"business_date": d, "commit": "true"})
    row = next(x for x in client.get("/api/pos", params={"date": d}).json()["rows"] if x["driver_code"] == "D-101")
    assert row["terminal_total"] == 150.5 and row["status"] == "agrees"
    assert any("terminal 60311101 total 0.00 -> 150.50" in a["summary"] for a in client.get("/api/audit").json())


def test_terminal_numbers_on_drivers(client):
    drivers = {d["code"]: d for d in client.get("/api/drivers").json()}
    assert drivers["D-101"]["pos_terminal"] == "60311101"
    r = client.patch(f"/api/drivers/{drivers['D-102']['id']}", json={"pos_terminal": "6031 1101"})
    assert r.status_code == 409 and "D-101" in r.json()["error"]["message"]
    r = client.post("/api/drivers", json={"code": "D-301", "name": "Terminal Test", "pos_terminal": " 7777 0001 "})
    assert r.status_code == 201 and r.json()["pos_terminal"] == "77770001"


def test_new_handovers_remember_the_terminal_used(client):
    with SessionLocal() as db:
        assert db.query(PosOrder).count() > 0
        h = db.query(Collection).filter_by(business_date=DAYS[0]).first()
        assert h.pos_terminal and h.pos_terminal == h.driver.pos_terminal


def test_templates(client):
    assert "Order no,Driver ID,Amount" in client.get("/api/pos/template/orders").text
    assert "Terminal ID,Total amount" in client.get("/api/pos/template/terminals").text
    assert client.get("/api/pos/template/nope").status_code == 404


def test_adding_a_column_to_an_old_database(tmp_path):
    """An older database without the terminal columns gets them added at start-up."""
    import sqlalchemy as sa
    from app import database
    old = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with old.begin() as c:
        c.execute(sa.text("CREATE TABLE drivers (id INTEGER PRIMARY KEY, code VARCHAR(20), name VARCHAR(80), phone VARCHAR(20), hub VARCHAR(60), active BOOLEAN, created_at DATETIME)"))
        c.execute(sa.text("INSERT INTO drivers (code, name, phone, hub, active) VALUES ('D-1', 'Old', '', '', 1)"))
    saved, database.engine, database._sqlite = database.engine, old, True
    try:
        added = database.add_missing_columns()
        assert "drivers.pos_terminal" in added
        with old.connect() as c:
            assert c.execute(sa.text("SELECT pos_terminal FROM drivers")).scalar() == ""
    finally:
        database.engine = saved
