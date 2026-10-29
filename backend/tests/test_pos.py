"""Stage 3: POS check, system POS orders against the terminal total, per driver and day."""
from datetime import date, timedelta

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


def test_terminal_sheet_pairs_registered_machines(client):
    d = OTHER_DAY.isoformat()
    client.put("/api/collections", json={"business_date": d, "driver_id": did(client, "D-101"),
                                         "expected_cash": 0, "cash_received": 0, "pos_amount": 0})
    text = ("TID,Total Sales\n"
            "6031 1101,150.50\n"     # D-101's registered machine, spaces are ignored
            "60311102,10\n"          # D-102's machine: paired even without a handover
            "99999999,10\n")         # nobody's machine and no driver with this amount
    r = client.post("/api/pos/import/terminals", files=upload("terminals.csv", text), data={"business_date": d}).json()
    assert r["counts"]["new"] == 3 and r["counts"]["error"] == 0
    assert [(x["driver_code"], x["paired_by"]) for x in r["rows"]] == [("D-101", "terminal"), ("D-102", "terminal"), (None, None)]
    client.post("/api/pos/import/terminals", files=upload("terminals.csv", text), data={"business_date": d, "commit": "true"})
    day = client.get("/api/pos", params={"date": d}).json()
    row = next(x for x in day["rows"] if x["driver_code"] == "D-101")
    assert row["terminal_total"] == 150.5 and row["status"] == "agrees" and row["paired_by"] == "terminal"
    assert day["totals"]["unpaired"] == 1 and day["totals"]["machines_total"] == 170.5
    assert day["totals"]["difference"] == round(170.5 - day["totals"]["system_total"], 2)
    handover = next(h for h in client.get("/api/collections", params={"date": d}).json()["rows"] if h["driver_code"] == "D-101")
    assert handover["pos_amount"] == 150.5  # the handover follows the machine
    assert any("POS 0.00 -> 150.50" in a["summary"] for a in client.get("/api/audit").json())


def _sheet(day, rows):
    """A terminal sheet laid out like a real desk sheet: a total line, then 'POS Code | <date>'."""
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Total POS COD", "=SUM(B3:B20)"])  # a formula without a saved value reads as empty
    ws.append(["POS Code", day])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return {"file": ("terminal.xlsx", buf.getvalue(), "application/octet-stream")}


def test_machines_without_owner_are_paired_by_exact_amount(client):
    day = date.today() - timedelta(days=1)  # recent, so it shows in the dashboard's alerts
    d = day.isoformat()
    sheet = _sheet(day, [(64800001, 300), (64800002, "125.50"), (64800003, 95), (64800004, None),
                         (64800005, 50), (64800006, 50), ("Grand Total", 620.5)])
    r = client.post("/api/pos/import/terminals", files=sheet, data={"business_date": d}).json()
    assert r["counts"] == {"new": 5, "update": 0, "same": 0, "skipped": 2, "error": 0}
    assert r["dates"] == [d] and r["rows"][0]["line"] == 3  # row numbers as in Excel
    client.post("/api/pos/import/terminals", files=sheet, data={"business_date": d, "commit": "true"})
    assert client.get("/api/pos", params={"date": d}).json()["totals"]["unpaired"] == 5  # no system orders yet

    # the system orders arrive: exact amounts pair, two drivers with the same 50.00 are left to the person
    orders = ("Order no,Driver ID,Amount\nPR-1,D-103,200\nPR-2,D-103,100\nPR-3,D-104,125.50\nPR-4,D-106,80\n"
              "PR-5,D-107,50\nPR-6,D-108,50\n")
    client.post("/api/pos/import/orders", files=upload("o.csv", orders), data={"business_date": d, "commit": "true"})
    p = client.get("/api/pos", params={"date": d}).json()
    rows = {x["driver_code"]: x for x in p["rows"]}
    assert rows["D-103"]["status"] == "agrees" and rows["D-103"]["terminal"] == "64800001" and rows["D-103"]["paired_by"] == "amount"
    assert rows["D-104"]["status"] == "agrees" and rows["D-106"]["status"] == "no_terminal"
    t = p["totals"]
    assert (t["machines_total"], t["system_total"], t["difference"], t["unpaired"]) == (620.5, 605.5, 15.0, 3)
    free = {m["terminal"]: m for m in p["machines"] if not m["driver_id"]}
    assert set(free) == {"64800003", "64800005", "64800006"}
    near = free["64800003"]["suggestions"][0]
    assert near["driver_code"] == "D-106" and near["difference"] == 15.0
    alerts = client.get("/api/dashboard", params={"date": d}).json()["alerts"]
    assert any(a["kind"] == "pos_unpaired" and a["date"] == d for a in alerts)

    # the person pairs the rest by hand
    client.put(f"/api/pos/machines/{free['64800003']['id']}", json={"driver_id": did(client, "D-106")})
    client.put(f"/api/pos/machines/{free['64800005']['id']}", json={"driver_id": did(client, "D-107")})
    client.put(f"/api/pos/machines/{free['64800006']['id']}", json={"driver_id": did(client, "D-108")})
    p = client.get("/api/pos", params={"date": d}).json()
    rows = {x["driver_code"]: x for x in p["rows"]}
    assert rows["D-106"]["status"] == "terminal_over" and rows["D-106"]["difference"] == 15.0 and rows["D-106"]["paired_by"] == "hand"
    assert p["totals"]["unpaired"] == 0 and p["totals"]["difference"] == 15.0
    # and can undo a pair
    client.put(f"/api/pos/machines/{free['64800006']['id']}", json={"driver_id": None})
    assert client.get("/api/pos", params={"date": d}).json()["totals"]["unpaired"] == 1
    # a machine entered by mistake is removed, but only once it has no driver
    assert client.delete(f"/api/pos/machines/{free['64800005']['id']}").status_code == 409
    assert client.delete(f"/api/pos/machines/{free['64800006']['id']}").json() == {"removed": True}
    assert client.get("/api/pos", params={"date": d}).json()["totals"]["machines_total"] == 570.5


def test_date_headings():
    from app.files import header_day
    assert header_day("27-Oct", 2026) == date(2026, 10, 27)
    assert header_day("2026-10-27 00:00:00", 2000) == date(2026, 10, 27)
    assert header_day("27/10/2026", 2000) == date(2026, 10, 27)
    assert header_day("26821.07", 2026) is None and header_day("Total", 2026) is None


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


def test_terminals_wait_until_the_days_pos_orders_are_imported(client):
    d = "2026-03-03"
    driver = did(client, "D-104")
    client.put("/api/collections", json={"business_date": d, "driver_id": driver, "expected_cash": 0, "cash_received": 0, "pos_amount": 500})
    day = client.get("/api/pos", params={"date": d}).json()
    row = next(r for r in day["rows"] if r["driver_id"] == driver)
    assert row["status"] == "awaiting_orders" and not row["open"]
    assert day["totals"]["differences"] == 0 and day["totals"]["awaiting"] == 1 and day["totals"]["difference"] == 0
    assert client.get("/api/dashboard", params={"date": d}).json()["figures"]["pos_awaiting"] == 1
    client.post("/api/pos/import/orders", files=upload("o.csv", "Order no,Driver ID,Amount\nWAIT-1,D-104,450\n"),
                data={"business_date": d, "commit": "true"})
    row = next(r for r in client.get("/api/pos", params={"date": d}).json()["rows"] if r["driver_id"] == driver)
    assert row["status"] == "terminal_over" and row["difference"] == 50.0 and row["open"]
