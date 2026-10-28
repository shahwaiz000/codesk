"""POS check: for each driver and day, the system's POS-closed orders against the terminal total.

At the desk the cashier opens the driver's POS-closed orders in the delivery system, and records the
day's total from the driver's POS terminal. Both should be the same amount. When they are not, the
order list is where the person looks for the cause, and they mark the difference as explained (with a
reason) or as needing follow-up."""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import audit
from .collections import COLUMNS as HANDOVER_COLUMNS, MAX_AMOUNT
from .database import get_db
from .deps import current_user, not_future, parse_day
from .files import FileProblem, clean_code, find_column, read_date, read_upload
from .models import Collection, Driver, PosOrder, PosReview, utcnow, iso
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/pos", tags=["pos"])

STATUS_TEXT = {"agrees": "Agrees", "terminal_short": "Terminal short", "terminal_over": "Terminal over",
               "no_terminal": "No terminal total", "awaiting_orders": "Waiting for system orders"}


def _status(system: int, terminal: int | None, orders_loaded: bool = True) -> str:
    if terminal is None:
        return "no_terminal"
    if not orders_loaded and terminal:
        return "awaiting_orders"  # the day's POS orders are not imported yet: not a difference, just not checked
    return "agrees" if terminal == system else "terminal_short" if terminal < system else "terminal_over"


def day_rows(db: Session, day: date) -> list[dict]:
    orders = defaultdict(lambda: [0, 0])
    for driver_id, total, n in (db.query(PosOrder.driver_id, func.sum(PosOrder.amount), func.count(PosOrder.id))
                                .filter(PosOrder.business_date == day).group_by(PosOrder.driver_id)):
        orders[driver_id] = [int(total), n]
    orders_loaded = bool(orders)
    handovers = {c.driver_id: c for c in db.query(Collection).filter_by(business_date=day)}
    reviews = {r.driver_id: r for r in db.query(PosReview).filter_by(business_date=day)}
    ids = set(orders) | set(handovers)
    drivers = {d.id: d for d in db.query(Driver).filter(Driver.id.in_(ids))} if ids else {}
    rows = []
    for did in sorted(ids, key=lambda i: drivers[i].code):
        d, h = drivers[did], handovers.get(did)
        system, count = orders[did]
        terminal = h.pos_amount if h else None
        status = _status(system, terminal, orders_loaded)
        r = reviews.get(did)
        review = None
        if r and status in ("terminal_short", "terminal_over"):
            review = {"status": r.status, "note": r.note, "by": r.decided_by, "at": iso(r.decided_at),
                      "stale": (r.system_total, r.terminal_total) != (system, terminal)}
        rows.append({"driver_id": did, "driver_code": d.code, "driver_name": d.name,
                     "terminal": (h.pos_terminal if h and h.pos_terminal else d.pos_terminal) or None,
                     "system_total": to_sar(system), "order_count": count, "terminal_total": to_sar(terminal),
                     "difference": to_sar(terminal - system) if terminal is not None else None,
                     "status": status, "status_text": STATUS_TEXT[status], "review": review,
                     "open": status in ("terminal_short", "terminal_over") and (not review or review["stale"] or review["status"] == "follow_up")})
    return rows


def summarize(rows: list[dict]) -> dict:
    diffs = [r for r in rows if r["status"] in ("terminal_short", "terminal_over")]
    return {"system_total": round(sum(r["system_total"] for r in rows), 2),
            "terminal_total": round(sum(r["terminal_total"] or 0 for r in rows), 2),
            "difference": round(sum(r["difference"] or 0 for r in diffs), 2),
            "order_count": sum(r["order_count"] for r in rows), "drivers": len(rows),
            "agrees": sum(r["status"] == "agrees" for r in rows), "differences": len(diffs),
            "no_terminal": sum(r["status"] == "no_terminal" for r in rows),
            "awaiting": sum(r["status"] == "awaiting_orders" for r in rows),
            "open": sum(r["open"] for r in rows),
            "explained": sum(1 for r in diffs if r["review"] and not r["review"]["stale"] and r["review"]["status"] == "explained"),
            "short": round(-sum(r["difference"] for r in diffs if r["difference"] < 0), 2),
            "over": round(sum(r["difference"] for r in diffs if r["difference"] > 0), 2)}


@router.get("")
def pos_day(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    rows = day_rows(db, day)
    return {"date": day.isoformat(), "rows": rows, "totals": summarize(rows),
            "orders_imported": db.query(PosOrder).filter_by(business_date=day).count() > 0}


@router.get("/orders")
def pos_orders(date_: str = Query(alias="date"), driver_id: int = Query(...), db: Session = Depends(get_db)):
    day = parse_day(date_)
    rows = (db.query(PosOrder).filter_by(business_date=day, driver_id=driver_id)
            .order_by(PosOrder.amount.desc(), PosOrder.order_no).all())
    return [{"order_no": o.order_no, "amount": to_sar(o.amount)} for o in rows]


# ---------------------------------------------------------------- review

class ReviewIn(BaseModel):
    business_date: str
    driver_id: int
    status: str = Field(pattern="^(explained|follow_up)$")
    note: str = Field("", max_length=300)


@router.put("/review")
def review(body: ReviewIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    day = parse_day(body.business_date, "business_date")
    row = next((r for r in day_rows(db, day) if r["driver_id"] == body.driver_id), None)
    if not row:
        raise HTTPException(404, "There is no POS record for this driver on this day")
    if row["status"] not in ("terminal_short", "terminal_over"):
        raise HTTPException(409, "Only a difference can be reviewed. This driver's POS agrees or has no terminal total yet")
    note = " ".join(body.note.split())
    if body.status == "explained" and len(note) < 3:
        raise HTTPException(422, "Write the reason the difference is explained")
    r = db.query(PosReview).filter_by(business_date=day, driver_id=body.driver_id).first() or \
        PosReview(business_date=day, driver_id=body.driver_id)
    r.status, r.note, r.decided_by, r.decided_at = body.status, note, user, utcnow()
    r.system_total = to_halalas(row["system_total"])
    r.terminal_total = to_halalas(row["terminal_total"])
    db.add(r)
    db.flush()
    word = "explained" if body.status == "explained" else "marked for follow-up"
    audit.record(db, user, "reviewed", "pos", r.id,
                 f"POS {row['driver_code']} on {day.isoformat()} {word}: difference {row['difference']:+,.2f}" + (f", note: {note}" if note else ""))
    db.commit()
    return next(x for x in day_rows(db, day) if x["driver_id"] == body.driver_id)


@router.delete("/review")
def reopen(business_date: str, driver_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    day = parse_day(business_date, "business_date")
    r = db.query(PosReview).filter_by(business_date=day, driver_id=driver_id).first()
    if not r:
        raise HTTPException(404, "This difference has no review to reopen")
    code = db.get(Driver, driver_id).code
    audit.record(db, user, "reopened", "pos", r.id, f"POS {code} on {day.isoformat()} reopened (was {r.status.replace('_', ' ')})")
    db.delete(r)
    db.commit()
    return {"reopened": True}


# ---------------------------------------------------------------- imports

ORDER_COLUMNS = {
    "order": ("orderno", "ordernumber", "orderid", "waybill", "waybillno", "waybillnumber", "awb", "awbno",
              "trackingno", "trackingnumber", "shipmentno", "order"),
    "driver": HANDOVER_COLUMNS["driver"],
    "amount": ("amount", "codamount", "posamount", "orderamount", "value", "collectedamount", "total"),
    "date": HANDOVER_COLUMNS["date"] + ("closedate", "closeddate", "deliverydate", "delivereddate"),
    "method": ("paymentmethod", "paymenttype", "payment", "paymentmode", "method", "paidby", "collectiontype"),
}
TERMINAL_COLUMNS = {
    "terminal": ("terminalid", "terminalno", "terminalnumber", "terminal", "tid", "posterminal", "posid", "posterminalid"),
    "amount": ("totalamount", "amount", "total", "settledamount", "netamount", "posamount", "totalsales", "sales"),
    "date": HANDOVER_COLUMNS["date"] + ("settlementdate", "transactiondate"),
}
POS_WORDS = ("pos", "card", "mada", "visa", "master", "network", "span", "credit", "debit")
TEMPLATES = {
    "orders": "Order no,Driver ID,Amount,Payment method,Date\nORD7400001,D-101,185.50,POS,2026-10-26\n",
    "terminals": "Terminal ID,Total amount,Date\n60311101,1320.50,2026-10-26\n",
}


@router.get("/template/{kind}")
def template(kind: str):
    if kind not in TEMPLATES:
        raise HTTPException(404, "Unknown template")
    return Response(TEMPLATES[kind], media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="codesk-pos-{kind}-template.csv"'})


def _amount(raw, problems: list[str], label="amount") -> int:
    if not str(raw).strip():
        problems.append(f"{label} is empty")
        return 0
    h = to_halalas(raw)
    if h is None:
        problems.append(f"{label} '{raw}' is not a number")
        return 0
    if h < 0 or h > MAX_AMOUNT:
        problems.append(f"{label} is out of range")
    return h


def _row_day(r, col, default_day, problems) -> date | None:
    day = read_date(r[col]) if col and str(r[col]).strip() else default_day
    if day is None:
        problems.append("date not readable")
    elif day > date.today():
        problems.append("date is in the future")
    return day


def _check_orders(db: Session, df, default_day: date | None):
    cols = {k: find_column(df, v) for k, v in ORDER_COLUMNS.items()}
    missing = [label for key, label in (("order", "Order no"), ("driver", "Driver ID"), ("amount", "Amount")) if not cols[key]]
    if missing:
        raise FileProblem(f"The file needs these columns: {', '.join(missing)}. Download the template to see the layout")
    if not cols["date"] and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")
    drivers = {d.code.upper(): d for d in db.query(Driver)}
    nos = [clean_code(v) for v in df[cols["order"]]]
    existing = {o.order_no: o for o in db.query(PosOrder).filter(PosOrder.order_no.in_([n for n in nos if n]))} if nos else {}
    seen: dict[str, int] = {}
    out = []
    for i, r in df.iterrows():
        line, problems = i + 2, []
        no = nos[i]
        method = str(r[cols["method"]]).strip() if cols["method"] else ""
        base = {"line": line, "order_no": no or None, "method": method}
        if method and not any(w in method.lower() for w in POS_WORDS):
            out.append({**base, "status": "skipped", "problems": [f"paid by {method}, not POS"], "driver_code": None,
                        "driver_name": "", "date": None, "amount": None})
            continue
        code = clean_code(r[cols["driver"]])
        day = _row_day(r, cols["date"], default_day, problems)
        drv = drivers.get(code)
        if not no:
            problems.append("no order number")
        elif no in seen:
            problems.append(f"order repeated, first on row {seen[no]}")
        else:
            seen[no] = line
        if not code:
            problems.append("no driver ID")
        elif not drv:
            problems.append(f"unknown driver {code}")
        amount = _amount(r[cols["amount"]], problems)
        status = "error" if problems else "new"
        if not problems and no in existing:
            o = existing[no]
            status = "same" if (o.driver_id, o.business_date, o.amount) == (drv.id, day, amount) else "update"
        out.append({**base, "status": status, "problems": problems, "driver_code": code or None,
                    "driver_name": drv.name if drv else "", "date": day.isoformat() if day else None,
                    "amount": to_sar(amount), "_driver": drv, "_day": day, "_amount": amount})
    return out


def _save_orders(db: Session, rows, user: str, filename: str) -> int:
    saved, per_day = 0, defaultdict(lambda: [0, 0])
    for r in rows:
        if r["status"] not in ("new", "update"):
            continue
        o = db.query(PosOrder).filter_by(order_no=r["order_no"]).first()
        if o:
            audit.record(db, user, "updated", "pos_order", o.id,
                         f"Order {o.order_no} changed by import {filename}: {o.driver.code} {o.business_date.isoformat()} "
                         f"{to_sar(o.amount):,.2f} -> {r['driver_code']} {r['date']} {r['amount']:,.2f}")
            o.driver_id, o.business_date, o.amount = r["_driver"].id, r["_day"], r["_amount"]
        else:
            db.add(PosOrder(order_no=r["order_no"], driver_id=r["_driver"].id, business_date=r["_day"],
                            amount=r["_amount"], created_by=user))
            per_day[r["date"]][0] += 1
            per_day[r["date"]][1] += r["_amount"]
        saved += 1
    for d, (n, total) in sorted(per_day.items()):
        audit.record(db, user, "imported", "pos_order", None, f"{n} POS orders for {d} from {filename}, total {to_sar(total):,.2f}")
    return saved


def _check_terminals(db: Session, df, default_day: date | None):
    cols = {k: find_column(df, v) for k, v in TERMINAL_COLUMNS.items()}
    missing = [label for key, label in (("terminal", "Terminal ID"), ("amount", "Total amount")) if not cols[key]]
    if missing:
        raise FileProblem(f"The file needs these columns: {', '.join(missing)}. Download the template to see the layout")
    if not cols["date"] and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")
    by_terminal = {d.pos_terminal: d for d in db.query(Driver).filter(Driver.active.is_(True), Driver.pos_terminal != "")}
    seen: dict[tuple, int] = {}
    out = []
    for i, r in df.iterrows():
        line, problems = i + 2, []
        terminal = clean_code(r[cols["terminal"]]).replace(" ", "")
        day = _row_day(r, cols["date"], default_day, problems)
        amount = _amount(r[cols["amount"]], problems, "total amount")
        handover = drv = None
        if not terminal:
            problems.append("no terminal ID")
        elif day:
            handover = db.query(Collection).filter_by(business_date=day, pos_terminal=terminal).first()
            drv = handover.driver if handover else by_terminal.get(terminal)
            if not drv:
                problems.append(f"terminal {terminal} is not given to any driver. Add it on the Drivers page")
            elif not handover:
                handover = db.query(Collection).filter_by(business_date=day, driver_id=drv.id).first()
                if not handover:
                    problems.append(f"{drv.code} has no handover on this day yet. Record the handover first")
            if (day, terminal) in seen:
                problems.append(f"terminal repeated, first on row {seen[(day, terminal)]}")
            else:
                seen[(day, terminal)] = line
        status = "error" if problems else ("same" if handover.pos_amount == amount else "update")
        out.append({"line": line, "status": status, "problems": problems, "terminal": terminal or None,
                    "driver_code": drv.code if drv else None, "driver_name": drv.name if drv else "",
                    "date": day.isoformat() if day else None, "amount": to_sar(amount),
                    "previous": to_sar(handover.pos_amount) if handover else None,
                    "_handover": handover, "_amount": amount, "_terminal": terminal})
    return out


def _save_terminals(db: Session, rows, user: str, filename: str) -> int:
    saved = 0
    for r in rows:
        if r["status"] != "update":
            continue
        h = r["_handover"]
        audit.record(db, user, "updated", "collection", h.id,
                     f"{h.driver.code} on {h.business_date.isoformat()} terminal {r['_terminal']} total "
                     f"{to_sar(h.pos_amount):,.2f} -> {r['amount']:,.2f} (import {filename})")
        h.pos_amount, h.pos_terminal = r["_amount"], r["_terminal"]
        saved += 1
    return saved


@router.post("/import/{kind}")
async def import_file(kind: str, file: UploadFile = File(...), business_date: str = Form(""), commit: bool = Form(False),
                      db: Session = Depends(get_db), user: str = Depends(current_user)):
    """kind = orders (the system's POS-closed orders) or terminals (one total per terminal).
    commit=false only checks the file; rows with problems are never saved."""
    if kind not in ("orders", "terminals"):
        raise HTTPException(404, "Unknown import")
    default_day = not_future(parse_day(business_date, "business_date")) if business_date else None
    try:
        df = read_upload(file.filename or "", await file.read(1 + 5_000_000))
        rows = (_check_orders if kind == "orders" else _check_terminals)(db, df, default_day)
    except FileProblem as e:
        raise HTTPException(422, str(e))
    if not rows:
        raise HTTPException(422, "The file has a header but no rows")
    saved = 0
    if commit:
        saved = (_save_orders if kind == "orders" else _save_terminals)(db, rows, user, file.filename or "file")
        db.commit()
    counts = {k: sum(r["status"] == k for r in rows) for k in ("new", "update", "same", "skipped", "error")}
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"file": file.filename, "rows": clean, "counts": counts, "committed": commit, "saved": saved,
            "dates": sorted({r["date"] for r in clean if r.get("date")})}
