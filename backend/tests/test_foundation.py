"""Stage 1: money handling, the fictional data, drivers and the activity log."""
from datetime import date

import pytest

from app.database import SessionLocal
from app.models import AuditEvent, Collection, Deposit, Driver, Expense
from app.money import to_halalas, to_sar
from app.seed import DAYS, DRIVERS, PLANTED, business_days, default_end_date, next_working_day
from tests.conftest import END


@pytest.mark.parametrize("raw, halalas", [
    ("1,234.50", 123450), ("SAR 99", 9900), ("(500.00)", -50000), (12.5, 1250), (7, 700),
    ("0.1", 10), ("  ", None), ("abc", None), (None, None), ("12.345", 1235), ("ر.س 20", 2000),
])
def test_amounts_are_read_into_exact_halalas(raw, halalas):
    assert to_halalas(raw) == halalas


def test_halalas_do_not_drift_like_floats():
    assert sum(to_halalas("0.10") for _ in range(10)) == 100  # exactly 1.00 SAR
    assert to_sar(123456) == 1234.56 and to_sar(None) is None


def test_working_days_skip_friday():
    assert date(2026, 10, 23).weekday() == 4  # a Friday
    assert next_working_day(date(2026, 10, 22)) == date(2026, 10, 24)
    days = business_days(END)
    assert len(days) == DAYS and days[0] == END and all(d.weekday() != 4 for d in days)
    assert default_end_date(date(2026, 10, 24)) == date(2026, 10, 22)  # yesterday was Friday, so Thursday


def test_demo_data_has_exactly_the_planted_mistakes(client):
    days = business_days(END)
    with SessionLocal() as db:
        seeded = db.query(Driver).filter(Driver.code.in_([c for c, _, _ in DRIVERS])).all()
        assert len(seeded) == 12 and sum(not d.active for d in seeded) == 1
        demo = db.query(Collection).filter(Collection.business_date.in_(days), Collection.created_by == "demo").all()
        assert len(demo) == 11 * DAYS
        diffs = sorted((days.index(c.business_date), c.driver.code, (c.cash_received - c.expected_cash) // 100)
                       for c in demo if c.cash_received != c.expected_cash)
        assert diffs == sorted(PLANTED["cash_differences"])
        open_adv = db.query(Expense).filter(Expense.category == "advance", Expense.settled_on.is_(None)).all()
        assert sorted(e.driver.code for e in open_adv) == ["D-108", "D-111"]

        def owed(pos):
            day = days[pos]
            cash = sum(c.cash_received for c in db.query(Collection).filter_by(business_date=day, created_by="demo"))
            spent = sum(e.amount for e in db.query(Expense).filter_by(business_date=day))
            paid = sum(d.amount for d in db.query(Deposit).filter_by(business_date=day))
            return cash - spent - paid

        unpaid = {pos: owed(pos) for pos in range(DAYS) if owed(pos)}
        assert set(unpaid) == {PLANTED["undeposited"], PLANTED["short_deposit"][0]}
        assert unpaid[PLANTED["short_deposit"][0]] == PLANTED["short_deposit"][1] * 100
        late = [d for d in db.query(Deposit) if d.deposit_date > next_working_day(d.business_date)]
        assert {days.index(d.business_date) for d in late} == {PLANTED["late_deposit"][0]}
        assert db.query(Deposit).filter_by(business_date=days[PLANTED["split_deposit"]]).count() == 2


def test_driver_list_shows_shortages_and_open_advances(client):
    rows = {d["code"]: d for d in client.get("/api/drivers").json()}
    assert rows["D-109"]["cash_shortage"] == 300.0 and rows["D-110"]["cash_shortage"] == 0.0  # an excess is not a shortage
    assert rows["D-111"]["open_advances"] == 800.0 and rows["D-111"]["open_advance_count"] == 1
    assert rows["D-102"]["open_advances"] == 0.0  # that advance was settled
    assert rows["D-101"]["last_collection"] == END.isoformat() and rows["D-112"]["active"] is False
    assert list(rows)[-1] == "D-112"  # inactive drivers are listed last


def test_add_edit_and_deactivate_a_driver(client):
    r = client.post("/api/drivers", json={"code": " d-201 ", "name": "  Test   Driver ", "hub": "North Hub"})
    assert r.status_code == 201 and r.json()["code"] == "D-201" and r.json()["name"] == "Test Driver"
    did = r.json()["id"]
    assert client.post("/api/drivers", json={"code": "D-201", "name": "Someone Else"}).status_code == 409
    assert client.post("/api/drivers", json={"code": "D 2!", "name": "Bad Code"}).status_code == 422
    r = client.patch(f"/api/drivers/{did}", json={"active": False, "phone": "0500000000"})
    assert r.json()["active"] is False and r.json()["phone"] == "0500000000"
    assert client.patch("/api/drivers/99999", json={"active": False}).status_code == 404
    assert client.delete(f"/api/drivers/{did}").json() == {"deleted": True}
    summaries = [a["summary"] for a in client.get("/api/audit").json()]
    assert summaries[0].startswith("Deleted driver D-201") and any("active: True -> False" in s for s in summaries)


def test_a_driver_with_history_cannot_be_deleted(client):
    d101 = next(d for d in client.get("/api/drivers").json() if d["code"] == "D-101")
    r = client.delete(f"/api/drivers/{d101['id']}")
    assert r.status_code == 409 and "inactive" in r.json()["error"]["message"]


def test_audit_entries_cannot_be_changed(client):
    with SessionLocal() as db:
        entry = db.query(AuditEvent).first()
        entry.summary = "rewritten"
        with pytest.raises(ValueError):
            db.commit()


def test_meta_reports_the_data_range(client):
    m = client.get("/api/meta").json()
    assert m["latest_business_date"] == END.isoformat() and m["currency"] == "SAR"
    assert m["first_business_date"] <= business_days(END)[-1].isoformat()  # other tests add older days
