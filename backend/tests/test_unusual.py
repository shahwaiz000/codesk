"""Unusual amounts: learned from the desk's own history, with no false alarms on ordinary days."""
from datetime import date

from app import unusual
from app.database import SessionLocal
from app.seed import DAYS as DAY_COUNT, PLANTED, business_days
from tests.conftest import END

DAYS = business_days(END)


def did(client, code):
    return next(d["id"] for d in client.get("/api/drivers").json() if d["code"] == code)


def test_the_demo_month_has_exactly_the_planted_unusual_payment(client):
    with SessionLocal() as db:
        found = [a for a in unusual.find(db, DAYS[DAY_COUNT - 1], END) if a["kind"] != "unusual_pos"]
    pos_, code, cat, sar = PLANTED["unusual_expenses"][0]
    assert [(a["date"], a["driver_code"], a["amount"]) for a in found if a["kind"] == "unusual_expense"] == \
        [(DAYS[pos_].isoformat(), code, float(sar))]
    a = next(a for a in found if a["kind"] == "unusual_expense")
    assert a["ratio"] >= 3 and ("x the usual fuel payment" in a["text"] or "x his usual" in a["text"])
    assert not [a for a in found if a["kind"] == "unusual_payout"]  # ordinary days are not flagged


def test_a_drivers_own_usual_and_a_big_day(client):
    d, drv = date(2026, 3, 30), did(client, "D-109")
    for i, amount in enumerate((60, 70, 65)):  # his usual parking is about 65
        client.post("/api/expenses", json={"business_date": f"2026-03-0{i + 2}", "driver_id": drv, "category": "parking", "amount": amount})
    client.post("/api/expenses", json={"business_date": d.isoformat(), "driver_id": drv, "category": "parking", "amount": 300})
    client.post("/api/expenses", json={"business_date": d.isoformat(), "driver_id": drv, "category": "parking", "amount": 90})  # not 3x
    with SessionLocal() as db:
        found = unusual.find(db, d, d)
    exp = [a for a in found if a["kind"] == "unusual_expense"]
    assert len(exp) == 1 and exp[0]["amount"] == 300 and exp[0]["usual"] == 65 and "his usual" in exp[0]["text"]
    # marked as looked at: it no longer alarms, but the day still shows it with the note
    assert client.post("/api/unusual/review", json={"key": exp[0]["key"], "note": "two days of parking at the port"}).json() == {"reviewed": True}
    assert client.post("/api/unusual/review", json={"key": exp[0]["key"]}).status_code == 409
    with SessionLocal() as db:
        assert not [a for a in unusual.find(db, d, d) if a["key"] == exp[0]["key"]]
    day = client.get("/api/unusual", params={"date": d.isoformat()}).json()
    assert next(a for a in day if a["key"] == exp[0]["key"])["review"]["note"] == "two days of parking at the port"


def test_a_pos_machine_that_keeps_disagreeing(client):
    drv = did(client, "D-112")
    client.patch(f"/api/drivers/{drv}", json={"active": True})
    for i, (system, terminal) in enumerate(((100, 100), (200, 195), (150, 150), (300, 290), (120, 117))):
        d = f"2026-02-{i + 2:02d}"
        client.post("/api/pos/import/orders", files={"file": ("o.csv", f"Order no,Driver ID,Amount\nPR{i}-X,D-112,{system}\n".encode(), "text/csv")},
                    data={"business_date": d, "commit": "true"})
        client.put("/api/collections", json={"business_date": d, "driver_id": drv, "expected_cash": 0, "cash_received": 0, "pos_amount": terminal})
    with SessionLocal() as db:
        found = [a for a in unusual.find(db, date(2026, 2, 6), date(2026, 2, 6)) if a["kind"] == "unusual_pos"]
    assert len(found) == 1 and found[0]["driver_code"] == "D-112" and "3 of his last 5 days" in found[0]["text"]
    assert found[0]["amount"] == -18.0
    client.patch(f"/api/drivers/{drv}", json={"active": False})  # as the demo data has him


def test_the_dashboard_lists_unusual_amounts(client):
    alerts = client.get("/api/dashboard", params={"date": END.isoformat()}).json()
    assert "unusual_expense" in alerts["alert_kinds"]
