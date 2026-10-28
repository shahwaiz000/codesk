"""The delivery system's "cashier has received the payment" report, read as it is exported.

The layout copies the real export (a pivot sheet first, then one line per order and charge);
every value here is invented."""
import io

import pandas as pd

HEAD = ["Waybill Number", "Order Number", "Charge Generation Time", "Charge Category", "Payment Method", "Collect Method",
        "Currency", "Net Cash Collected Amount", "Actual Received Amount", "DA Code", "DA Name", "Site Code",
        "Collection Operation Time", "cash", "pos"]


def line(wb, order, charge, pay, collect, amount, da, name):
    return [wb, order, "2026-02-03 10:00:00", charge, pay, collect, "SAR", amount, amount, da, name, "S1",
            "2026-02-03 18:30:00", amount if collect == "Cash" else "", amount if collect == "POS" else ""]


ROWS = [
    line("9000000000001", "FK00000000000001", "COD", "Cash", "Cash", 120.0, "X00000000001", "Fake Driver One"),
    line("9000000000002", "FK00000000000002", "COD", "Cash", "POS", 200.0, "X00000000001", "Fake Driver One"),  # chose cash, paid card
    line("9000000000002", "FK00000000000002", "Import VAT", "Cash", "POS", 15.5, "X00000000001", "Fake Driver One"),  # same order, VAT line
    line("9000000000003", "FK00000000000003", "COD", "POS", "POS", 300.0, "X00000000002", "Fake Driver Two"),
    line("9000000000004", "FK00000000000004", "Import VAT", "Cash", "part pos and part case", 1.2, "X00000000002", "Fake Driver Two"),
    line("9000000000004", "FK00000000000004", "Import VAT", "POS", "part pos and part case", 4.3, "X00000000002", "Fake Driver Two"),
    line("9000000000005", "FK00000000000005", "COD", "Mixed payment-Cash", "Cash", 50.0, "8800000001", "Fake Driver Three"),
    line("9000000000005", "FK00000000000005", "COD", "Mixed payment-POS", "POS", 70.0, "8800000001", "Fake Driver Three"),
]


def report() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:  # the pivot sheet comes first, as in the real export
        pd.DataFrame([[None, None, None], ["DA Code", "Sum of pos", "Sum of cash"], ["X00000000001", 215.5, 120]]).to_excel(
            xw, sheet_name="Sheet2", index=False, header=False, startrow=1)
        pd.DataFrame(ROWS, columns=HEAD).to_excel(xw, sheet_name="sheet1", index=False)
    return buf.getvalue()


def send(client, path, commit=False, **data):
    return client.post(path, files={"file": ("cashier-report.xlsx", report(), "application/octet-stream")},
                       data={**data, "commit": str(commit).lower()}).json()


def test_drivers_come_from_the_report_once_each(client):
    out = send(client, "/api/drivers/import")
    assert out["counts"] == {"new": 3, "update": 0, "same": 0, "skipped": 5, "error": 0}, out["rows"]
    assert {r["driver_code"] for r in out["rows"] if r["status"] == "new"} == {"X00000000001", "X00000000002", "8800000001"}
    assert send(client, "/api/drivers/import", commit=True)["saved"] == 3


def test_pos_orders_use_collect_method_and_add_vat_to_the_order(client):
    out = send(client, "/api/pos/import/orders")
    by_line = {r["line"]: r for r in out["rows"]}
    assert by_line[2]["status"] == "skipped"                                     # collected in cash
    assert by_line[3]["status"] == "new" and "order total 215.50" in by_line[3]["problems"][0]  # customer chose cash, paid by card
    assert "added to row 3" in by_line[4]["problems"][0]                       # the VAT line of the same order
    assert by_line[6]["status"] == "skipped" and "this line was Cash" in by_line[6]["problems"][0]  # split: the cash part
    assert by_line[7]["status"] == "new" and "this line was POS" in by_line[7]["problems"][0]       # split: the POS part
    assert by_line[8]["status"] == "skipped" and by_line[9]["status"] == "new"  # a mixed payment: only its POS line counts
    assert out["dates"] == ["2026-02-03"]                                       # read from Collection Operation Time
    send(client, "/api/pos/import/orders", commit=True)
    day = client.get("/api/pos", params={"date": "2026-02-03"}).json()
    sys_totals = {r["driver_code"]: r["system_total"] for r in day["rows"]}
    assert sys_totals == {"X00000000001": 215.5, "X00000000002": 304.3, "8800000001": 70.0}
    again = send(client, "/api/pos/import/orders")
    assert again["counts"]["new"] == 0 and again["counts"]["same"] == 5         # importing twice changes nothing


def test_a_split_line_with_an_unknown_driver_is_still_a_problem(client):
    text = ("Order Number,DA Code,Actual Received Amount,Collect Method,Payment Method,Collection Operation Time\n"
            "SPLIT-1,NOBODY-1,5,part pos and part case,POS,2026-02-04 10:00:00\n")
    out = client.post("/api/pos/import/orders", files={"file": ("r.csv", text.encode(), "text/csv")}).json()
    assert out["rows"][0]["status"] == "error" and "unknown driver NOBODY-1" in out["rows"][0]["problems"]
