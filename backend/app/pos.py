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
from . import terminals
from .models import Collection, Driver, PosOrder, PosReview, TerminalTotal, utcnow, iso
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
    # with a terminal sheet for the day, a driver's terminal total is the machines paired with him;
    # without one, it is the POS amount written on his handover
    machines = db.query(TerminalTotal).filter_by(business_date=day).all()
    paired = defaultdict(list)
    for m in machines:
        if m.driver_id:
            paired[m.driver_id].append(m)
    ids = set(orders) | set(handovers) | set(paired)
    drivers = {d.id: d for d in db.query(Driver).filter(Driver.id.in_(ids))} if ids else {}
    rows = []
    for did in sorted(ids, key=lambda i: drivers[i].code):
        d, h = drivers[did], handovers.get(did)
        system, count = orders[did]
        ms = paired.get(did, [])
        if machines:
            terminal = sum(m.amount for m in ms) if ms else None
            label = ", ".join(m.terminal for m in ms) or None
        else:
            terminal = h.pos_amount if h else None
            label = (h.pos_terminal if h and h.pos_terminal else d.pos_terminal) or None
        status = _status(system, terminal, orders_loaded)
        r = reviews.get(did)
        review = None
        if r and status in ("terminal_short", "terminal_over"):
            review = {"status": r.status, "note": r.note, "by": r.decided_by, "at": iso(r.decided_at),
                      "stale": (r.system_total, r.terminal_total) != (system, terminal)}
        rows.append({"driver_id": did, "driver_code": d.code, "driver_name": d.name,
                     "terminal": label, "paired_by": ms[0].paired_by if ms else None,
                     "system_total": to_sar(system), "order_count": count, "terminal_total": to_sar(terminal),
                     "difference": to_sar(terminal - system) if terminal is not None else None,
                     "status": status, "status_text": STATUS_TEXT[status], "review": review,
                     "open": status in ("terminal_short", "terminal_over") and (not review or review["stale"] or review["status"] == "follow_up")})
    return rows


def summarize(rows: list[dict], machines: list | None = None) -> dict:
    """machines: the day's terminal sheet, if there is one. Machines not yet paired with a driver still
    count in the day's machine total, so the day's difference is never hidden."""
    diffs = [r for r in rows if r["status"] in ("terminal_short", "terminal_over")]
    machines = machines or []
    unpaired = to_sar(sum(m.amount for m in machines if not m.driver_id))
    system = round(sum(r["system_total"] for r in rows), 2)
    paired_total = round(sum(r["terminal_total"] or 0 for r in rows), 2)
    machines_total = round(paired_total + unpaired, 2)
    if machines and any(r["order_count"] for r in rows):
        difference = round(machines_total - system, 2)  # every machine of the day against every POS order
    else:
        difference = round(sum(r["difference"] or 0 for r in diffs), 2)
    return {"system_total": system, "terminal_total": paired_total, "difference": difference,
            "sheet": bool(machines), "machines": len(machines), "machines_total": machines_total,
            "unpaired": sum(1 for m in machines if not m.driver_id), "unpaired_total": unpaired,
            "drivers_without_machine": sum(1 for r in rows if r["order_count"] and r["terminal_total"] is None) if machines else 0,
            "order_count": sum(r["order_count"] for r in rows), "drivers": len(rows),
            "agrees": sum(r["status"] == "agrees" for r in rows), "differences": len(diffs),
            "no_terminal": sum(r["status"] == "no_terminal" for r in rows),
            "awaiting": sum(r["status"] == "awaiting_orders" for r in rows),
            "open": sum(r["open"] for r in rows),
            "explained": sum(1 for r in diffs if r["review"] and not r["review"]["stale"] and r["review"]["status"] == "explained"),
            "short": round(-sum(r["difference"] for r in diffs if r["difference"] < 0), 2),
            "over": round(sum(r["difference"] for r in diffs if r["difference"] > 0), 2)}


def day_summary(db: Session, day: date) -> tuple[list[dict], dict]:
    rows = day_rows(db, day)
    return rows, summarize(rows, db.query(TerminalTotal).filter_by(business_date=day).all())


@router.get("")
def pos_day(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    rows, totals = day_summary(db, day)
    return {"date": day.isoformat(), "rows": rows, "totals": totals, "machines": terminals.machine_list(db, day, rows),
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
    "amount": ("actualreceivedamount", "receivedamount", "amount", "codamount", "posamount", "orderamount", "value",
               "collectedamount", "netcashcollectedamount", "total"),
    "date": HANDOVER_COLUMNS["date"] + ("closedate", "closeddate", "deliverydate", "delivereddate"),
    # how the money was actually collected comes before what the customer chose when ordering
    "method": ("collectmethod", "collectionmethod", "collectiontype", "paymentmethod", "paymenttype", "payment",
               "paymentmode", "method", "paidby"),
    "charge": ("chargecategory", "chargetype", "charge", "feetype"),
}
POS_WORDS = ("pos", "card", "mada", "visa", "master", "network", "span", "credit", "debit")
SPLIT_WORDS = ("part", "mixed", "split")  # e.g. "part pos and part cash": the file does not say how much was POS


def is_pos(method: str) -> bool:
    m = method.lower()
    return any(w in m for w in POS_WORDS)


def is_split(method: str) -> bool:
    m = method.lower()
    return any(w in m for w in SPLIT_WORDS) and is_pos(m) and ("cash" in m or "case" in m)
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
    pay_col = find_column(df, ("paymentmethod", "paymenttype", "paymentmode"))  # tells which part a split line is
    if pay_col == cols["method"]:
        pay_col = None
    drivers = {d.code.upper(): d for d in db.query(Driver)}
    nos = [clean_code(v) for v in df[cols["order"]]]
    existing = {o.order_no: o for o in db.query(PosOrder).filter(PosOrder.order_no.in_([n for n in nos if n]))} if nos else {}
    seen: dict[tuple, int] = {}
    out = []
    for i, r in df.iterrows():
        line, problems = i + 2, []
        no = nos[i]
        method = str(r[cols["method"]]).strip() if cols["method"] else ""
        charge = " ".join(str(r[cols["charge"]]).split()) if cols["charge"] else ""
        base = {"line": line, "order_no": no or None, "method": method}
        note = None
        if method and is_split(method):
            # a split payment comes as one line per part; this line's payment method says which part it is
            part = str(r[pay_col]).strip() if pay_col else ""
            if part and not is_split(part):
                note = f"part payment, this line was {part}"
                method = part
            else:
                problems.append(f"collected as '{method}': the file does not say how much of it was POS")
        if method and not is_pos(method) and not problems:
            out.append({**base, "status": "skipped", "problems": [note or f"collected by {method}, not POS"], "driver_code": None,
                        "driver_name": "", "date": None, "amount": None})
            continue
        code = clean_code(r[cols["driver"]])
        day = _row_day(r, cols["date"], default_day, problems)
        drv = drivers.get(code)
        if not no:
            problems.append("no order number")
        elif (no, charge) in seen:  # the same order twice is fine for different charges (COD and VAT), not for the same one
            problems.append(f"order repeated, first on row {seen[(no, charge)]}")
        else:
            seen[(no, charge)] = line
        if not code:
            problems.append("no driver ID")
        elif not drv:
            problems.append(f"unknown driver {code}")
        amount = _amount(r[cols["amount"]], problems)
        status = "error" if problems else "ok"
        if note and not problems:
            problems = [note]  # shown as a note on a good row
        out.append({**base, "status": status, "problems": problems, "driver_code": code or None,
                    "driver_name": drv.name if drv else "", "date": day.isoformat() if day else None,
                    "amount": to_sar(amount), "charge": charge, "_driver": drv, "_day": day, "_amount": amount})

    # one order can have several POS lines (COD and Import VAT): they are added together into one order
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in out:
        if r["status"] == "ok":
            groups[r["order_no"]].append(r)
    for no, rows in groups.items():
        head = rows[0]
        if len({(x["driver_code"], x["date"]) for x in rows}) > 1:
            for x in rows:
                x["status"] = "error"
                x["problems"].append("the same order has different drivers or dates in this file")
            continue
        total = sum(x["_amount"] for x in rows)
        status = "new"
        if no in existing:
            o = existing[no]
            status = "same" if (o.driver_id, o.business_date, o.amount) == (head["_driver"].id, head["_day"], total) else "update"
        for x in rows:
            x["status"], x["_head"] = status, x is head
        head["_amount"] = total
        if len(rows) > 1:
            head["problems"] = head["problems"][:1] if head["problems"] and head["problems"][0].startswith("part payment") else []
            head["problems"] += [f"order total {to_sar(total):,.2f} with row {', '.join(str(x['line']) for x in rows[1:])}"]
            for x in rows[1:]:
                x["problems"] = [f"added to row {head['line']}, same order ({x['charge'] or 'another charge'})"]
    return out


def _save_orders(db: Session, rows, user: str, filename: str) -> int:
    saved, per_day = 0, defaultdict(lambda: [0, 0])
    for r in rows:
        if r["status"] not in ("new", "update") or not r.get("_head", True):
            continue  # the other lines of an order are already in its head row's total
        o = db.query(PosOrder).filter_by(order_no=r["order_no"]).first()
        if o:
            audit.record(db, user, "updated", "pos_order", o.id,
                         f"Order {o.order_no} changed by import {filename}: {o.driver.code} {o.business_date.isoformat()} "
                         f"{to_sar(o.amount):,.2f} -> {r['driver_code']} {r['date']} {to_sar(r['_amount']):,.2f}")
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


@router.post("/import/{kind}")
async def import_file(kind: str, file: UploadFile = File(...), business_date: str = Form(""), commit: bool = Form(False),
                      db: Session = Depends(get_db), user: str = Depends(current_user)):
    """kind = orders (the system's POS-closed orders) or terminals (one total per terminal).
    commit=false only checks the file; rows with problems are never saved."""
    if kind not in ("orders", "terminals"):
        raise HTTPException(404, "Unknown import")
    default_day = not_future(parse_day(business_date, "business_date")) if business_date else None
    try:
        df = read_upload(file.filename or "", await file.read(1 + 5_000_000), keep_unnamed=kind == "terminals")
        rows = (_check_orders if kind == "orders" else terminals.check_sheet)(db, df, default_day)
    except FileProblem as e:
        raise HTTPException(422, str(e))
    if not rows:
        raise HTTPException(422, "The file has a header but no rows")
    saved = 0
    if commit:
        saved = (_save_orders if kind == "orders" else terminals.save_sheet)(db, rows, user, file.filename or "file")
        if kind == "orders":  # new system orders can complete the pairing of that day's machines
            db.flush()
            for d in sorted({r["_day"] for r in rows if r.get("_day")}):
                if db.query(TerminalTotal).filter_by(business_date=d).count():
                    terminals.auto_pair(db, d, user)
        db.commit()
    counts = {k: sum(r["status"] == k for r in rows) for k in ("new", "update", "same", "skipped", "error")}
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"file": file.filename, "rows": clean, "counts": counts, "committed": commit, "saved": saved,
            "dates": sorted({r["date"] for r in clean if r.get("date")})}
