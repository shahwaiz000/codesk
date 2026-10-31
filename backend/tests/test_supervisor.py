"""The cashier supervisor's tools: sign-off, follow-ups, the message to a cashier, and the scorecard."""
from datetime import date

END = date(2026, 10, 26)  # the latest day of the test data (see conftest)


def jed(client):
    return next(s for s in client.get("/api/stations").json()["stations"] if s["code"] == "JED")


def test_cashier_details_are_kept_on_the_station(client):
    s = jed(client)
    r = client.put(f"/api/stations/{s['id']}", json={**{k: s[k] for k in ("code", "name", "city", "region", "active")},
                   "cashier_name": "Ahmed Saleh", "cashier_phone": "050 123 4567", "cashier_email": "cashier.jed@example.com",
                   "cash_limit": 50000}).json()
    assert r["cashier_name"] == "Ahmed Saleh" and r["cashier_phone"] == "0501234567" and r["cash_limit"] == 50000


def test_a_day_is_signed_off_and_shows_on_the_overview(client):
    s, day = jed(client), END.isoformat()
    h = {"X-Station": str(s["id"])}
    assert client.get("/api/supervisor/check", params={"date": day}, headers=h).json()["check"] is None
    r = client.post("/api/supervisor/check", json={"date": day, "note": "all files fine"}, headers=h).json()
    assert r["check"]["checked_by"] and r["check"]["note"] == "all files fine"
    ov = {x["code"]: x for x in client.get("/api/stations/overview", params={"date": day}).json()["stations"]}
    assert ov["JED"]["check"]["note"] == "all files fine"
    assert client.delete("/api/supervisor/check", params={"date": day}, headers=h).json()["check"] is None
    assert client.post("/api/supervisor/check", json={"date": day}).status_code == 422  # all stations: choose one first


def test_a_follow_up_is_raised_noted_messaged_and_closed(client):
    s = jed(client)
    h = {"X-Station": str(s["id"])}
    f = client.post("/api/supervisor/follow-ups", headers=h, json={"date": "2026-10-15", "kind": "deposit_short",
                    "title": "Deposit 500 short", "amount": 500, "note": "seen on the overview"}).json()
    assert f["status"] == "open" and f["amount"] == 500 and f["notes"][0]["text"] == "seen on the overview"
    f = client.post(f"/api/supervisor/follow-ups/{f['id']}/notes", json={"text": "called, deposits tomorrow"}).json()
    assert len(f["notes"]) == 2
    m = client.post(f"/api/supervisor/follow-ups/{f['id']}/message", json={"lang": "en"}).json()
    assert "Dear Ahmed Saleh" in m["text"] and "500.00 SAR short" in m["text"] and "15 Oct 2026" in m["text"]
    assert m["phone"] == "966501234567" and m["by"] == "template"
    ar = client.post(f"/api/supervisor/follow-ups/{f['id']}/message", json={"lang": "ar"}).json()
    assert "ريال" in ar["text"]
    assert client.post(f"/api/supervisor/follow-ups/{f['id']}/message", json={"polish": True}).status_code == 422  # no AI in the tests
    listed = client.get("/api/supervisor/follow-ups", headers=h).json()
    assert listed["open"] >= 1 and any(x["id"] == f["id"] for x in listed["rows"])
    f = client.post(f"/api/supervisor/follow-ups/{f['id']}/close", json={"note": "slip received"}).json()
    assert f["status"] == "closed" and f["notes"][-1]["text"] == "slip received"
    assert client.post(f"/api/supervisor/follow-ups/{f['id']}/reopen").json()["status"] == "open"


def test_the_scorecard_grades_each_cashier(client):
    month = END.strftime("%Y-%m")
    rows = {r["station_code"]: r for r in client.get("/api/supervisor/scorecard", params={"month": month}).json()["rows"]}
    j = rows["JED"]
    assert j["cashier_name"] == "Ahmed Saleh" and j["days"] > 0 and j["short_days"] >= 0
    assert j["score"] is None or 0 <= j["score"] <= 100
    assert j["on_time"] + j["short_days"] + j["late_days"] <= j["days"]


def test_the_month_end_report_is_a_pdf(client):
    month = END.strftime("%Y-%m")
    r = client.get("/api/supervisor/month-report", params={"month": month})
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "codesk-month-" in r.headers["content-disposition"]
    one = client.get("/api/supervisor/month-report", params={"month": month, "station": jed(client)["id"]})
    assert one.status_code == 200 and "-JED.pdf" in one.headers["content-disposition"]
    import fitz
    text = "".join(p.get_text() for p in fitz.open(stream=one.content, filetype="pdf"))
    assert "Month-end report: Jeddah" in text and "Day by day" in text and "Ahmed Saleh" in text


def test_the_daily_supervisor_report_is_a_pdf(client):
    import fitz
    s = jed(client)
    client.post("/api/supervisor/check", json={"date": END.isoformat(), "station_id": s["id"], "note": "ok"})
    r = client.get("/api/supervisor/day-report", params={"date": END.isoformat()})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    text = "".join(p.get_text() for p in fitz.open(stream=r.content, filetype="pdf"))
    assert "Daily supervisor report: all stations" in text and "Jeddah" in text and "Ahmed Saleh" in text
    assert "stations checked" in text and "Follow-ups still open" in text and "Signature" in text
    one = client.get("/api/supervisor/day-report", params={"date": END.isoformat(), "station": s["id"]})
    assert "-JED.pdf" in one.headers["content-disposition"]
