"""Collections: what each driver hands over at the end of a business day.

The desk counts the cash and compares it with the cash the delivery system says the driver
collected. Card payments (POS) are recorded here as totals; stage 3 checks them order by order."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, true
from sqlalchemy.orm import Session

from . import audit
from .database import get_db
from .deps import current_user, not_future, parse_day
from .files import FileProblem, clean_code, find_column, read_date, read_upload
from .models import AppSetting, Collection, Driver, TerminalTotal
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/collections", tags=["collections"])

MAX_AMOUNT = 100_000_000  # 1,000,000 SAR in halalas: nothing a single driver hands over in one day
MAX_ORDERS = 1000


CASH_MODES = ("count", "paid")  # count: the desk counts each driver's cash; paid: orders are closed only when paid in full


def cash_mode(db: Session) -> str:
    s = db.get(AppSetting, "cash_mode")
    return s.value if s and s.value in CASH_MODES else "count"


def status_of(diff: int) -> str:
    return "short" if diff < 0 else "over" if diff > 0 else "ok"


def row_dict(c: Collection) -> dict:
    diff = c.cash_received - c.expected_cash
    return {"id": c.id, "business_date": c.business_date.isoformat(), "driver_id": c.driver_id,
            "driver_code": c.driver.code, "driver_name": c.driver.name, "hub": c.driver.hub,
            "orders": c.orders, "expected_cash": to_sar(c.expected_cash), "cash_received": to_sar(c.cash_received),
            "difference": to_sar(diff), "status": status_of(diff), "pos_amount": to_sar(c.pos_amount), "pos_terminal": c.pos_terminal,
            "total": to_sar(c.cash_received + c.pos_amount), "note": c.note, "created_by": c.created_by}


def day_totals(rows: list[Collection]) -> dict:
    diffs = [c.cash_received - c.expected_cash for c in rows]
    return {"expected_cash": to_sar(sum(c.expected_cash for c in rows)),
            "cash_received": to_sar(sum(c.cash_received for c in rows)),
            "difference": to_sar(sum(diffs)),
            "short": to_sar(-sum(d for d in diffs if d < 0)), "over": to_sar(sum(d for d in diffs if d > 0)),
            "short_count": sum(d < 0 for d in diffs), "over_count": sum(d > 0 for d in diffs),
            "pos_amount": to_sar(sum(c.pos_amount for c in rows)),
            "total": to_sar(sum(c.cash_received + c.pos_amount for c in rows)),
            "orders": sum(c.orders for c in rows), "drivers": len(rows)}


@router.get("")
def list_day(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    rows = (db.query(Collection).join(Driver).filter(Collection.business_date == day)
            .order_by(Driver.code).all())
    done = {c.driver_id for c in rows}
    missing = db.query(Driver).filter(Driver.active.is_(True), Driver.id.notin_(done) if done else true()).order_by(Driver.code).all()
    return {"date": day.isoformat(), "rows": [row_dict(c) for c in rows], "totals": day_totals(rows),
            "missing": [{"id": d.id, "code": d.code, "name": d.name, "hub": d.hub} for d in missing]}


@router.get("/days")
def recent_days(end: str, count: int = 14, db: Session = Depends(get_db)):
    """Totals for the days up to `end`, newest first, for the date strip."""
    last = parse_day(end, "end")
    first = last - timedelta(days=max(1, min(count, 92)) - 1)
    diff = Collection.cash_received - Collection.expected_cash
    q = (db.query(Collection.business_date, func.count(Collection.id), func.sum(Collection.cash_received),
                  func.sum(Collection.pos_amount), func.sum(diff),
                  func.sum(func.min(diff, 0)))
         .filter(Collection.business_date.between(first, last)).group_by(Collection.business_date)
         .order_by(Collection.business_date.desc()))
    return [{"date": d.isoformat(), "drivers": n, "cash_received": to_sar(cash), "pos_amount": to_sar(pos),
             "difference": to_sar(net), "short": to_sar(-short)} for d, n, cash, pos, net, short in q]


Amount = int | float | str


class HandoverIn(BaseModel):
    business_date: str
    driver_id: int
    orders: int = Field(0, ge=0, le=MAX_ORDERS)
    expected_cash: Amount
    cash_received: Amount
    pos_amount: Amount = 0
    note: str = Field("", max_length=300)


def _amount(value, label: str) -> int:
    h = to_halalas(value)
    if h is None:
        raise HTTPException(422, f"{label} is not a valid amount")
    if h < 0:
        raise HTTPException(422, f"{label} cannot be negative")
    if h > MAX_AMOUNT:
        raise HTTPException(422, f"{label} is too large")
    return h


def _describe(c: Collection) -> str:
    return (f"expected {to_sar(c.expected_cash):,.2f}, cash {to_sar(c.cash_received):,.2f}, "
            f"POS {to_sar(c.pos_amount):,.2f}, {c.orders} orders")


def save_handover(db: Session, user: str, day: date, driver: Driver, orders: int, expected: int, received: int,
                  pos: int, note: str, source: str = "") -> tuple[Collection, str]:
    """Create or update one driver's handover for a day. Returns (row, "new" | "updated" | "same")."""
    existing = db.query(Collection).filter_by(business_date=day, driver_id=driver.id).first()
    machines = db.query(TerminalTotal).filter_by(business_date=day).all()
    if machines:  # with a terminal sheet for the day, the POS amount is the machines paired with this driver
        pos = sum(m.amount for m in machines if m.driver_id == driver.id)
    values = {"orders": orders, "expected_cash": expected, "cash_received": received, "pos_amount": pos, "note": note,
              "pos_terminal": (existing.pos_terminal if existing and existing.pos_terminal else driver.pos_terminal)}
    if existing:
        if all(getattr(existing, k) == v for k, v in values.items()):
            return existing, "same"
        before = _describe(existing)
        for k, v in values.items():
            setattr(existing, k, v)
        audit.record(db, user, "updated", "collection", existing.id,
                     f"{driver.code} on {day.isoformat()}{source}: {before} -> {_describe(existing)}")
        return existing, "updated"
    row = Collection(business_date=day, driver_id=driver.id, created_by=user, **values)
    row.driver = driver
    db.add(row)
    db.flush()
    diff = received - expected
    extra = f", {'short' if diff < 0 else 'over'} {abs(diff) / 100:,.2f}" if diff else ""
    audit.record(db, user, "created", "collection", row.id, f"{driver.code} on {day.isoformat()}{source}: {_describe(row)}{extra}")
    return row, "new"


@router.put("")
def upsert(body: HandoverIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    day = not_future(parse_day(body.business_date, "business_date"))
    driver = db.get(Driver, body.driver_id)
    if not driver:
        raise HTTPException(404, "Driver not found")
    if not driver.active and not db.query(Collection).filter_by(business_date=day, driver_id=driver.id).first():
        raise HTTPException(409, f"{driver.code} is inactive. Reactivate the driver on the Drivers page first")
    expected = _amount(body.expected_cash, "Expected cash")
    # when orders are closed only once paid in full, what the driver handed over is the system cash
    received = expected if cash_mode(db) == "paid" else _amount(body.cash_received, "Cash received")
    row, result = save_handover(db, user, day, driver, body.orders, expected, received, _amount(body.pos_amount, "POS amount"),
                                " ".join(body.note.split()))
    db.commit()
    return {**row_dict(row), "result": result}


@router.delete("/{cid}")
def delete(cid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    row = db.get(Collection, cid)
    if not row:
        raise HTTPException(404, "Handover not found")
    audit.record(db, user, "deleted", "collection", row.id,
                 f"Deleted {row.driver.code} on {row.business_date.isoformat()}: {_describe(row)}")
    db.delete(row)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- import

COLUMNS = {
    "driver": ("driverid", "drivercode", "driverno", "courierid", "couriercode", "dacode", "daid", "deliveryagentcode",
               "deliveryagentid", "employeeid", "empid", "driver", "courier", "id"),
    "name": ("drivername", "couriername", "daname", "deliveryagentname", "name"),
    "date": ("businessdate", "date", "day", "collectiondate", "collectionoperationtime", "collectiontime"),
    "orders": ("orders", "ordercount", "codorders", "deliveredorders", "delivered", "noofswaybills", "waybills"),
    "expected": ("expectedcash", "systemcash", "codcash", "cashexpected", "expected", "cashsystem", "expectedcod"),
    "received": ("cashreceived", "receivedcash", "cashcollected", "cashhandedover", "actualcash", "cash", "received"),
    "pos": ("posamount", "pos", "card", "cardamount", "possales", "poscollected", "mada"),
    "note": ("note", "notes", "remark", "remarks", "comment"),
}
TEMPLATE = ("Driver ID,Driver name,Date,Orders,Expected cash,Cash received,POS amount,Note\n"
            "D-101,Example Driver,2026-10-26,24,2150.00,2150.00,1320.50,\n")


@router.get("/template")
def template():
    return Response(TEMPLATE, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="codesk-collections-template.csv"'})


def _check_rows(db: Session, df, default_day: date | None) -> tuple[list[dict], dict]:
    cols = {k: find_column(df, v) for k, v in COLUMNS.items()}
    missing = [label for key, label in (("driver", "Driver ID"), ("expected", "Expected cash"), ("received", "Cash received"))
               if not cols[key]]
    if missing:
        raise FileProblem(f"The file needs these columns: {', '.join(missing)}. Download the template to see the layout")
    if not cols["date"] and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")
    drivers = {d.code.upper(): d for d in db.query(Driver)}
    seen: dict[tuple, int] = {}
    out = []
    for i, r in df.iterrows():
        line = i + 2  # row 1 is the header
        code = clean_code(r[cols["driver"]])
        problems = []
        day = read_date(r[cols["date"]]) if cols["date"] and str(r[cols["date"]]).strip() else default_day
        if day is None:
            problems.append("date not readable")
        elif day > date.today():
            problems.append("date is in the future")
        drv = drivers.get(code)
        if not code:
            problems.append("no driver ID")
        elif not drv:
            problems.append(f"unknown driver {code}")
        elif not drv.active:
            problems.append(f"{code} is inactive")

        def amount(key, label, required=True):
            raw = r[cols[key]] if cols[key] else ""
            if not str(raw).strip():
                if required:
                    problems.append(f"{label} is empty")
                return 0
            h = to_halalas(raw)
            if h is None:
                problems.append(f"{label} '{raw}' is not a number")
                return 0
            if h < 0 or h > MAX_AMOUNT:
                problems.append(f"{label} is out of range")
            return h

        expected = amount("expected", "expected cash")
        received = amount("received", "cash received")
        pos = amount("pos", "POS amount", required=False)
        orders_raw = str(r[cols["orders"]]).strip() if cols["orders"] else ""
        orders = 0
        if orders_raw:
            try:
                orders = int(float(orders_raw))
                if not 0 <= orders <= MAX_ORDERS:
                    raise ValueError
            except ValueError:
                problems.append(f"orders '{orders_raw}' is not a whole number")
        if day and code:
            if (day, code) in seen:
                problems.append(f"same driver and date as row {seen[(day, code)]}")
            else:
                seen[(day, code)] = line
        status = "error" if problems else "new"
        if not problems:
            existing = db.query(Collection).filter_by(business_date=day, driver_id=drv.id).first()
            if existing:
                same = (existing.expected_cash, existing.cash_received, existing.pos_amount, existing.orders) == (expected, received, pos, orders)
                status = "same" if same else "update"
        out.append({"line": line, "status": status, "problems": problems, "driver_code": code or None,
                    "driver_name": drv.name if drv else (str(r[cols["name"]]).strip() if cols["name"] else ""),
                    "date": day.isoformat() if day else None, "orders": orders,
                    "expected_cash": to_sar(expected), "cash_received": to_sar(received), "pos_amount": to_sar(pos),
                    "difference": to_sar(received - expected),
                    "note": str(r[cols["note"]]).strip()[:300] if cols["note"] else "",
                    "_driver": drv, "_day": day, "_h": (orders, expected, received, pos)})
    counts = {k: sum(o["status"] == k for o in out) for k in ("new", "update", "same", "error")}
    return out, counts


def _is_order_report(df) -> bool:
    """The delivery system's collection report: one line per order (or charge), with how it was collected."""
    from .pos import ORDER_COLUMNS
    return bool(find_column(df, ORDER_COLUMNS["order"]) and find_column(df, ORDER_COLUMNS["method"])
                and find_column(df, ORDER_COLUMNS["amount"]) and find_column(df, COLUMNS["driver"]))


def _check_report(db: Session, df, default_day: date | None) -> tuple[list[dict], dict]:
    """Turn the order-level collection report into one handover per driver and day: the expected cash is
    every line collected in cash (and the cash part of split payments), the orders are counted once each.
    The report cannot know the cash counted at the desk: a new handover starts with the counted cash equal
    to the expected cash, and an existing one keeps the counted cash already recorded."""
    from .pos import ORDER_COLUMNS, is_pos, is_split
    ocol, mcol, acol = (find_column(df, ORDER_COLUMNS[k]) for k in ("order", "method", "amount"))
    dcol, ncol = find_column(df, COLUMNS["driver"]), find_column(df, COLUMNS["name"])
    tcol = find_column(df, ORDER_COLUMNS["date"])
    pay_col = find_column(df, ("paymentmethod", "paymenttype", "paymentmode"))
    if pay_col == mcol:
        pay_col = None
    if not tcol and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")
    drivers = {d.code.upper(): d for d in db.query(Driver)}
    groups: dict[tuple, dict] = {}
    bad = []
    for i, r in df.iterrows():
        line, problems = i + 2, []
        code = clean_code(r[dcol])
        day = read_date(r[tcol]) if tcol and str(r[tcol]).strip() else default_day
        method = str(r[mcol]).strip()
        if is_split(method):
            part = str(r[pay_col]).strip() if pay_col else ""
            method = part if part and not is_split(part) else ""
            if not method:
                problems.append("split payment without the part it was")
        amount = to_halalas(r[acol]) if str(r[acol]).strip() else 0
        if amount is None:
            problems.append(f"amount '{r[acol]}' is not a number")
        if not code:
            problems.append("no driver ID")
        if day is None:
            problems.append("date not readable")
        elif day > date.today():
            problems.append("date is in the future")
        if problems:
            bad.append({"line": line, "status": "error", "problems": problems, "driver_code": code or None,
                        "driver_name": "", "date": day.isoformat() if day else None, "orders": 0, "expected_cash": 0,
                        "cash_received": 0, "pos_amount": 0, "difference": 0, "note": ""})
            continue
        g = groups.setdefault((day, code), {"line": line, "orders": set(), "cash": 0, "pos": 0,
                                            "name": str(r[ncol]).strip() if ncol else ""})
        g["orders"].add(clean_code(r[ocol]))
        g["pos" if is_pos(method) else "cash"] += amount
    out = []
    for (day, code), g in sorted(groups.items(), key=lambda kv: kv[1]["line"]):
        drv, problems = drivers.get(code), []
        if not drv:
            problems.append(f"unknown driver {code}. Import the drivers from this file first")
        elif not drv.active:
            problems.append(f"{code} is inactive")
        existing = db.query(Collection).filter_by(business_date=day, driver_id=drv.id).first() if drv else None
        expected, orders = g["cash"], len(g["orders"])
        paid = cash_mode(db) == "paid"  # orders closed only when paid: the cash received is the system cash
        received = expected if paid or not existing else existing.cash_received
        pos = existing.pos_amount if existing else 0
        note = (existing.note if existing else "")
        status = "error" if problems else "new"
        if existing and not problems:
            status = "same" if (existing.expected_cash, existing.cash_received, existing.orders) == (expected, received, orders) else "update"
        notes = [] if problems or paid else (["counted cash kept as recorded"] if existing else ["counted cash set to the system cash: change it if short"])
        out.append({"line": g["line"], "status": status, "problems": problems + notes, "driver_code": code,
                    "driver_name": drv.name if drv else g["name"], "date": day.isoformat(), "orders": orders,
                    "expected_cash": to_sar(expected), "cash_received": to_sar(received), "pos_amount": to_sar(pos),
                    "system_pos": to_sar(g["pos"]), "difference": to_sar(received - expected), "note": note,
                    "_driver": drv, "_day": day, "_h": (orders, expected, received, pos)})
    out += bad
    counts = {k: sum(o["status"] == k for o in out) for k in ("new", "update", "same", "error")}
    return out, counts


@router.post("/import")
async def import_file(file: UploadFile = File(...), business_date: str = Form(""), commit: bool = Form(False),
                      db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Check a file and show what would happen (commit=false), or save the good rows (commit=true).
    Rows with problems are never saved; the person fixes the file and imports again."""
    default_day = not_future(parse_day(business_date, "business_date")) if business_date else None
    try:
        return run(db, file.filename or "file", await file.read(1 + 5_000_000), default_day, commit, user)
    except FileProblem as e:
        raise HTTPException(422, str(e))


def run(db: Session, filename: str, data: bytes, default_day: date | None, commit: bool, user: str) -> dict:
    """Check (and with commit, save) handovers from a file. Also used by the watch folder."""
    df = read_upload(filename, data)
    rows, counts = (_check_report if _is_order_report(df) else _check_rows)(db, df, default_day)
    if not rows:
        raise FileProblem("The file has a header but no rows")
    saved = 0
    if commit:
        for r in rows:
            if r["status"] in ("new", "update"):
                orders, expected, received, pos = r["_h"]
                save_handover(db, user, r["_day"], r["_driver"], orders, expected, received, pos,
                              " ".join(r["note"].split()), source=f" (import {filename})")
                saved += 1
        db.commit()
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"file": filename, "rows": clean, "counts": counts, "committed": commit, "saved": saved,
            "dates": sorted({r["date"] for r in clean if r["date"]})}
