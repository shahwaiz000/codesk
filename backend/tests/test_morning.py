"""The morning summary: the last business day on one page, prepared by itself at the chosen time."""
from datetime import datetime, timedelta

from app import morning
from app.database import SessionLocal
from app.seed import next_working_day
from tests.conftest import END


def test_the_summary_reads_the_last_business_day(client):
    today = next_working_day(END)
    s = client.get("/api/morning", params={"date": today.isoformat()}).json()
    assert s["day"] == END.isoformat()
    labels = [x["label"] for x in s["lines"]]
    assert labels[0] == "Cash collected" and "POS" in labels and "To the bank" in labels
    assert s["text"].startswith("CODesk morning summary") and "Needs attention:" in s["text"]
    assert any("due today" in x["note"] for x in s["lines"] if x["label"] == "To the bank")  # the latest day is not deposited yet
    pdf = client.get("/api/morning/pdf", params={"date": today.isoformat()})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"


def test_it_is_prepared_once_at_the_chosen_time(client, tmp_path):
    client.put("/api/watch", json={"folder": str(tmp_path)})
    assert client.put("/api/morning/settings", json={"time": "8:5"}).status_code == 422
    assert client.put("/api/morning/settings", json={"time": "08:30"}).json() == {"time": "08:30"}
    thursday = datetime(2026, 10, 29, 8, 29)
    with SessionLocal() as db:
        assert morning.maybe_run(db, thursday) is None                    # not yet
        folder = morning.maybe_run(db, thursday + timedelta(minutes=1))  # 08:30
        assert folder == tmp_path / "Morning summaries"
        assert (folder / "Morning summary 2026-10-29.pdf").exists() and (folder / "Morning summary 2026-10-29.txt").exists()
        assert morning.maybe_run(db, thursday + timedelta(hours=2)) is None  # only once a day
        assert morning.maybe_run(db, datetime(2026, 10, 30, 9, 0)) is None  # Friday is the day off
    client.put("/api/morning/settings", json={"time": ""})
    client.put("/api/watch", json={"folder": ""})
