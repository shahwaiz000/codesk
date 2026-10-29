"""The watch folder: files saved in one folder are recognised by their columns and imported by themselves."""
import io

import openpyxl

from app import watcher
from app.database import SessionLocal

DAY = "2026-04-07"


def _report() -> bytes:
    return ("Waybill Number,Charge Category,Payment Method,Collect Method,Actual Received Amount,DA Code,DA Name,Collection Operation Time\n"
            f"WF-1,COD,Cash,Cash,100.00,D-101,Faisal Al-Harbi,{DAY} 20:00:00\n"
            f"WF-2,COD,POS,POS,250.00,D-101,Faisal Al-Harbi,{DAY} 20:05:00\n"
            f"WF-3,COD,POS,POS,80.00,W-777,Watch Folder Driver,{DAY} 21:00:00\n").encode()


def _terminal_sheet() -> bytes:
    from datetime import date
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Total POS COD", 330])
    ws.append(["POS Code", date(2026, 4, 7)])
    ws.append([64900001, 250])
    ws.append([64900002, 80])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_files_in_the_watch_folder_are_imported_by_themselves(client, tmp_path):
    inbox = tmp_path / "CODesk inbox"
    r = client.put("/api/watch", json={"folder": str(inbox)})
    assert r.status_code == 404  # it does not exist yet
    r = client.put("/api/watch", json={"folder": str(inbox), "create": True}).json()
    assert r["exists"] and r["folder"] == str(inbox)
    assert client.put("/api/watch", json={"folder": "relative/path"}).status_code == 422

    (inbox / "collection report.csv").write_bytes(_report())
    (inbox / "POS 7 Apr.xlsx").write_bytes(_terminal_sheet())
    (inbox / "expenses.csv").write_text(f"07-Apr-26,D-101,Faisal Al-Harbi,40.00\n")
    (inbox / "notes.csv").write_text("hello,world\n1,2\n")
    (inbox / "pos export.csv").write_text("Order no,Driver ID,Amount,Payment method\nWF-9,D-102,60,POS\n")
    (inbox / "~$open in excel.xlsx").write_bytes(b"lock")

    with SessionLocal() as db:
        assert watcher.scan(db) == []  # first look: files must hold still before they are read
        done = {f["filename"]: f for f in watcher.scan(db)}
    assert set(done) == {"collection report.csv", "POS 7 Apr.xlsx", "expenses.csv", "notes.csv", "pos export.csv"}
    assert done["pos export.csv"]["kind"] == "orders" and done["pos export.csv"]["status"] == "failed"  # no date: needs the day
    assert done["collection report.csv"]["kind"] == "report" and done["collection report.csv"]["status"] == "done"
    assert done["POS 7 Apr.xlsx"]["kind"] == "terminals" and done["expenses.csv"]["kind"] == "expenses"
    assert done["notes.csv"]["status"] == "failed"
    assert sorted(p.name for p in (inbox / "Imported").iterdir()) == ["POS 7 Apr.xlsx", "collection report.csv", "expenses.csv"]
    assert sorted(p.name for p in (inbox / "Problems").iterdir()) == ["notes.csv", "pos export.csv"]
    assert (inbox / "~$open in excel.xlsx").exists()  # Excel's lock file is left alone

    # everything arrived: the new driver, the handovers, the POS orders, the machines paired by amount, the expense
    assert any(d["code"] == "W-777" for d in client.get("/api/drivers").json())
    p = client.get("/api/pos", params={"date": DAY}).json()
    assert p["totals"]["system_total"] == 330.0 and p["totals"]["unpaired"] == 0 and p["totals"]["difference"] == 0
    assert client.get("/api/collections", params={"date": DAY}).json()["totals"]["cash_received"] == 100.0
    assert client.get("/api/expenses", params={"date": DAY}).json()["totals"]["total"] == 40.0

    # the same report saved again changes nothing
    (inbox / "collection report.csv").write_bytes(_report())
    again = client.post("/api/watch/scan").json()
    assert again["imported"][0]["summary"] == "Already imported earlier: nothing to do"
    log = client.get("/api/watch").json()["files"]
    assert log[0]["filename"] == "collection report.csv" and len(log) == 6
    client.put("/api/watch", json={"folder": ""})
    assert client.post("/api/watch/scan").status_code == 409
