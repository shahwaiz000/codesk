"""Bank deposits: each business day's cash goes to the bank on the next working day.

    cash to deposit = cash received from drivers
                      - expenses and advances paid out that day
                      + advances returned in cash that day

A day can be deposited with more than one slip, and each station runs a balance: what a day leaves
unbanked is carried to the next day, and a slip larger than its day's cash pays the oldest day still short. Cash goes in as notes, so a day deposited to within
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
from .models import Collection, Deposit, Expense, Station
from .scope import current_station
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
    """Every business day that has money in or out, newest first: one row per station and day, because
    each station deposits its own cash.

    Each station runs a balance, like a bank statement: what was left from earlier days is brought forward,
    the day's cash is added, the slips are taken off, and what is left goes on to the next day. A slip pays
    its own day first; anything more pays the oldest day still short."""
    today = today or date.today()
    cash = {(st, d): v for st, d, v in db.query(Collection.station_id, Collection.business_date, func.sum(Collection.cash_received))
            .group_by(Collection.station_id, Collection.business_date)}
    paid = {(st, d): v for st, d, v in db.query(Expense.station_id, Expense.business_date, func.sum(Expense.amount))
            .group_by(Expense.station_id, Expense.business_date)}
    returned = {(st, d): v for st, d, v in db.query(Expense.station_id, Expense.settled_on, func.sum(Expense.amount))
                .filter(Expense.category == "advance", Expense.settlement_method == "cash").group_by(Expense.station_id, Expense.settled_on)}
    slips = defaultdict(list)
    for d in db.query(Deposit).order_by(Deposit.deposit_date, Deposit.id):
        slips[(d.station_id, d.business_date)].append(d)
    stations = {s.id: s for s in db.query(Station)}
    keys = set(cash) | set(paid) | set(returned) | set(slips)

    # walk each station's days, oldest first, keeping what each day still owes
    owed: dict[tuple, int] = {}       # (station, day) -> still to deposit
    rounding: dict[tuple, int] = {}
    paid_later: dict[tuple, tuple] = {}  # (station, day) -> (deposit date, business day of the slip) that finished it
    opening: dict[tuple, int] = {}
    closing: dict[tuple, int] = {}
    for st in {k[0] for k in keys}:
        credit = 0  # paid too much, beyond rounding: taken off the next day's cash
        mine = sorted(k for k in keys if k[0] == st)
        for key in mine:
            own = int(cash.get(key) or 0) - int(paid.get(key) or 0) + int(returned.get(key) or 0)
            opening[key] = sum(v for k, v in owed.items() if k[0] == st) - credit
            take = min(credit, max(own, 0))
            credit -= take
            owed[key] = own - take
            amount = sum(x.amount for x in slips[key])
            last = max((x.deposit_date for x in slips[key]), default=None)
            if amount:
                if rounded(owed[key], amount):
                    rounding[key], owed[key] = amount - owed[key], 0
                    amount = 0
                else:
                    use = min(amount, max(owed[key], 0))
                    owed[key] -= use
                    amount -= use
                for old in sorted(k for k in owed if k[0] == st and k < key and owed[k] > 0):
                    if not amount:
                        break
                    if rounded(owed[old], amount):  # the rest of the slip pays this day, rounded to whole notes
                        rounding[old] = amount - owed[old]
                        owed[old], amount = 0, 0
                        paid_later[old] = (last, key[1])
                    elif amount >= owed[old]:
                        owed[old], amount = 0, amount - owed[old]
                        paid_later[old] = (last, key[1])
                    else:
                        owed[old] -= amount
                        amount = 0
                credit += amount
            closing[key] = sum(v for k, v in owed.items() if k[0] == st) - credit

    out = []
    for key in sorted(keys, key=lambda k: (k[1], stations[k[0]].name if k[0] in stations else ""), reverse=True):
        st, day = key
        c, p, r = int(cash.get(key) or 0), int(paid.get(key) or 0), int(returned.get(key) or 0)
        to_dep = c - p + r
        dep = sum(x.amount for x in slips[key])
        pending = owed[key]
        applied = to_dep - pending if not rounding.get(key) else dep
        status = status_for(day, to_dep, applied, today) if pending or not dep or not rounding.get(key) else "deposited"
        if pending > 0 and dep == 0 and key in paid_later:
            status = "short"
        due = next_working_day(day)
        later = paid_later.get(key)
        last = max([x.deposit_date for x in slips[key]] + ([later[0]] if later and not pending else []), default=None)
        out.append({
            "date": day.isoformat(), "due_on": due.isoformat(),
            "station_id": st, "station": stations[st].name if st in stations else "No station",
            "station_code": stations[st].code if st in stations else "",
            "cash_received": to_sar(c), "paid_out": to_sar(p), "returned": to_sar(r),
            "to_deposit": to_sar(to_dep), "deposited": to_sar(dep),
            "brought_forward": to_sar(opening[key]), "total_due": to_sar(opening[key] + to_dep), "left": to_sar(closing[key]),
            "pending": to_sar(pending), "rounding": to_sar(rounding.get(key, 0)),
            "paid_later_on": later[0].isoformat() if later and not pending else None,
            "status": status, "status_text": STATUS_TEXT[status],
            "late": bool(last and last > due and (dep > 0 or later)),
            "days_late": (last - due).days if last and last > due else 0,
            "slips": [{"id": x.id, "deposit_date": x.deposit_date.isoformat(), "bank": x.bank, "slip_ref": x.slip_ref,
                       "amount": to_sar(x.amount), "note": x.note, "created_by": x.created_by} for x in slips[key]],
        })
    return out


WORST = ("overdue", "short", "over", "due_today", "not_due", "deposited", "nothing")


def by_day(rows: list[dict]) -> list[dict]:
    """The stations' rows of each day added together, for the all-stations view. The day's status is the
    most urgent of its stations' (one station overdue makes the day overdue)."""
    days: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        days[r["date"]].append(r)
    out = []
    for day, rs in sorted(days.items(), reverse=True):
        if len(rs) == 1:
            out.append(rs[0])
            continue
        status = min((r["status"] for r in rs), key=WORST.index)
        add = lambda k: round(sum(r[k] for r in rs), 2)  # noqa: E731
        out.append({"date": day, "due_on": rs[0]["due_on"], "station_id": None, "station": f"{len(rs)} stations", "station_code": "",
                    **{k: add(k) for k in ("cash_received", "paid_out", "returned", "to_deposit", "deposited", "pending", "rounding",
                                            "brought_forward", "total_due", "left")}, "paid_later_on": None,
                    "status": status, "status_text": STATUS_TEXT[status], "late": any(r["late"] for r in rs),
                    "days_late": max(r["days_late"] for r in rs), "slips": [x for r in rs for x in r["slips"]]})
    return out


@router.get("")
def deposits(end: str | None = None, count: int = 30, days: bool = False, db: Session = Depends(get_db)):
    """days=true adds the stations of each day together (the all-stations view of one day)."""
    today = date.today()
    last = parse_day(end, "end") if end else today
    window = {d.isoformat() for d in business_days(last, max(1, min(count, 120)))}
    all_days = by_day(ledger(db, today)) if days else ledger(db, today)
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
    station_id: int | None = None  # whose cash: needed in the all-stations view when a day has several stations


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
    if db.query(Deposit).execution_options(all_stations=True).filter(func.upper(Deposit.slip_ref) == slip).first():
        raise HTTPException(409, f"Slip {slip} is already recorded")
    wanted = body.station_id or current_station.get()
    rows = [r for r in ledger(db) if r["date"] == day.isoformat() and (wanted is None or r["station_id"] == wanted)]
    if not rows:
        raise HTTPException(409, "There is no cash recorded for this business day")
    if len(rows) > 1:
        raise HTTPException(422, "Several stations have cash on this day: choose the station first")
    row = rows[0]
    still = to_halalas(row["left"])  # this day's cash and anything left from earlier days
    if amount >= still + ROUND_UP:
        raise HTTPException(422, f"The slip is more than the {to_sar(max(still, 0)):,.2f} SAR still to deposit up to this day")
    d = Deposit(business_date=day, deposit_date=when, bank=" ".join(body.bank.split()), slip_ref=slip, amount=amount,
                note=" ".join(body.note.split()), created_by=user, station_id=row["station_id"])
    db.add(d)
    db.flush()
    audit.record(db, user, "created", "deposit", d.id,
                 f"Deposited {to_sar(amount):,.2f} for {day.isoformat()} at {d.bank} on {when.isoformat()}, slip {slip}")
    db.commit()
    return next(r for r in ledger(db) if r["date"] == day.isoformat() and r["station_id"] == row["station_id"])


@router.delete("/{did}")
def delete_deposit(did: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    d = db.get(Deposit, did)
    if not d:
        raise HTTPException(404, "Deposit not found")
    audit.record(db, user, "deleted", "deposit", d.id,
                 f"Deleted slip {d.slip_ref}: {to_sar(d.amount):,.2f} for {d.business_date.isoformat()} at {d.bank}")
    from .models import SlipScan
    for scan in db.query(SlipScan).filter(SlipScan.deposit_id == d.id):  # a slip read by the AI goes back to put aside
        scan.deposit_id, scan.status = None, "dismissed"
    db.flush()
    db.delete(d)
    db.commit()
    return {"deleted": True}
