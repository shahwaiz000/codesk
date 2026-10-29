"""Stage 4: expenses, advances and bank deposits."""
from datetime import date, timedelta

import pytest

from app.deposits import status_for
from app.seed import PLANTED, business_days, next_working_day
from tests.conftest import END

DAYS = business_days(END)
FREE_DAY = date(2026, 6, 2)  # a Tuesday with no other test data


def did(client, code):
    return next(d["id"] for d in client.get("/api/drivers").json() if d["code"] == code)


def ledger_row(client, day: date):
    rows = client.get("/api/deposits", params={"end": END.isoformat(), "count": 120}).json()["rows"]
    return next((r for r in rows if r["date"] == day.isoformat()), None)


@pytest.mark.parametrize("today_shift, deposited, expected", [
    (0, 0, "not_due"),       # collected today, deposit is due tomorrow
    (1, 0, "due_today"),
    (2, 0, "overdue"),
    (2, 50, "short"),
    (2, 100, "deposited"),
    (2, 120, "over"),
])
def test_deposit_status_rules(today_shift, deposited, expected):
    day = date(2026, 10, 25)  # Sunday, so the deposit day is Monday
    today = day + timedelta(days=today_shift)
    assert status_for(day, 100, deposited, today) == expected
    assert status_for(day, 0, 0, today) == "nothing"


def test_friday_moves_the_deposit_day():
    assert next_working_day(date(2026, 10, 22)) == date(2026, 10, 24)  # Thursday's cash goes in on Saturday


def test_demo_ledger_finds_the_planted_deposit_problems(client):
    rows = {r["date"]: r for r in client.get("/api/deposits", params={"end": END.isoformat(), "count": 30}).json()["rows"]}
    short_pos, short_sar = PLANTED["short_deposit"]
    short = rows[DAYS[short_pos].isoformat()]
    assert short["status"] == "short" and short["pending"] == short_sar
    assert short["to_deposit"] == round(short["cash_received"] - short["paid_out"] + short["returned"], 2)
    late = rows[DAYS[PLANTED["late_deposit"][0]].isoformat()]
    assert late["status"] == "deposited" and late["late"] and late["days_late"] >= 2
    split = rows[DAYS[PLANTED["split_deposit"]].isoformat()]
    assert len(split["slips"]) == 2 and split["pending"] == 0 and split["status"] == "deposited"
    latest = rows[DAYS[0].isoformat()]
    assert latest["deposited"] == 0 and latest["pending"] == latest["to_deposit"] > 0
    assert latest["status"] in ("not_due", "due_today", "overdue")  # depends on the real date the tests run
    demo = [rows[d.isoformat()] for d in DAYS]
    assert sum(r["late"] for r in demo) == 1
    assert {r["status"] for r in demo[1:]} <= {"deposited", "short"}


def test_record_a_deposit_with_two_slips(client):
    driver = did(client, "D-101")
    client.put("/api/collections", json={"business_date": FREE_DAY.isoformat(), "driver_id": driver,
                                         "expected_cash": 1000, "cash_received": 1000})
    client.post("/api/expenses", json={"business_date": FREE_DAY.isoformat(), "driver_id": driver, "category": "fuel", "amount": "80.50"})
    row = ledger_row(client, FREE_DAY)
    assert row["to_deposit"] == 919.5 and row["status"] == "overdue"
    slip = {"business_date": FREE_DAY.isoformat(), "deposit_date": (FREE_DAY + timedelta(days=1)).isoformat(),
            "bank": "Coastal  National Bank", "slip_ref": "ds-test-1", "amount": 500}
    r = client.post("/api/deposits", json=slip)
    assert r.status_code == 201 and r.json()["status"] == "short" and r.json()["pending"] == 419.5
    assert client.post("/api/deposits", json=slip).status_code == 409  # same slip twice
    too_much = client.post("/api/deposits", json={**slip, "slip_ref": "DS-TEST-2", "amount": 420})
    assert too_much.status_code == 422 and "419.50" in too_much.json()["error"]["message"]
    early = client.post("/api/deposits", json={**slip, "slip_ref": "DS-TEST-3", "deposit_date": "2026-06-01"})
    assert early.status_code == 422
    r = client.post("/api/deposits", json={**slip, "slip_ref": "DS-TEST-2", "amount": "419.50"}).json()
    assert r["status"] == "deposited" and not r["late"] and [s["slip_ref"] for s in r["slips"]] == ["DS-TEST-1", "DS-TEST-2"]
    assert client.delete(f"/api/deposits/{r['slips'][1]['id']}").json() == {"deleted": True}
    assert ledger_row(client, FREE_DAY)["status"] == "short"
    assert "Deleted slip DS-TEST-2" in client.get("/api/audit").json()[0]["summary"]


def test_expenses_for_a_day(client):
    day = client.get("/api/expenses", params={"date": DAYS[PLANTED["advances"][3][0]].isoformat()}).json()
    adv = [e for e in day["rows"] if e["category"] == "advance"]
    assert len(adv) == 1 and adv[0]["driver_code"] == "D-111" and adv[0]["amount"] == 800.0 and adv[0]["settled_on"] is None
    t = day["totals"]
    assert t["advances"] == 800.0 and t["total"] == round(t["expenses"] + t["advances"], 2)
    assert day["rows"][-1]["category"] == "advance"  # advances listed after expenses


def test_add_edit_and_delete_an_expense(client):
    d = FREE_DAY - timedelta(days=7)
    body = {"business_date": d.isoformat(), "driver_id": did(client, "D-103"), "category": "toll", "amount": "25", "reference": "RC-1"}
    e = client.post("/api/expenses", json=body).json()
    assert e["amount"] == 25.0 and e["category_text"] == "Toll"
    e = client.put(f"/api/expenses/{e['id']}", json={**body, "amount": "30"}).json()
    assert e["amount"] == 30.0
    assert "toll 25.00 for D-103" in client.get("/api/audit").json()[0]["summary"]
    for bad in ({"amount": 0}, {"amount": "x"}, {"category": "lunch"}, {"business_date": "2099-01-01"}):
        assert client.post("/api/expenses", json={**body, **bad}).status_code == 422
    assert client.post("/api/expenses", json={**body, "driver_id": did(client, "D-112")}).status_code == 409  # inactive
    assert client.delete(f"/api/expenses/{e['id']}").json() == {"deleted": True}


def test_advance_returned_in_cash_goes_into_the_deposit(client):
    given, back = FREE_DAY - timedelta(days=14), FREE_DAY - timedelta(days=12)
    driver = did(client, "D-104")
    for d in (given, back):
        client.put("/api/collections", json={"business_date": d.isoformat(), "driver_id": driver, "expected_cash": 2000, "cash_received": 2000})
    adv = client.post("/api/expenses", json={"business_date": given.isoformat(), "driver_id": driver, "category": "advance", "amount": 600}).json()
    assert ledger_row(client, given)["to_deposit"] == 1400.0
    opened = client.get("/api/advances").json()
    assert any(a["id"] == adv["id"] for a in opened["rows"])
    assert client.post(f"/api/advances/{adv['id']}/settle", json={"settled_on": (given - timedelta(days=1)).isoformat(), "method": "cash"}).status_code == 422
    r = client.post(f"/api/advances/{adv['id']}/settle", json={"settled_on": back.isoformat(), "method": "cash", "note": "returned"})
    assert r.json()["settlement_method"] == "cash"
    row = ledger_row(client, back)
    assert row["returned"] == 600.0 and row["to_deposit"] == 2600.0
    assert client.delete(f"/api/expenses/{adv['id']}").status_code == 409  # recovered advances are protected
    assert client.post(f"/api/advances/{adv['id']}/settle", json={"settled_on": back.isoformat(), "method": "cash"}).status_code == 409
    assert client.post(f"/api/advances/{adv['id']}/reopen").json()["settled_on"] is None
    assert ledger_row(client, back)["to_deposit"] == 2000.0
    r = client.post(f"/api/advances/{adv['id']}/settle", json={"settled_on": back.isoformat(), "method": "salary"})
    assert r.json()["settlement_method"] == "salary" and ledger_row(client, back)["to_deposit"] == 2000.0


def test_open_advances_in_the_demo_data(client):
    data = client.get("/api/advances").json()
    demo = [a for a in data["rows"] if a["created_by"] == "demo"]
    assert sorted((a["driver_code"], a["amount"]) for a in demo) == [("D-108", 300.0), ("D-111", 800.0)]
    assert all(a["days_open"] > 0 for a in demo)
    everything = client.get("/api/advances", params={"status": "all"}).json()["rows"]
    assert {a["driver_code"] for a in everything if a["settled_on"] and a["created_by"] == "demo"} == {"D-102", "D-106"}


def test_expense_sheet_import(client):
    """The desk's own expense sheet: date, driver ID, name, amount, even without a heading row.
    A driver who is not in CODesk yet is added; importing the same sheet again pays nothing twice."""
    d = "2026-05-12"
    text = ("12-May-26,D-101,Faisal Al-Harbi,151.00\n"
            "12-May-26,X-901,New Expense Driver,57.00\n"    # not in CODesk yet: added on save
            "12-May-26,D-102,Imran Qureshi,abc\n"           # bad amount
            "12-May-26,,Nobody,10\n"                         # no driver ID
            ",,Total,208.00\n")                              # the sheet's total line is skipped
    up = lambda: {"file": ("expenses.csv", text.encode(), "text/csv")}  # noqa: E731
    r = client.post("/api/expenses/import", files=up()).json()
    assert r["counts"]["new"] == 2 and r["counts"]["error"] == 2 and r["counts"]["skipped"] == 1 and r["dates"] == [d]
    assert r["rows"][0]["line"] == 1 and r["rows"][0]["category"] == "other"
    assert "new driver" in r["rows"][1]["problems"][0]
    assert client.post("/api/expenses/import", files=up(), data={"commit": "true"}).json()["saved"] == 2
    day = client.get("/api/expenses", params={"date": d}).json()
    assert day["totals"]["total"] == 208.0
    assert any(x["code"] == "X-901" for x in client.get("/api/drivers").json())
    again = client.post("/api/expenses/import", files=up()).json()
    assert again["counts"]["same"] == 2 and again["counts"]["new"] == 0
    # with a heading row and a category column
    text2 = "Date,Driver ID,Driver name,Amount,Type\n12-May-26,D-103,Yousef Al-Amri,40,Petrol\n12-May-26,D-103,Yousef Al-Amri,25,Lunch\n12-May-26,D-104,Bilal Ahmed,900,Final settlement\n12-May-26,D-104,Bilal Ahmed,150,Incentive\n"
    r = client.post("/api/expenses/import", files={"file": ("e2.csv", text2.encode(), "text/csv")}).json()
    assert [x["category"] for x in r["rows"]] == ["fuel", "other", "settlement", "incentive"] and "saved as Other" in r["rows"][1]["problems"][0]
