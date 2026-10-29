"""Bank deposits: each business day's cash goes to the bank on the next working day.

    cash to deposit = cash received from drivers
                      - expenses and advances paid out that day
                      + advances returned in cash that day

A day can be deposited with more than one slip. Cash goes in as notes, so a day deposited to within
a few riyals (the halalas left, or a slip rounded up to the next note) counts as deposited. A day is overdue when money is still pending after
its deposit day, and short when slips were recorded but they add up to less than the cash to deposit."""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import audit
from .collections import MAX_AMOUNT
from .database import get_db
from .deps import current_user, not_future, parse_day
from .models import Collection, Deposit, Expense
from .money import to_halalas, to_sar
from .seed import business_days, next_working_day

router = APIRouter(prefix="/api/deposits", tags=["deposits"])

STATUS_TEXT = {"deposited": "Deposited", "not_due": "Cash on hand", "due_today": "Due today", "overdue": "Overdue",
               "short": "Deposit short", "over": "Deposited too much", "nothing": "Nothing to deposit"}


# Cash goes to the bank in notes: the halalas of a day cannot be deposited, and a slip is often rounded
# up to the next note. A day deposited within these limits counts as deposited, and the gap is shown as rounding.
ROUND_DOWN = 100  # up to 0.99 SAR left over
ROUND_UP = 500    # up to 4.99 SAR more on the slip


def rounded(to_deposit: int, deposited: int) -> bool:
    return deposited > 0 and -ROUND_UP < to_deposit - deposited < ROUND_DOWN


def status_for(day: date, to_deposit: int, deposited: int, today: date) -> str:
    pending = to_deposit - deposited
    if pending and rounded(to_deposit, deposited):
        return "deposited"
    if pending < 0:
        return "over"
    if pending == 0:
        return "deposited" if deposited else "nothing"
    due = next_working_day(day)
    if today < due:
        return "not_due"
    if deposited:
        return "short"
    return "due_today" if today == due else "overdue"


def ledger(db: Session, today: date | None = None) -> list[dict]:
    """Every business day that has money in or out, newest first."""
    today = today or date.today()
    cash = dict(db.query(Collection.business_date, func.sum(Collection.cash_received)).group_by(Collection.business_date))
    paid = dict(db.query(Expense.business_date, func.sum(Expense.amount)).group_by(Expense.business_date))
    returned = dict(db.query(Expense.settled_on, func.sum(Expense.amount))
                    .filter(Expense.category == "advance", Expense.settlement_method == "cash").group_by(Expense.settled_on))
    slips = defaultdict(list)
    for d in db.query(Deposit).order_by(Deposit.deposit_date, Deposit.id):
        slips[d.business_date].append(d)
    days = sorted(set(cash) | set(paid) | set(returned) | set(slips), reverse=True)
    out = []
    for day in days:
        c, p, r = int(cash.get(day) or 0), int(paid.get(day) or 0), int(returned.get(day) or 0)
        to_dep = c - p + r
        dep = sum(s.amount for s in slips[day])
        status = status_for(day, to_dep, dep, today)
        due = next_working_day(day)
        last = max((s.deposit_date for s in slips[day]), default=None)
        out.append({
            "date": day.isoformat(), "due_on": due.isoformat(),
            "cash_received": to_sar(c), "paid_out": to_sar(p), "returned": to_sar(r),
            "to_deposit": to_sar(to_dep), "deposited": to_sar(dep),
            "pending": 0.0 if rounded(to_dep, dep) else to_sar(to_dep - dep),
            "rounding": to_sar(dep - to_dep) if rounded(to_dep, dep) else 0.0,
            "status": status, "status_text": STATUS_TEXT[status],
            "late": bool(last and last > due and dep > 0),
            "days_late": (last - due).days if last and last > due else 0,
            "slips": [{"id": s.id, "deposit_date": s.deposit_date.isoformat(), "bank": s.bank, "slip_ref": s.slip_ref,
                       "amount": to_sar(s.amount), "note": s.note, "created_by": s.created_by} for s in slips[day]],
        })
    return out


@router.get("")
def deposits(end: str | None = None, count: int = 30, db: Session = Depends(get_db)):
    today = date.today()
    last = parse_day(end, "end") if end else today
    window = {d.isoformat() for d in business_days(last, max(1, min(count, 120)))}
    all_days = ledger(db, today)
    rows = [r for r in all_days if r["date"] in window or r["status"] in ("overdue", "short", "due_today", "not_due", "over")]
    pending_rows = [r for r in all_days if r["pending"] > 0]
    by = lambda s: [r for r in all_days if r["status"] == s]  # noqa: E731
    banks = [b for (b,) in db.query(Deposit.bank).group_by(Deposit.bank).order_by(func.count(Deposit.id).desc())]
    return {"rows": rows, "banks": banks, "today": today.isoformat(),
            "totals": {"cash_on_hand": round(sum(r["pending"] for r in pending_rows), 2),
                       "overdue": round(sum(r["pending"] for r in by("overdue")), 2), "overdue_days": len(by("overdue")),
                       "short": round(sum(r["pending"] for r in by("short")), 2), "short_days": len(by("short")),
                       "due_today": round(sum(r["pending"] for r in by("due_today")), 2),
                       "not_due": round(sum(r["pending"] for r in by("not_due")), 2),
                       "deposited": round(sum(r["deposited"] for r in rows if r["date"] in window), 2),
                       "late_days": sum(r["late"] for r in rows if r["date"] in window)}}


class DepositIn(BaseModel):
    business_date: str
    deposit_date: str
    bank: str = Field(min_length=2, max_length=60)
    slip_ref: str = Field(min_length=2, max_length=60)
    amount: int | float | str
    note: str = Field("", max_length=300)


@router.post("", status_code=201)
def add_deposit(body: DepositIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    day = parse_day(body.business_date, "business_date")
    when = not_future(parse_day(body.deposit_date, "deposit_date"), "Deposit date")
    if when < day:
        raise HTTPException(422, "The deposit date cannot be before the business day it covers")
    amount = to_halalas(body.amount)
    if amount is None or amount <= 0 or amount > MAX_AMOUNT:
        raise HTTPException(422, "Enter the slip amount, more than zero")
    slip = " ".join(body.slip_ref.split()).upper()
    if db.query(Deposit).filter(func.upper(Deposit.slip_ref) == slip).first():
        raise HTTPException(409, f"Slip {slip} is already recorded")
    row = next((r for r in ledger(db) if r["date"] == day.isoformat()), None)
    if not row:
        raise HTTPException(409, "There is no cash recorded for this business day")
    still = to_halalas(row["to_deposit"]) - to_halalas(row["deposited"])
    if amount >= still + ROUND_UP:
        raise HTTPException(422, f"The slip is more than the {to_sar(max(still, 0)):,.2f} SAR still to deposit for this day")
    d = Deposit(business_date=day, deposit_date=when, bank=" ".join(body.bank.split()), slip_ref=slip, amount=amount,
                note=" ".join(body.note.split()), created_by=user)
    db.add(d)
    db.flush()
    audit.record(db, user, "created", "deposit", d.id,
                 f"Deposited {to_sar(amount):,.2f} for {day.isoformat()} at {d.bank} on {when.isoformat()}, slip {slip}")
    db.commit()
    return next(r for r in ledger(db) if r["date"] == day.isoformat())


@router.delete("/{did}")
def delete_deposit(did: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    d = db.get(Deposit, did)
    if not d:
        raise HTTPException(404, "Deposit not found")
    audit.record(db, user, "deleted", "deposit", d.id,
                 f"Deleted slip {d.slip_ref}: {to_sar(d.amount):,.2f} for {d.business_date.isoformat()} at {d.bank}")
    db.delete(d)
    db.commit()
    return {"deleted": True}
