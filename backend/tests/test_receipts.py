"""Card machine receipts: read by the AI from photos, checked, and saved as the day's card machine sheet."""
import io

from PIL import Image

from app import receipts
from app.config import settings

DAY = "2026-10-21"


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, "PNG")
    return buf.getvalue()


def test_what_the_ai_read_is_checked():
    from datetime import date
    r = receipts.check_receipt({"terminal_id": "64814768", "date": "2026-10-30", "count": 2, "total": "437.91",
                                "lines": [172.91, 265.0]}, date(2026, 10, 30))
    assert r["terminal"] == "64814768" and r["total"] == 437.91 and all(c["ok"] for c in r["checks"])
    bad = receipts.check_receipt({"terminal_id": "648", "date": "2026-10-29", "count": 3, "total": 500, "lines": [100, 200]}, date(2026, 10, 30))
    texts = [c["text"] for c in bad["checks"] if not c["ok"]]
    assert any("terminal ID" in t for t in texts) and any("add up to 300.00" in t for t in texts)
    assert any("3 payments" in t for t in texts) and any("not 30 Oct" in t for t in texts)


def test_photos_are_read_and_the_totals_saved_as_the_card_sheet(client, monkeypatch):
    monkeypatch.setattr(receipts.ai, "status", lambda db: {"ready": True, "engine": "gemini", "reason": ""})
    monkeypatch.setattr(receipts, "read_photo", lambda db, png: [
        {"terminal_id": "64810001", "date": DAY, "count": 2, "total": 300.5, "lines": [100, 200.5]},
        {"terminal_id": "64810002", "date": DAY, "count": 1, "total": 99, "lines": [99]}])
    r = client.post("/api/receipts/read", data={"business_date": DAY},
                    files=[("files", ("a.png", _png(), "image/png"))]).json()
    assert r["ai"] and len(r["photos"][0]["receipts"]) == 2 and r["photos"][0]["receipts"][0]["total"] == 300.5
    rows = [{"terminal": x["terminal"], "amount": x["total"]} for x in r["photos"][0]["receipts"]]
    s = client.post("/api/receipts/save", json={"date": DAY, "rows": rows}).json()
    assert s == {"saved": 2, "machines": 2, "total": 399.5}
    again = client.post("/api/receipts/save", json={"date": DAY, "rows": [{"terminal": "64810001", "amount": 310}]}).json()
    assert again["saved"] == 1  # the machine is updated, not doubled
    pos = client.get("/api/pos", params={"date": DAY}).json()
    assert pos["totals"]["sheet"] and pos["totals"]["machines_total"] == 409.0
    assert client.post("/api/receipts/save", json={"date": DAY, "rows": rows + rows[:1]}).status_code == 422  # same machine twice


def test_without_the_ai_the_photos_come_back_to_type_from(client):
    r = client.post("/api/receipts/read", data={"business_date": DAY}, files=[("files", ("a.png", _png(), "image/png"))]).json()
    assert r["ai"] is False and r["photos"][0]["receipts"] == [] and r["reason"]


def test_demo_receipts_only_in_demo_mode(client, monkeypatch):
    assert client.get("/api/receipts/demo", params={"date": DAY}).status_code == 404
    monkeypatch.setattr(settings, "seed_demo_data", True)
    parts = client.get("/api/receipts/demo/parts", params={"date": "2026-10-26"}).json()["parts"]
    assert parts >= 1
    img = client.get("/api/receipts/demo", params={"date": "2026-10-26", "part": 1})
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
