"""Deposit slips read by the local AI: CODesk checks what was read and a person records it."""
import io
from datetime import date

import pytest
from PIL import Image

from app import slip_reader
from app.database import SessionLocal

DAY = date(2026, 4, 14)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1600, 2200), "white").save(buf, "PNG")
    return buf.getvalue()


def _slip(total=1000, words="one thousand", lines=((500, 1, 500), (100, 5, 500)), when="15-Apr-2026"):
    return {"bank": "Coastal National Bank", "date": when, "slip_number": "CN-4471", "total": total,
            "amount_in_words": words, "denominations": [{"note": n, "count": c, "amount": a} for n, c, a in lines]}


@pytest.fixture()
def day_with_cash(client):
    drv = next(d["id"] for d in client.get("/api/drivers").json() if d["code"] == "D-110")
    client.put("/api/collections", json={"business_date": DAY.isoformat(), "driver_id": drv, "expected_cash": "998.40", "cash_received": "998.40"})
    return DAY


def test_words_to_number():
    assert slip_reader.words_to_number("Seven thousand nine hundred twenty five") == 7925
    assert slip_reader.words_to_number("Thirteen thousand eight hundred twenty") == 13820
    assert slip_reader.words_to_number("one hundred and five riyals only") == 105
    assert slip_reader.words_to_number("") is None


def test_a_slip_is_read_checked_and_recorded(client, monkeypatch, day_with_cash):
    monkeypatch.setattr(slip_reader, "ask_model", lambda png: _slip())
    r = client.post("/api/slips/read", files={"file": ("slip.png", _png(), "image/png")}).json()
    assert r["status"] == "draft" and r["total"] == 1000 and r["has_image"]
    assert all(c["ok"] for c in r["checks"]), r["checks"]
    assert r["business_date"] == DAY.isoformat() and r["deposit_date"] == "2026-04-15"  # 998.40 rounded up to 1,000
    assert client.get(f"/api/slips/{r['id']}/image").headers["content-type"] == "image/png"
    assert any(s["id"] == r["id"] for s in client.get("/api/slips").json())
    row = client.post(f"/api/slips/{r['id']}/record", json={"business_date": r["business_date"], "deposit_date": r["deposit_date"],
                                                           "bank": r["bank"], "slip_ref": r["slip_number"], "amount": r["total"]}).json()
    assert row["status"] == "deposited" and row["rounding"] == 1.6
    assert not any(s["id"] == r["id"] for s in client.get("/api/slips").json())  # no longer waiting


def test_misread_or_wrong_slips_are_flagged(client, monkeypatch, day_with_cash):
    # a line whose count does not match its amount, and lines that do not add up to the total
    monkeypatch.setattr(slip_reader, "ask_model", lambda png: _slip(lines=((500, 1, 500), (200, 6, 500))))
    r = client.post("/api/slips/read", files={"file": ("bad.png", _png(), "image/png")}).json()
    texts = [c["text"] for c in r["checks"] if not c["ok"]]
    assert any("200 x 6 = 1,200.00" in t for t in texts) and any("add up to 1,700.00" in t for t in texts)
    # the words disagree with the total, and no day has this amount
    monkeypatch.setattr(slip_reader, "ask_model", lambda png: _slip(total=4000, words="four thousand five hundred",
                                                                     lines=((500, 8, 4000),)))
    r = client.post("/api/slips/read", files={"file": ("other.png", _png(), "image/png")}).json()
    texts = [c["text"] for c in r["checks"] if not c["ok"]]
    assert any("in words says 4,500" in t for t in texts) and any("No day still to deposit" in t for t in texts)
    assert r["business_date"] is None
    assert client.post(f"/api/slips/{r['id']}/dismiss").json() == {"dismissed": True}


def test_without_the_ai_the_slip_waits_with_a_reason(client, monkeypatch):
    def offline(png):
        raise slip_reader.SlipProblem("The AI is not running. Start Ollama, then read the slip again")
    monkeypatch.setattr(slip_reader, "ask_model", offline)
    r = client.post("/api/slips/read", files={"file": ("slip.png", _png(), "image/png")}).json()
    assert r["status"] == "failed" and "Ollama" in r["error"]
    assert client.post("/api/slips/read", files={"file": ("slip.txt", b"x", "text/plain")}).status_code == 422
    assert client.get("/api/slips/ai").json()["ready"] is False  # no Ollama in the test environment


def test_a_pdf_slip_becomes_a_picture():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "Deposit slip")
    png = slip_reader.to_image("scan.pdf", doc.tobytes())
    w, h = Image.open(io.BytesIO(png)).size
    assert max(w, h) <= slip_reader.MAX_SIDE and h > w


def test_the_watch_folder_reads_slips(client, monkeypatch, tmp_path):
    from app import watcher
    monkeypatch.setattr(slip_reader, "ask_model", lambda png: _slip(total=500, words="five hundred", lines=((500, 1, 500),)))
    client.put("/api/watch", json={"folder": str(tmp_path)})
    (tmp_path / "SAB slip.jpg").write_bytes(_png())
    with SessionLocal() as db:
        done = watcher.scan(db, wait=False)
    assert done[0]["kind"] == "slip" and "read 500.00" in done[0]["summary"] and "Bank deposits" in done[0]["summary"]
    client.put("/api/watch", json={"folder": ""})
