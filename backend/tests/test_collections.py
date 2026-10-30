"""Stage 2: driver handovers, cash shortage checks and file import."""
import io
from datetime import date, timedelta

import pandas as pd

from app.seed import PLANTED, business_days
from tests.conftest import END

DAYS = business_days(END)
EMPTY_DAY = date(2026, 9, 1)  # before the demo data starts


def driver_id(client, code):
    return next(d["id"] for d in client.get("/api/drivers").json() if d["code"] == code)


def test_a_day_lists_every_handover_with_its_cash_difference(client):
    pos, code, sar = PLANTED["cash_differences"][0]  # D-103 was 50 short
    day = client.get("/api/collections", params={"date": DAYS[pos].isoformat()}).json()
    row = next(r for r in day["rows"] if r["driver_code"] == code)
    assert row["status"] == "short" and row["difference"] == sar
    assert row["cash_received"] == round(row["expected_cash"] + sar, 2)
    assert row["total"] == round(row["cash_received"] + row["pos_amount"], 2)
    t = day["totals"]
    assert t["drivers"] == 11 and t["short_count"] == 1 and t["short"] == 50.0 and t["difference"] == -50.0
    assert t["cash_received"] == round(sum(r["cash_received"] for r in day["rows"]), 2)
    assert not [m for m in day["missing"] if m["code"] < "D-113"]  # every demo driver handed over


def test_an_empty_day_lists_drivers_still_to_hand_over(client):
    day = client.get("/api/collections", params={"date": EMPTY_DAY.isoformat()}).json()
    assert day["rows"] == [] and day["totals"]["drivers"] == 0
    codes = [m["code"] for m in day["missing"]]
    assert "D-101" in codes and "D-112" not in codes  # inactive drivers are not expected


def test_recent_days_summary(client):
    days = client.get("/api/collections/days", params={"end": END.isoformat(), "count": 14}).json()
    assert days[0]["date"] == END.isoformat() and days[0]["drivers"] == 11
    by_date = {d["date"]: d for d in days}
    assert by_date[DAYS[3].isoformat()]["short"] == 120.0  # D-107
    assert by_date[DAYS[8].isoformat()]["short"] == 0.0 and by_date[DAYS[8].isoformat()]["difference"] == 30.0  # only an excess


def test_record_update_and_delete_a_handover(client):
    did = driver_id(client, "D-105")
    body = {"business_date": EMPTY_DAY.isoformat(), "driver_id": did, "orders": 20,
            "expected_cash": "1,500.00", "cash_received": 1480, "pos_amount": "620.5", "note": "  counted   twice "}
    r = client.put("/api/collections", json=body)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["result"] == "new" and row["difference"] == -20.0 and row["status"] == "short" and row["note"] == "counted twice"
    assert client.put("/api/collections", json=body).json()["result"] == "same"  # saving again changes nothing
    r = client.put("/api/collections", json={**body, "cash_received": "1500"})
    assert r.json()["result"] == "updated" and r.json()["status"] == "ok"
    log = client.get("/api/audit").json()[0]["summary"]
    assert "D-105" in log and "cash 1,480.00" in log and "-> expected 1,500.00, cash 1,500.00" in log
    assert client.delete(f"/api/collections/{row['id']}").json() == {"deleted": True}
    assert client.get("/api/collections", params={"date": EMPTY_DAY.isoformat()}).json()["rows"] == []


def test_bad_handovers_are_refused(client):
    did = driver_id(client, "D-105")
    base = {"business_date": EMPTY_DAY.isoformat(), "driver_id": did, "expected_cash": 100, "cash_received": 100}
    assert client.put("/api/collections", json={**base, "cash_received": -5}).status_code == 422
    assert client.put("/api/collections", json={**base, "pos_amount": "abc"}).status_code == 422
    future = (date.today() + timedelta(days=2)).isoformat()
    assert client.put("/api/collections", json={**base, "business_date": future}).status_code == 422
    assert client.put("/api/collections", json={**base, "driver_id": 99999}).status_code == 404
    inactive = driver_id(client, "D-112")
    r = client.put("/api/collections", json={**base, "driver_id": inactive})
    assert r.status_code == 409 and "inactive" in r.json()["error"]["message"]


def csv_upload(text: str, name="day.csv"):
    return {"file": (name, text.encode(), "text/csv")}


def test_import_preview_flags_every_problem_and_saves_nothing(client):
    text = ("Driver ID,Orders,Expected Cash,Cash Received,POS Amount\n"
            "d-101,20,1000,1000,500\n"      # fine
            "D-102,18,SAR 900.00,850,0\n"    # fine, 50 short
            "D-999,10,100,100,0\n"           # unknown driver
            "D-112,10,100,100,0\n"           # inactive
            "D-103,x,100,abc,0\n"            # bad orders and amount
            "D-101,5,10,10,0\n")             # duplicate of row 2
    r = client.post("/api/collections/import", files=csv_upload(text), data={"business_date": EMPTY_DAY.isoformat()})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"] == {"new": 2, "update": 0, "same": 0, "error": 4} and out["saved"] == 0
    problems = {row["line"]: " | ".join(row["problems"]) for row in out["rows"]}
    assert "unknown driver D-999" in problems[4] and "inactive" in problems[5]
    assert "not a whole number" in problems[6] and "'abc' is not a number" in problems[6]
    assert "same driver and date as row 2" in problems[7]
    assert out["rows"][1]["difference"] == -50.0
    assert client.get("/api/collections", params={"date": EMPTY_DAY.isoformat()}).json()["rows"] == []


def test_import_commit_saves_good_rows_and_updates_existing_ones(client):
    day = EMPTY_DAY - timedelta(days=1)
    text = "Driver,Expected,Cash,POS\nD-106,700,700,100\nD-107,300,290,0\n"
    r = client.post("/api/collections/import", files=csv_upload(text), data={"business_date": day.isoformat(), "commit": "true"})
    assert r.json()["saved"] == 2 and r.json()["counts"]["new"] == 2
    text2 = "Driver,Expected,Cash,POS\nD-106,700,700,100\nD-107,300,300,0\n"
    r = client.post("/api/collections/import", files=csv_upload(text2), data={"business_date": day.isoformat()})
    assert r.json()["counts"] == {"new": 0, "update": 1, "same": 1, "error": 0}
    client.post("/api/collections/import", files=csv_upload(text2), data={"business_date": day.isoformat(), "commit": "true"})
    rows = client.get("/api/collections", params={"date": day.isoformat()}).json()["rows"]
    assert {r["driver_code"]: r["status"] for r in rows} == {"D-106": "ok", "D-107": "ok"}
    assert any("(import day.csv)" in a["summary"] for a in client.get("/api/audit").json())


def test_import_excel_with_its_own_date_column(client):
    df = pd.DataFrame({"Courier ID": ["D-108", "D-109"], "Date": ["01/08/2026", "2026-08-02"],
                       "System Cash": [1200, 450.5], "Cash Collected": [1200, 450.5], "Card": [0, 80]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r = client.post("/api/collections/import", files={"file": ("week.xlsx", buf.getvalue(), "application/octet-stream")},
                    data={"commit": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["dates"] == ["2026-08-01", "2026-08-02"] and r.json()["saved"] == 2  # 01/08 is read day-first


def test_import_explains_file_problems(client):
    def err(text, name="x.csv", data=None):
        data = {"business_date": EMPTY_DAY.isoformat()} if data is None else data
        r = client.post("/api/collections/import", files=csv_upload(text, name), data=data)
        assert r.status_code == 422
        return r.json()["error"]["message"]
    assert "Expected cash" in err("Driver ID,Cash Received\nD-101,5\n")
    assert "choose the business date" in err("Driver ID,Expected,Cash\nD-101,5,5\n", data={})
    assert ".csv or .xlsx" in err("a,b\n1,2\n", name="notes.txt")
    assert "not a real .xlsx" in err("hello", name="fake.xlsx")
    assert "no rows" in err("Driver ID,Expected,Cash\n")


def test_template_downloads(client):
    r = client.get("/api/collections/template")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "Driver ID,Driver name,Date" in r.text


def test_the_systems_order_report_becomes_one_handover_per_driver(client):
    """The delivery system's collection report has a line per order and charge. Collections adds the
    cash lines up per driver into the expected cash; POS lines are not cash."""
    d = "2026-05-06"
    text = ("Waybill Number,Charge Category,Payment Method,Collect Method,Actual Received Amount,DA Code,DA Name,Collection Operation Time\n"
            "WB-71,COD,Cash,Cash,100.00,D-101,Faisal,2026-05-06 21:10:00\n"
            "WB-71,Import VAT,Cash,Cash,5.00,D-101,Faisal,2026-05-06 21:10:00\n"        # same order, another charge
            "WB-72,COD,POS,POS,300.00,D-101,Faisal,2026-05-06 21:11:00\n"              # card: not cash
            "WB-73,COD,Cash,part pos and part cash,40.00,D-101,Faisal,2026-05-06 21:12:00\n"
            "WB-73,COD,POS,part pos and part cash,60.00,D-101,Faisal,2026-05-06 21:12:00\n"
            "WB-74,COD,Cash,Cash,250.50,D-102,Imran,2026-05-06 20:00:00\n"
            "WB-75,COD,Cash,Cash,10.00,X-404,Nobody,2026-05-06 20:00:00\n")
    r = client.post("/api/collections/import", files={"file": ("report.csv", text.encode(), "text/csv")}).json()
    rows = {x["driver_code"]: x for x in r["rows"]}
    assert rows["D-101"]["expected_cash"] == 145.0 and rows["D-101"]["orders"] == 3 and rows["D-101"]["system_pos"] == 360.0
    assert rows["D-101"]["cash_received"] == 145.0 and rows["D-101"]["status"] == "new"
    assert rows["D-102"]["expected_cash"] == 250.5 and rows["X-404"]["status"] == "error"
    client.post("/api/collections/import", files={"file": ("report.csv", text.encode(), "text/csv")}, data={"commit": "true"})
    day = client.get("/api/collections", params={"date": d}).json()
    h = next(x for x in day["rows"] if x["driver_code"] == "D-101")
    assert (h["expected_cash"], h["cash_received"], h["orders"]) == (145.0, 145.0, 3)

    # the desk records a shortage; importing a later report keeps the counted cash
    client.put("/api/collections", json={"business_date": d, "driver_id": h["driver_id"], "orders": 3,
                                         "expected_cash": 145, "cash_received": 140})
    later = text + "WB-76,COD,Cash,Cash,20.00,D-101,Faisal,2026-05-06 22:30:00\n"
    r = client.post("/api/collections/import", files={"file": ("r2.csv", later.encode(), "text/csv")}, data={"commit": "true"}).json()
    assert next(x for x in r["rows"] if x["driver_code"] == "D-101")["status"] == "update"
    h = next(x for x in client.get("/api/collections", params={"date": d}).json()["rows"] if x["driver_code"] == "D-101")
    assert (h["expected_cash"], h["cash_received"], h["difference"]) == (165.0, 140.0, -25.0)


def test_a_desk_that_closes_orders_only_when_paid(client):
    """Some desks close an order only when the driver has paid it in full, so cash received is always
    the system cash: the import and the form follow that, and the choice is logged."""
    assert client.get("/api/settings").json() == {"cash_mode": "count"}
    try:
        assert client.put("/api/settings", json={"cash_mode": "paid"}).json() == {"cash_mode": "paid"}
        assert client.put("/api/settings", json={"cash_mode": "nope"}).status_code == 422
        d = "2026-05-07"
        text = ("Waybill Number,Collect Method,Actual Received Amount,DA Code,Collection Operation Time\n"
                "PW-1,Cash,80.00,D-103,2026-05-07 20:00:00\nPW-2,POS,50.00,D-103,2026-05-07 20:01:00\n")
        r = client.post("/api/collections/import", files={"file": ("r.csv", text.encode(), "text/csv")}, data={"commit": "true"}).json()
        assert r["rows"][0]["problems"] == [] and r["saved"] == 1
        drv = driver_id(client, "D-103")
        client.put("/api/collections", json={"business_date": d, "driver_id": drv, "orders": 2, "expected_cash": 90, "cash_received": 10})
        h = next(x for x in client.get("/api/collections", params={"date": d}).json()["rows"] if x["driver_id"] == drv)
        assert (h["expected_cash"], h["cash_received"], h["status"]) == (90.0, 90.0, "ok")
        assert any("closed only when paid in full" in a["summary"] for a in client.get("/api/audit").json())
    finally:
        client.put("/api/settings", json={"cash_mode": "count"})


def test_the_demo_follows_paid_in_full_mode(client):
    """Started in demo mode, a database without a choice is set to paid-in-full and has no driver differences.
    (Run on a separate database, so the shared test data keeps its planted differences.)"""
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import AppSetting, Collection
    from app.seed import match_paid_mode, seed_demo
    from datetime import date as _d
    from app import stations
    eng = create_engine(f"sqlite:///{tempfile.mkdtemp()}/p.db")
    Base.metadata.create_all(eng)
    with sessionmaker(eng)() as db:
        stations.ensure_defaults(db)
        seed_demo(db, end=_d(2026, 10, 26))
        assert db.query(Collection).filter(Collection.cash_received != Collection.expected_cash).count() > 0
        assert match_paid_mode(db) > 0
        assert db.get(AppSetting, "cash_mode").value == "paid"
        assert db.query(Collection).filter(Collection.cash_received != Collection.expected_cash).count() == 0
