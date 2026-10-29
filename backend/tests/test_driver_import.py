"""Importing the driver list, and number-only IDs from Excel in every import."""
import io

import pandas as pd

from app.files import clean_code


def up(name, text):
    return {"file": (name, text.encode(), "text/csv")}


def test_clean_code():
    assert clean_code(" d-101 ") == "D-101" and clean_code("123456.0") == "123456" and clean_code(123456) == "123456"
    assert clean_code(None) == "" and clean_code("12.5") == "12.5"


def test_preview_flags_problems_and_saves_nothing(client):
    text = ("Courier ID,Courier Name,Station,Mobile No,TID\n"
            "E-501,First Import,Jeddah North,0501111111,7101 0001\n"   # new, terminal spaces removed
            "e-502,Second Import,,,\n"                                  # new, only the required columns
            "E-501,Again,,,\n"                                          # same ID twice
            "E 503,Bad Id,,,\n"                                         # space inside the ID
            "E-504,,,,\n"                                               # no name
            "E-505,Taken Terminal,,,60311101\n"                         # D-101's terminal
            "E-506,Twice Terminal,,,71010001\n")                        # same terminal as row 2
    r = client.post("/api/drivers/import", files=up("drivers.csv", text))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["counts"] == {"new": 2, "update": 0, "same": 0, "skipped": 0, "error": 5} and out["saved"] == 0
    p = {x["line"]: " | ".join(x["problems"]) for x in out["rows"]}
    assert "repeated with different details, first on row 2" in p[4] and "letters, numbers and dashes" in p[5] and "no driver name" in p[6]
    assert "already belongs to D-101" in p[7] and "terminal 71010001 repeated" in p[8]
    assert out["rows"][0]["terminal"] == "71010001" and out["rows"][1]["driver_code"] == "E-502"
    assert not [d for d in client.get("/api/drivers").json() if d["code"].startswith("E-5")]


def test_commit_adds_then_updates_without_wiping(client):
    text = "Driver ID,Driver name,Hub,POS terminal ID\nE-601,Real Test One,Hub A,71020001\nE-602,Real Test Two,Hub A,\n"
    r = client.post("/api/drivers/import", files=up("d.csv", text), data={"commit": "true"}).json()
    assert r["saved"] == 2
    again = "Driver ID,Driver name,Hub,POS terminal ID\nE-601,Real Test One,,71020001\nE-602,Real Test Two,Hub B,\n"
    r = client.post("/api/drivers/import", files=up("d2.csv", again)).json()
    assert r["counts"] == {"new": 0, "update": 1, "same": 1, "skipped": 0, "error": 0}  # an empty hub does not wipe "Hub A"
    client.post("/api/drivers/import", files=up("d2.csv", again), data={"commit": "true"})
    rows = {d["code"]: d for d in client.get("/api/drivers").json()}
    assert rows["E-601"]["hub"] == "Hub A" and rows["E-601"]["pos_terminal"] == "71020001" and rows["E-602"]["hub"] == "Hub B"
    log = [a["summary"] for a in client.get("/api/audit").json()[:3]]
    assert any("1 added" in s or "0 added, 1 updated" in s for s in log)


def test_excel_with_number_only_ids_works_across_imports(client):
    buf = io.BytesIO()
    pd.DataFrame({"Driver ID": [880011.0], "Name": ["Number Id"], "Terminal": [71030001.0]}).to_excel(buf, index=False)
    r = client.post("/api/drivers/import", files={"file": ("d.xlsx", buf.getvalue(), "application/octet-stream")},
                    data={"commit": "true"}).json()
    assert r["rows"][0]["driver_code"] == "880011" and r["rows"][0]["terminal"] == "71030001" and r["saved"] == 1
    buf = io.BytesIO()
    pd.DataFrame({"Driver ID": [880011.0], "Expected cash": [100], "Cash received": [90]}).to_excel(buf, index=False)
    r = client.post("/api/collections/import", files={"file": ("h.xlsx", buf.getvalue(), "application/octet-stream")},
                    data={"business_date": "2026-04-05"}).json()
    assert r["counts"]["new"] == 1 and r["rows"][0]["difference"] == -10.0


def test_template_and_missing_columns(client):
    assert "Driver ID,Driver name,Station,Hub,Mobile,POS terminal ID" in client.get("/api/drivers/template").text
    r = client.post("/api/drivers/import", files=up("x.csv", "Driver ID,Hub\nE-1,X\n"))
    assert r.status_code == 422 and "Driver name" in r.json()["error"]["message"]
