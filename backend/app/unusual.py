"""Unusual amounts: CODesk learns what is normal from the desk's own history and points out what is not.

No outside service and no model to train: "normal" is the median of past amounts (the middle value, which
one odd payment cannot pull up), and an amount is unusual when it is several times that. Three checks:

    expense    one payment much bigger than usual: the driver's own usual for that kind of expense when he
               has a history, otherwise the desk's usual for that kind (advances are left out: they are big
               by nature and tracked on their own)
    payout     a day's total paid out (without advances) much bigger than a usual day
    pos        a driver whose POS machine disagreed with his orders on several of his recent days

An alert can be marked "looks fine" with a note, so it stops coming back."""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit, pos
from .database import get_db
from .deps import current_user, parse_day
from .expenses import CATEGORY_TEXT
from .models import Expense, PosOrder, TerminalTotal, UnusualReview, utcnow
from .money import to_sar

router = APIRouter(prefix="/api/unusual", tags=["unusual"])

HISTORY_DAYS = 90       # what "usual" is learned from
TIMES = 3.0             # an amount this many times the usual is unusual
MIN_GAP = 5000          # and at least 50 SAR above it, so small amounts never alarm
MIN_DRIVER = 3          # past payments of the same kind before a driver has his own "usual"
MIN_DESK = 8            # past payments of the same kind before the desk has a "usual"
MIN_DAYS = 5            # past days before a "usual day" exists
POS_WINDOW = 10         # a driver's recent POS days looked at
POS_TIMES = 3           # how many of them may disagree before it is a pattern
POS_MIN = 100           # a disagreement smaller than 1 SAR is rounding, not a pattern


def _expense_alerts(db: Session, first: date, last: date) -> list[dict]:
    start = first - timedelta(days=HISTORY_DAYS)
    rows = (db.query(Expense).filter(Expense.business_date.between(start, last), Expense.category != "advance")
            .order_by(Expense.business_date, Expense.id).all())
    out = []
    for e in rows:
        if e.business_date < first:
            continue
        past = [x for x in rows if x.business_date < e.business_date and x.business_date >= e.business_date - timedelta(days=HISTORY_DAYS)
                and x.category == e.category]
        mine = [x.amount for x in past if x.driver_id == e.driver_id]
        if len(mine) >= MIN_DRIVER:
            usual, whose = median(mine), "his usual"
        elif len(past) >= MIN_DESK:
            usual, whose = median(x.amount for x in past), f"the usual {CATEGORY_TEXT[e.category].lower()} payment"
        else:
            continue
        if usual > 0 and e.amount >= usual * TIMES and e.amount - usual >= MIN_GAP:
            ratio = e.amount / usual
            out.append({"key": f"expense:{e.id}", "kind": "unusual_expense", "date": e.business_date.isoformat(),
                        "driver_code": e.driver.code, "driver_name": e.driver.name, "amount": to_sar(e.amount),
                        "usual": to_sar(int(usual)), "ratio": round(ratio, 1), "page": "/expenses", "expense_id": e.id,
                        "text": f"{CATEGORY_TEXT[e.category]} {to_sar(e.amount):,.2f} to {e.driver.code}: "
                                f"{ratio:.1f}x {whose} ({to_sar(int(usual)):,.2f})"})
    return out


def _payout_alerts(db: Session, first: date, last: date) -> list[dict]:
    start = first - timedelta(days=HISTORY_DAYS)
    totals = defaultdict(int)
    for e in db.query(Expense).filter(Expense.business_date.between(start, last), Expense.category != "advance"):
        totals[e.business_date] += e.amount
    out = []
    for day in sorted(d for d in totals if d >= first):
        past = [v for d, v in totals.items() if d < day and d >= day - timedelta(days=HISTORY_DAYS)]
        if len(past) < MIN_DAYS:
            continue
        usual = median(past)
        if usual > 0 and totals[day] >= usual * TIMES and totals[day] - usual >= MIN_GAP:
            ratio = totals[day] / usual
            out.append({"key": f"payout:{day.isoformat()}", "kind": "unusual_payout", "date": day.isoformat(),
                        "driver_code": None, "driver_name": None, "amount": to_sar(totals[day]), "usual": to_sar(int(usual)),
                        "ratio": round(ratio, 1), "page": "/expenses",
                        "text": f"Paid out {to_sar(totals[day]):,.2f} in one day: {ratio:.1f}x a usual day ({to_sar(int(usual)):,.2f})"})
    return out


def _pos_alerts(db: Session, first: date, last: date) -> list[dict]:
    days = sorted({d for (d,) in db.query(PosOrder.business_date).filter(PosOrder.business_date <= last).distinct()}
                  | {d for (d,) in db.query(TerminalTotal.business_date).filter(TerminalTotal.business_date <= last).distinct()})
    days = days[-(POS_WINDOW * 3):]  # enough recent days to see each driver's last POS_WINDOW days
    by_driver = defaultdict(list)
    for d in days:
        for r in pos.day_rows(db, d):
            if r["status"] in ("agrees", "terminal_short", "terminal_over"):
                by_driver[r["driver_id"]].append((d, r))
    out = []
    for rows in by_driver.values():
        recent = rows[-POS_WINDOW:]
        off = [(d, r) for d, r in recent if r["difference"] and abs(r["difference"]) * 100 >= POS_MIN]
        if len(off) < POS_TIMES or off[-1][0] < first:
            continue
        d, r = off[-1]
        total = round(sum(x["difference"] for _, x in off), 2)
        out.append({"key": f"pos:{r['driver_id']}:{d.isoformat()}", "kind": "unusual_pos", "date": d.isoformat(),
                    "driver_code": r["driver_code"], "driver_name": r["driver_name"], "amount": total, "usual": None,
                    "ratio": None, "page": "/pos",
                    "text": f"{r['driver_code']}'s POS machine disagreed on {len(off)} of his last {len(recent)} days "
                            f"({total:+,.2f} in all)"})
    return out


def find(db: Session, first: date, last: date, include_reviewed: bool = False) -> list[dict]:
    """Unusual amounts on the days from first to last, newest first. Reviewed ones are left out."""
    found = _expense_alerts(db, first, last) + _payout_alerts(db, first, last) + _pos_alerts(db, first, last)
    reviewed = {r.key: r for r in db.query(UnusualReview)}
    out = []
    for a in found:
        r = reviewed.get(a["key"])
        if r and not include_reviewed:
            continue
        a["review"] = {"note": r.note, "by": r.decided_by} if r else None
        out.append(a)
    return sorted(out, key=lambda a: (a["date"], a["key"]), reverse=True)


@router.get("")
def for_day(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    return find(db, day, day, include_reviewed=True)


class ReviewIn(BaseModel):
    key: str = Field(min_length=3, max_length=80)
    note: str = Field("", max_length=300)


@router.post("/review")
def review(body: ReviewIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Mark an unusual amount as looked at ("looks fine"), so it stops showing on the dashboard."""
    if db.get(UnusualReview, body.key):
        raise HTTPException(409, "This one is already marked")
    note = " ".join(body.note.split())
    db.add(UnusualReview(key=body.key, note=note, decided_by=user, decided_at=utcnow()))
    audit.record(db, user, "reviewed", "unusual", None, f"Unusual amount {body.key} marked as looked at" + (f": {note}" if note else ""))
    db.commit()
    return {"reviewed": True}
