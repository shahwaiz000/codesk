"""Import the day's driver expenses from the desk's own sheet: date, driver ID, driver name, amount.

The category column is optional (salary, incentive, final settlement, fuel, travel... in the desk's own
words); without it a row is saved as Other and can be changed on the page. A driver who is not in CODesk yet is added from the name in the sheet, so a driver who had no
collection that day can still be paid. A row already saved (same day, driver, category and amount) is
skipped, so importing the same sheet twice never pays twice."""
import re
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import audit
from .collections import COLUMNS as HANDOVER_COLUMNS, MAX_AMOUNT
from .database import get_db
from .deps import current_user, not_future, parse_day
from .expenses import CATEGORY_TEXT
from .files import FileProblem, clean_code, find_column, find_header, read_date, read_upload
from .models import Driver, Expense
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

COLUMNS = {
    "driver": HANDOVER_COLUMNS["driver"],
    "name": HANDOVER_COLUMNS["name"] + ("employeename", "fullname"),
    "date": HANDOVER_COLUMNS["date"] + ("expensedate", "paiddate", "paymentdate"),
    "amount": ("amount", "expense", "expenseamount", "paid", "paidamount", "total", "sar", "value"),
    "category": ("category", "type", "expensetype", "reason", "purpose"),
    "reference": ("reference", "ref", "receipt", "receiptno", "voucher", "voucherno"),
    "note": ("note", "notes", "remark", "remarks", "comment", "description"),
}
WORDS = {  # a category written in the sheet, in the desk's own words
    "salary": ("salary", "salaries", "wage", "payroll"), "incentive": ("incentive", "bonus", "reward", "commission"),
    "settlement": ("settlement", "final", "eos", "end of service"),
    "fuel": ("fuel", "petrol", "diesel", "gas"), "toll": ("toll",), "parking": ("parking",),
    "travel": ("travel", "trip", "transport", "taxi", "ticket"), "maintenance": ("maintenance", "repair", "tyre", "tire", "oil"),
    "advance": ("advance", "loan"), "other": ("other",),
}
CODE_OK = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")
TEMPLATE = "Date,Driver ID,Driver name,Amount,Category,Receipt no,Note\n27-Oct-26,D-101,Example Driver,57.00,Travel,,\n"


@router.get("/template")
def template():
    return Response(TEMPLATE, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="codesk-expenses-template.csv"'})


def _category(text: str) -> str | None:
    t = text.lower()
    return next((k for k, words in WORDS.items() if any(w in t for w in words)), None)


def _no_header(df):
    """A sheet copied without its heading row: date, driver ID, name, amount by position."""
    first = [str(c) for c in df.columns]
    if len(first) >= 4 and read_date(first[0]) and to_halalas(first[3]) is not None:
        df = df.copy()
        df.loc[-1] = first
        df = df.sort_index().reset_index(drop=True)
        df.columns = ["Date", "Driver ID", "Driver name", "Amount"] + [f"Unnamed: {i}" for i in range(4, len(first))]
        return df, -1
    return None, 0


def _check(db: Session, df, default_day: date | None) -> list[dict]:
    plain, shift = _no_header(df)
    if plain is not None:
        df, above = plain, shift
    else:
        df, above = find_header(df, COLUMNS["driver"])
    cols = {k: find_column(df, v) for k, v in COLUMNS.items()}
    missing = [label for key, label in (("driver", "Driver ID"), ("amount", "Amount")) if not cols[key]]
    if missing:
        raise FileProblem(f"The file needs these columns: {', '.join(missing)}. Download the template to see the layout")
    if not cols["date"] and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")
    drivers = {d.code: d for d in db.query(Driver)}
    new_names: dict[str, str] = {}
    seen = Counter()
    out = []
    for i, r in df.iterrows():
        line, problems, notes = i + 2 + above, [], []
        cell = lambda k: " ".join(str(r[cols[k]]).split()) if cols[k] else ""  # noqa: E731
        code, name, raw = clean_code(r[cols["driver"]]), cell("name"), cell("amount")
        if not code and not raw:
            continue  # an empty row
        if not code and "total" in " ".join(str(v) for v in r.values).lower():
            out.append({"line": line, "status": "skipped", "problems": ["a total line, not a payment"], "date": None,
                        "driver_code": None, "driver_name": "", "category": None, "category_text": "", "amount": None,
                        "reference": "", "note": "", "_day": None, "_amount": None, "_driver": None})
            continue
        day = read_date(r[cols["date"]]) if cols["date"] and cell("date") else default_day
        if day is None:
            problems.append("date not readable")
        elif day > date.today():
            problems.append("date is in the future")
        amount = to_halalas(raw) if raw else None
        if amount is None:
            problems.append(f"amount '{raw}' is not a number" if raw else "no amount")
        elif amount <= 0 or amount > MAX_AMOUNT:
            problems.append("amount must be more than 0")
        written = cell("category")
        category = _category(written) if written else "other"
        if category is None:
            category = "other"
            notes.append(f"'{written}' saved as Other")
        drv = drivers.get(code)
        if not code:
            problems.append("no driver ID")
        elif not drv:
            if not CODE_OK.match(code):
                problems.append(f"driver ID '{code}' can only use letters, numbers and dashes")
            elif len(name) < 2:
                problems.append(f"unknown driver {code} and no name to add him")
            elif new_names.setdefault(code, name) != name:
                problems.append(f"driver {code} has two different names in this file")
            else:
                notes.append("new driver, added to CODesk on save")
        elif not drv.active:
            problems.append(f"{code} is inactive")
        status = "error" if problems else "new"
        if not problems:
            key = (day, code, category, amount)
            seen[key] += 1
            if drv:
                saved = db.query(Expense).filter_by(business_date=day, driver_id=drv.id, category=category, amount=amount).count()
                if seen[key] <= saved:
                    status, notes = "same", ["already saved"]
            if seen[key] > 1 and status == "new":
                notes.append("same driver and amount again on this day")
        out.append({"line": line, "status": status, "problems": problems + notes, "date": day.isoformat() if day else None,
                    "driver_code": code or None, "driver_name": drv.name if drv else name,
                    "category": category, "category_text": CATEGORY_TEXT[category], "amount": to_sar(amount or 0),
                    "reference": cell("reference")[:60], "note": cell("note")[:300],
                    "_day": day, "_amount": amount, "_driver": drv})
    return out


@router.post("/import")
async def import_expenses(file: UploadFile = File(...), business_date: str = Form(""), commit: bool = Form(False),
                          db: Session = Depends(get_db), user: str = Depends(current_user)):
    default_day = not_future(parse_day(business_date, "business_date")) if business_date else None
    try:
        df = read_upload(file.filename or "", await file.read(1 + 5_000_000))
        rows = _check(db, df, default_day)
    except FileProblem as e:
        raise HTTPException(422, str(e))
    if not rows:
        raise HTTPException(422, "The file has a header but no rows")
    saved = 0
    if commit:
        added: dict[str, Driver] = {}
        for r in rows:
            if r["status"] != "new":
                continue
            drv = r["_driver"] or added.get(r["driver_code"])
            if not drv:
                drv = Driver(code=r["driver_code"], name=r["driver_name"])
                db.add(drv)
                db.flush()
                audit.record(db, user, "created", "driver", drv.id, f"{drv.code} {drv.name} (from expense sheet {file.filename})")
                added[drv.code] = drv
            db.add(Expense(business_date=r["_day"], driver_id=drv.id, category=r["category"], amount=r["_amount"],
                           reference=r["reference"], note=r["note"], created_by=user))
            saved += 1
        if saved:
            total = sum(r["_amount"] for r in rows if r["status"] == "new")
            audit.record(db, user, "imported", "expense", None,
                         f"Expense sheet {file.filename}: {saved} payments, total {to_sar(total):,.2f}")
        db.commit()
    counts = {k: sum(r["status"] == k for r in rows) for k in ("new", "update", "same", "skipped", "error")}
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"file": file.filename, "rows": clean, "counts": counts, "committed": commit, "saved": saved,
            "dates": sorted({r["date"] for r in clean if r["date"]})}
