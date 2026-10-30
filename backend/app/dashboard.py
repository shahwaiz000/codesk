"""One business day at a glance, plus the things that need attention across all days.

Everything is computed from the stored records with the same functions the other pages use,
so a number on the dashboard always matches the page it links to."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import pos, unusual, scope
from .collections import day_totals
from .database import get_db
from .deposits import ledger, by_day
from .deps import parse_day
from .models import Station, Collection, Driver, Expense, ImportedFile, PosOrder, TerminalTotal
from .money import to_sar
from .seed import business_days

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

OLD_ADVANCE_DAYS = 14


def previous_day_with_data(db: Session, day: date) -> date | None:
    return db.query(func.max(Collection.business_date)).filter(Collection.business_date < day).scalar()


def day_figures(db: Session, day: date, deposit_rows: dict) -> dict:
    handovers = db.query(Collection).filter_by(business_date=day).all()
    c = day_totals(handovers)
    _, p = pos.day_summary(db, day)
    spent = dict(db.query(Expense.category == "advance", func.sum(Expense.amount))
                 .filter(Expense.business_date == day).group_by(Expense.category == "advance").all())
    d = deposit_rows.get(day.isoformat())
    return {
        "cash_received": c["cash_received"], "expected_cash": c["expected_cash"],
        "cash_short": c["short"], "cash_over": c["over"], "short_count": c["short_count"], "over_count": c["over_count"],
        "pos_terminal": p["machines_total"], "pos_system": p["system_total"], "pos_difference": p["difference"],
        "pos_open": p["open"], "pos_differences": p["differences"], "pos_awaiting": p["awaiting"],
        "total_collected": round(c["cash_received"] + p["machines_total"], 2), "orders": c["orders"], "drivers": c["drivers"],
        "expenses": to_sar(int(spent.get(False) or 0)), "advances": to_sar(int(spent.get(True) or 0)),
        "paid_out": d["paid_out"] if d else 0.0, "returned": d["returned"] if d else 0.0,
        "to_deposit": d["to_deposit"] if d else 0.0, "deposited": d["deposited"] if d else 0.0,
        "pending": d["pending"] if d else 0.0, "deposit_status": d["status"] if d else "nothing",
        "deposit_status_text": d["status_text"] if d else "Nothing to deposit", "due_on": d["due_on"] if d else None,
        # the running balance: what earlier days left unbanked, what the cashier had to deposit in all, what is still left
        "brought_forward": d.get("brought_forward", 0.0) if d else 0.0, "total_due": d.get("total_due", 0.0) if d else 0.0,
        "left": d.get("left", 0.0) if d else 0.0,
    }


@router.get("/month")
def month(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    """The month so far, from the 1st up to the chosen day: for the station being looked at (or all)."""
    day = parse_day(date_)
    first = day.replace(day=1)
    days = sorted({d for (d,) in db.query(Collection.business_date).filter(Collection.business_date.between(first, day)).distinct()})
    rows = [r for r in ledger(db, date.today()) if first.isoformat() <= r["date"] <= day.isoformat()]
    handovers = db.query(Collection).filter(Collection.business_date.between(first, day)).all()
    short = [h for h in handovers if h.cash_received < h.expected_cash]
    pos_short = pos_count = pos_open = 0
    machines = system = 0.0
    for d in days:
        _, p = pos.day_summary(db, d)
        machines += p["machines_total"]
        system += p["system_total"]
        if p["system_total"] and p["machines_total"] and abs(p["difference"]) >= 0.01:  # the sheet against the system, per day
            pos_count += 1
            pos_open += 1
    late = [r for r in rows if r["status"] in ("overdue", "short")]
    add = lambda k: round(sum(r[k] for r in rows), 2)  # noqa: E731
    return {
        "start": first.isoformat(), "end": day.isoformat(), "working_days": len(days),
        "cash_received": add("cash_received"), "pos": round(machines, 2), "pos_difference": round(machines - system, 2),
        "pos_differences": pos_count, "pos_open": pos_open,
        "paid_out": round(add("paid_out") - add("returned"), 2), "to_deposit": add("to_deposit"), "deposited": add("deposited"),
        "not_deposited": round(sum(r["pending"] for r in rows if r["pending"] > 0), 2),
        "late_days": len(late), "late_amount": round(sum(r["pending"] for r in late), 2),
        "late_dates": [r["date"] for r in sorted(late, key=lambda r: r["date"])],
        # the cashier's mistakes: put less in the bank than the cash received, or did not deposit on time
        "deposit_short_days": len([r for r in rows if r["status"] == "short"]),
        "deposit_short": round(sum(r["pending"] for r in rows if r["status"] == "short"), 2),
        "deposit_short_dates": sorted(r["date"] for r in rows if r["status"] == "short"),
        "deposit_overdue_days": len([r for r in rows if r["status"] == "overdue"]),
        "deposit_overdue": round(sum(r["pending"] for r in rows if r["status"] == "overdue"), 2),
        "deposit_overdue_dates": sorted(r["date"] for r in rows if r["status"] == "overdue"),
        "short_paid_later": len([r for r in rows if r.get("paid_later_on")]),
        "cash_short": to_sar(sum(h.expected_cash - h.cash_received for h in short)), "cash_short_count": len(short),
    }


@router.get("")
def dashboard(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    today = date.today()
    all_deposits = ledger(db, today)
    by_date = {r["date"]: r for r in by_day(all_deposits)}
    figures = day_figures(db, day, by_date)
    prev = previous_day_with_data(db, day)
    previous = day_figures(db, prev, by_date) if prev else None
    active = scope.drivers(db).filter(Driver.active.is_(True)).count()

    # drivers with something wrong on this day
    people = {}
    for h in db.query(Collection).filter_by(business_date=day):
        if h.cash_received != h.expected_cash:
            people.setdefault(h.driver_id, {"driver_code": h.driver.code, "driver_name": h.driver.name, "issues": []})["issues"].append(
                {"kind": "cash_short" if h.cash_received < h.expected_cash else "cash_over",
                 "amount": to_sar(h.cash_received - h.expected_cash), "page": "/collections"})
    for r in pos.day_rows(db, day):
        if r["status"] in ("terminal_short", "terminal_over"):
            people.setdefault(r["driver_id"], {"driver_code": r["driver_code"], "driver_name": r["driver_name"], "issues": []})["issues"].append(
                {"kind": r["status"], "amount": r["difference"], "page": "/pos", "explained": not r["open"]})
    attention = sorted(people.values(), key=lambda p: p["driver_code"])

    # problems across all days, newest first
    alerts = []
    for r in all_deposits:
        if r["status"] in ("overdue", "short", "over"):
            alerts.append({"kind": f"deposit_{r['status']}", "date": r["date"], "amount": r["pending"], "page": "/deposits",
                           "text": scope.named(r, {"overdue": "Cash not deposited, overdue",
                                                   "short": "Bank deposit short",
                                                   "over": "Deposit more than the cash"}[r["status"]])})
    since = today - timedelta(days=45)
    pos_days = [d for (d,) in db.query(PosOrder.business_date).filter(PosOrder.business_date >= since).distinct()]
    pos_days += [d for (d,) in db.query(Collection.business_date).filter(Collection.business_date >= since,
                                                                          Collection.pos_amount > 0).distinct()]
    pos_days += [d for (d,) in db.query(TerminalTotal.business_date).filter(TerminalTotal.business_date >= since).distinct()]
    # the supervisor checks each station's card machine sheet against the system's card payments, as day totals
    from .scope import current_station
    looking = current_station.get()
    for d in sorted(set(pos_days), reverse=True):
        ids = [looking] if looking is not None else sorted(
            {s for (s,) in db.query(Collection.station_id).filter(Collection.business_date == d).distinct()} - {None}) or [None]
        for sid in ids:
            token = current_station.set(sid)
            try:
                _, p = pos.day_summary(db, d)
            finally:
                current_station.reset(token)
            if p["system_total"] and p["machines_total"] and abs(p["difference"]) >= 0.01:
                name = db.get(Station, sid).name if sid and looking is None else ""
                alerts.append({"kind": "pos_sheet", "date": d.isoformat(), "amount": p["difference"], "page": "/pos",
                               "text": "Card machine sheet differs from the system" + (f" ({name})" if name else "")})
    for e in (db.query(Expense).filter(Expense.category == "advance", Expense.settled_on.is_(None),
                                       Expense.business_date <= today - timedelta(days=OLD_ADVANCE_DAYS))
              .order_by(Expense.business_date)):
        alerts.append({"kind": "advance_old", "date": e.business_date.isoformat(), "amount": to_sar(e.amount), "page": "/expenses",
                       "text": f"Advance to {e.driver.code} open for {(today - e.business_date).days} days"})
    for f in (db.query(ImportedFile).filter(ImportedFile.status.in_(("failed", "attention")), ImportedFile.at >= since)
              .order_by(ImportedFile.id.desc()).limit(5)):
        alerts.append({"kind": f"file_{f.status}", "date": f.at.date().isoformat(), "amount": 0, "page": "/settings",
                       "text": f"{f.filename}: " + ("could not be imported" if f.status == "failed" else "some rows were left out")})
    for a in unusual.find(db, since, today):
        alerts.append({"kind": a["kind"], "date": a["date"], "amount": a["amount"], "page": a["page"], "text": a["text"]})
    alerts.sort(key=lambda a: a["date"], reverse=True)

    # last 30 working days ending on the chosen day
    days = list(reversed(business_days(day, 30)))
    cash = dict(db.query(Collection.business_date, func.sum(Collection.cash_received))
                .filter(Collection.business_date.between(days[0], days[-1])).group_by(Collection.business_date))
    card = dict(db.query(Collection.business_date, func.sum(Collection.pos_amount))
                .filter(Collection.business_date.between(days[0], days[-1])).group_by(Collection.business_date))
    card.update(db.query(TerminalTotal.business_date, func.sum(TerminalTotal.amount))  # a terminal sheet wins
                .filter(TerminalTotal.business_date.between(days[0], days[-1])).group_by(TerminalTotal.business_date))
    trend = [{"date": d.isoformat(), "cash": to_sar(int(cash.get(d) or 0)), "pos": to_sar(int(card.get(d) or 0)),
              "deposit_status": by_date.get(d.isoformat(), {}).get("status", "nothing")} for d in days]

    pending_total = round(sum(r["pending"] for r in all_deposits if r["pending"] > 0), 2)
    return {"date": day.isoformat(), "previous_date": prev.isoformat() if prev else None,
            "figures": figures, "previous": previous, "active_drivers": active,
            "cash_on_hand": pending_total, "attention": attention, "alerts": alerts[:12], "alert_count": len(alerts),
            "alert_kinds": {k: sum(a["kind"] == k for a in alerts) for k in sorted({a["kind"] for a in alerts})},
            "trend": trend}
