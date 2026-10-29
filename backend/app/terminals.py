"""POS machines and their daily totals from the terminal sheet.

POS machines move between drivers from day to day, and the finance desk is not always told who had
which one. So each day's machine is matched to a driver in this order:
1. the machine is registered to a driver on the Drivers page, or was recorded on his handover that day;
2. its total is exactly one driver's system POS total, and no other machine or driver has that amount;
3. the person picks the driver. The drivers with the closest system totals are suggested.
A pair holds for that day only."""
import re
from collections import Counter, defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import audit
from .collections import COLUMNS as HANDOVER_COLUMNS, MAX_AMOUNT
from .database import get_db
from .deps import current_user
from .files import FileProblem, clean_code, find_column, find_header, header_day, read_date
from .models import Collection, Driver, PosOrder, TerminalTotal
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/pos", tags=["pos"])

TERMINAL_COLUMNS = {
    "terminal": ("terminalid", "terminalno", "terminalnumber", "terminal", "tid", "posterminal", "posid", "posterminalid",
                 "poscode", "posno", "posnumber", "terminalcode", "machineid", "machineno", "machine"),
    "amount": ("totalamount", "amount", "total", "settledamount", "netamount", "posamount", "totalsales", "sales"),
    "date": HANDOVER_COLUMNS["date"] + ("settlementdate", "transactiondate"),
}
PAIRED_TEXT = {"terminal": "registered machine", "amount": "same amount", "hand": "chosen by hand"}
TERMINAL_OK = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,29}$")


def system_totals(db: Session, day: date) -> dict[int, int]:
    return {d: int(t) for d, t in db.query(PosOrder.driver_id, func.sum(PosOrder.amount))
            .filter(PosOrder.business_date == day).group_by(PosOrder.driver_id)}


def owners(db: Session, day: date) -> dict[str, int]:
    """Machines whose driver is known: registered on the Drivers page, or recorded on that day's handover."""
    out = {d.pos_terminal: d.id for d in db.query(Driver).filter(Driver.active.is_(True), Driver.pos_terminal != "")}
    out.update({c.pos_terminal: c.driver_id for c in db.query(Collection).filter(
        Collection.business_date == day, Collection.pos_terminal != "")})
    return out


def plan_pairs(machines: list[tuple[str, int]], system: dict[int, int], owner: dict[str, int],
               taken: set[int]) -> dict[str, tuple[int, str]]:
    """machines: (terminal, amount) still without a driver. system: driver id -> system POS total.
    taken: drivers that already have a machine that day. Returns terminal -> (driver id, how)."""
    plan = {t: (owner[t], "terminal") for t, _ in machines if t in owner}
    used = taken | {d for d, _ in plan.values()}
    left = [(t, a) for t, a in machines if t not in plan]
    free = {d: s for d, s in system.items() if d not in used and s > 0}
    machines_at = Counter(a for _, a in left)
    drivers_at = Counter(free.values())
    for t, a in left:
        if machines_at[a] == 1 and drivers_at[a] == 1:  # one machine and one driver with this exact amount
            plan[t] = (next(d for d, s in free.items() if s == a), "amount")
    return plan


def sync_handovers(db: Session, day: date, user: str):
    """A handover's POS amount is the total of the machines paired with that driver."""
    machines = db.query(TerminalTotal).filter_by(business_date=day).all()
    if not machines:
        return
    paired = defaultdict(list)
    for m in machines:
        if m.driver_id:
            paired[m.driver_id].append(m)
    for h in db.query(Collection).filter_by(business_date=day):
        ms = paired.get(h.driver_id, [])
        total = sum(m.amount for m in ms)
        if h.pos_amount != total:
            audit.record(db, user, "updated", "collection", h.id,
                         f"{h.driver.code} on {day.isoformat()} POS {to_sar(h.pos_amount):,.2f} -> {to_sar(total):,.2f} "
                         f"(machines {', '.join(m.terminal for m in ms) or 'none'})")
            h.pos_amount = total
        if ms:
            h.pos_terminal = ms[0].terminal


def auto_pair(db: Session, day: date, user: str) -> int:
    """Pair the day's machines that can be paired for certain. A pair made by amount that no longer
    matches (the system orders changed) is released first. Returns how many machines were paired."""
    system = system_totals(db, day)
    machines = db.query(TerminalTotal).filter_by(business_date=day).all()
    for m in machines:
        if m.paired_by == "amount" and system.get(m.driver_id) != m.amount:
            m.driver_id, m.paired_by = None, ""
    taken = {m.driver_id for m in machines if m.driver_id}
    free = [m for m in machines if not m.driver_id]
    plan = plan_pairs([(m.terminal, m.amount) for m in free], system, owners(db, day), taken)
    how = Counter()
    for m in free:
        if m.terminal in plan:
            m.driver_id, m.paired_by = plan[m.terminal]
            how[m.paired_by] += 1
    if how:
        audit.record(db, user, "paired", "terminal", None,
                     f"POS machines on {day.isoformat()} paired with drivers: "
                     + ", ".join(f"{n} by {PAIRED_TEXT[k]}" for k, n in sorted(how.items())))
    db.flush()
    sync_handovers(db, day, user)
    return sum(how.values())


def machine_list(db: Session, day: date, rows: list[dict]) -> list[dict]:
    """The day's machines. A machine without a driver gets the drivers whose system POS total is closest,
    among those with POS orders and no machine yet."""
    waiting = [r for r in rows if r["order_count"] and r["terminal_total"] is None]
    out = []
    for m in (db.query(TerminalTotal).filter_by(business_date=day)
              .order_by(TerminalTotal.driver_id.isnot(None), TerminalTotal.terminal)):
        amount = to_sar(m.amount)
        item = {"id": m.id, "terminal": m.terminal, "amount": amount, "driver_id": m.driver_id,
                "driver_code": m.driver.code if m.driver else None, "driver_name": m.driver.name if m.driver else None,
                "paired_by": m.paired_by or None, "suggestions": []}
        if not m.driver_id:
            near = sorted(waiting, key=lambda r: (abs(r["system_total"] - amount), r["driver_code"]))[:3]
            item["suggestions"] = [{"driver_id": r["driver_id"], "driver_code": r["driver_code"], "driver_name": r["driver_name"],
                                    "system_total": r["system_total"], "difference": round(amount - r["system_total"], 2)}
                                   for r in near]
        out.append(item)
    return out


class PairIn(BaseModel):
    driver_id: int | None = None


@router.put("/machines/{machine_id}")
def pair(machine_id: int, body: PairIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    m = db.get(TerminalTotal, machine_id)
    if not m:
        raise HTTPException(404, "This machine total does not exist")
    before = m.driver.code if m.driver else "no driver"
    if body.driver_id is None:
        m.driver_id, m.paired_by = None, ""
        after = "no driver"
    else:
        d = db.get(Driver, body.driver_id)
        if not d:
            raise HTTPException(404, "Driver not found")
        m.driver_id, m.paired_by = d.id, "hand"
        after = d.code
    db.flush()
    db.refresh(m)
    audit.record(db, user, "paired", "terminal", m.id,
                 f"Machine {m.terminal} on {m.business_date.isoformat()} ({to_sar(m.amount):,.2f}): {before} -> {after}")
    sync_handovers(db, m.business_date, user)
    db.commit()
    return {"id": m.id, "driver_id": m.driver_id, "paired_by": m.paired_by or None}


@router.delete("/machines/{machine_id}")
def remove(machine_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Remove a machine total typed or imported by mistake. A matched machine is unmatched first."""
    m = db.get(TerminalTotal, machine_id)
    if not m:
        raise HTTPException(404, "This machine total does not exist")
    if m.driver_id:
        raise HTTPException(409, "Undo the match with the driver first, then remove the machine")
    day = m.business_date
    audit.record(db, user, "deleted", "terminal", m.id, f"Machine {m.terminal} on {day.isoformat()} ({to_sar(m.amount):,.2f}) removed")
    db.delete(m)
    db.flush()
    sync_handovers(db, day, user)
    db.commit()
    return {"removed": True}


# ---------------------------------------------------------------- the terminal sheet

def _amount(raw, problems: list[str]) -> int | None:
    """None means the cell is empty (the machine was not used that day)."""
    if not str(raw).strip():
        return None
    h = to_halalas(raw)
    if h is None:
        problems.append(f"amount '{raw}' is not a number")
        return 0
    if h < 0 or h > MAX_AMOUNT:
        problems.append("amount is out of range")
    return h


def check_sheet(db: Session, df, default_day: date | None) -> list[dict]:
    """Two layouts are read: one row per machine with Terminal ID, Total amount (and Date), or a sheet
    with one column per day whose heading is the date (27-Oct), with title or total lines above it."""
    df, above = find_header(df, TERMINAL_COLUMNS["terminal"])
    df = df.loc[:, [str(c).strip() != "" and not str(c).startswith("Unnamed") for c in df.columns]]
    tcol = find_column(df, TERMINAL_COLUMNS["terminal"])
    if not tcol:
        raise FileProblem("The file needs a Terminal ID or POS Code column. Download the template to see the layout")
    acol, dcol, fixed = find_column(df, TERMINAL_COLUMNS["amount"]), find_column(df, TERMINAL_COLUMNS["date"]), None
    if not acol:
        year = (default_day or date.today()).year
        day_cols = [(c, header_day(c, year)) for c in df.columns if c != tcol]
        day_cols = [(c, d) for c, d in day_cols if d]
        if not day_cols:
            raise FileProblem("The file needs a Total amount column, or one column per day with the date as its heading")
        chosen = [(c, d) for c, d in day_cols if d == default_day]
        if chosen:
            day_cols = chosen
        elif len(day_cols) > 1:
            raise FileProblem("The sheet has a column for each of " + ", ".join(d.strftime("%d %b") for _, d in day_cols)
                              + ". Choose one of these days in the date strip first")
        acol, fixed = day_cols[0]
    elif not dcol and not default_day:
        raise FileProblem("The file has no Date column, so choose the business date first")

    existing = {(m.business_date, m.terminal): m for m in db.query(TerminalTotal)}
    seen: dict[tuple, int] = {}
    out = []
    for i, r in df.iterrows():
        line, problems, notes = i + 2 + above, [], []
        terminal = clean_code(r[tcol]).replace(" ", "")
        raw_amount = r[acol]
        if not terminal and not str(raw_amount).strip():
            continue  # an empty row
        day = fixed
        if not day:
            day = read_date(r[dcol]) if dcol and str(r[dcol]).strip() else default_day
            if day is None:
                problems.append("date not readable")
        if day and day > date.today():
            problems.append("date is in the future")
        amount = _amount(raw_amount, problems)
        status = None
        if "TOTAL" in terminal:
            status, notes = "skipped", ["a total line, not a machine"]
        elif not terminal:
            problems.append("no terminal ID")
        elif not TERMINAL_OK.match(terminal):
            problems.append(f"terminal ID '{terminal}' can only use letters, numbers and dashes")
        elif amount is None or (amount == 0 and not problems):
            status, notes = "skipped", ["no amount on this machine for the day"]
        elif day:
            if (day, terminal) in seen:
                problems.append(f"terminal repeated, first on row {seen[(day, terminal)]}")
            else:
                seen[(day, terminal)] = line
        old = existing.get((day, terminal)) if day else None
        if problems:
            status = "error"
        elif not status:
            status = "new" if not old else ("same" if old.amount == amount else "update")
        out.append({"line": line, "status": status, "problems": problems + notes, "terminal": terminal or None,
                    "date": day.isoformat() if day else None, "amount": to_sar(amount or 0),
                    "previous": to_sar(old.amount) if old else None,
                    "driver_code": None, "driver_name": "", "paired_by": None,
                    "_day": day, "_amount": amount or 0, "_old": old})
    _preview_pairs(db, out)
    return out


def _preview_pairs(db: Session, rows: list[dict]):
    """Show in the check which driver each machine will be paired with, without saving anything."""
    by_day = defaultdict(list)
    for r in rows:
        if r["status"] in ("new", "update", "same"):
            by_day[r["_day"]].append(r)
    drivers = {d.id: d for d in db.query(Driver)}
    for day, day_rows in by_day.items():
        in_file = {r["terminal"] for r in day_rows}
        kept, free = {}, []
        for r in day_rows:
            old = r["_old"]
            if old and old.driver_id and not (old.paired_by == "amount" and r["status"] == "update"):
                kept[r["terminal"]] = (old.driver_id, old.paired_by)
            else:
                free.append((r["terminal"], r["_amount"]))
        taken = {d for d, _ in kept.values()} | {m.driver_id for m in db.query(TerminalTotal).filter(
            TerminalTotal.business_date == day, TerminalTotal.driver_id.isnot(None)) if m.terminal not in in_file}
        plan = {**kept, **plan_pairs(free, system_totals(db, day), owners(db, day), taken)}
        for r in day_rows:
            if r["terminal"] in plan:
                d = drivers[plan[r["terminal"]][0]]
                r.update(driver_code=d.code, driver_name=d.name, paired_by=plan[r["terminal"]][1])
            else:
                r["problems"].append("no driver with the same amount: choose the driver on the POS check page")


def save_sheet(db: Session, rows: list[dict], user: str, filename: str) -> int:
    saved, days = 0, set()
    for r in rows:
        if r["status"] == "new":
            db.add(TerminalTotal(business_date=r["_day"], terminal=r["terminal"], amount=r["_amount"], created_by=user))
        elif r["status"] == "update":
            m = r["_old"]
            audit.record(db, user, "updated", "terminal", m.id, f"Machine {m.terminal} on {m.business_date.isoformat()} "
                         f"{to_sar(m.amount):,.2f} -> {to_sar(r['_amount']):,.2f} (import {filename})")
            m.amount = r["_amount"]
        else:
            continue
        saved += 1
        days.add(r["_day"])
    db.flush()
    for day in sorted(days):
        n = sum(1 for r in rows if r["_day"] == day and r["status"] in ("new", "update"))
        total = sum(r["_amount"] for r in rows if r["_day"] == day and r["status"] in ("new", "update", "same"))
        audit.record(db, user, "imported", "terminal", None,
                     f"Terminal sheet {filename} for {day.isoformat()}: {n} machine totals saved, sheet total {to_sar(total):,.2f}")
        auto_pair(db, day, user)
    return saved
