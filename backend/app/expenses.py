"""Driver expenses and advances, all paid out of the day's collected cash.

Every expense and every advance lowers the cash to deposit for its business day. An advance stays open
until it is recovered: either deducted from the driver's salary (nothing comes back to the desk) or
returned in cash (which is added to the cash to deposit on the day it comes back)."""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit
from .collections import MAX_AMOUNT
from .database import get_db
from .deps import current_user, not_future, parse_day
from .models import EXPENSE_CATEGORIES, Driver, Expense
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api", tags=["expenses"])

CATEGORY_TEXT = {"salary": "Salary", "incentive": "Incentive", "settlement": "Final settlement", "fuel": "Fuel", "toll": "Toll", "parking": "Parking", "travel": "Travel", "maintenance": "Maintenance",
                 "other": "Other", "advance": "Advance"}


def expense_dict(e: Expense) -> dict:
    return {"id": e.id, "business_date": e.business_date.isoformat(), "driver_id": e.driver_id,
            "driver_code": e.driver.code, "driver_name": e.driver.name, "category": e.category,
            "category_text": CATEGORY_TEXT[e.category], "amount": to_sar(e.amount), "reference": e.reference,
            "note": e.note, "created_by": e.created_by,
            "settled_on": e.settled_on.isoformat() if e.settled_on else None,
            "settlement_method": e.settlement_method or None, "settlement_note": e.settlement_note}


@router.get("/expenses")
def day_expenses(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    day = parse_day(date_)
    rows = (db.query(Expense).join(Driver).filter(Expense.business_date == day)
            .order_by(Expense.category == "advance", Driver.code, Expense.id).all())
    by_cat: dict[str, int] = defaultdict(int)
    for e in rows:
        by_cat[e.category] += e.amount
    expenses = sum(v for k, v in by_cat.items() if k != "advance")
    return {"date": day.isoformat(), "rows": [expense_dict(e) for e in rows],
            "totals": {"expenses": to_sar(expenses), "advances": to_sar(by_cat.get("advance", 0)),
                       "total": to_sar(sum(by_cat.values())), "count": len(rows),
                       "by_category": [{"category": c, "category_text": CATEGORY_TEXT[c], "amount": to_sar(by_cat[c])}
                                       for c in EXPENSE_CATEGORIES if by_cat.get(c)]},
            "categories": [{"value": c, "text": CATEGORY_TEXT[c]} for c in EXPENSE_CATEGORIES]}


class ExpenseIn(BaseModel):
    business_date: str
    driver_id: int
    category: str
    amount: int | float | str
    reference: str = Field("", max_length=60)
    note: str = Field("", max_length=300)


def _clean(db: Session, body: ExpenseIn) -> tuple[date, Driver, int]:
    day = not_future(parse_day(body.business_date, "business_date"))
    if body.category not in EXPENSE_CATEGORIES:
        raise HTTPException(422, "Choose a category: " + ", ".join(CATEGORY_TEXT.values()))
    driver = db.get(Driver, body.driver_id)
    if not driver:
        raise HTTPException(404, "Driver not found")
    amount = to_halalas(body.amount)
    if amount is None:
        raise HTTPException(422, "Amount is not a valid number")
    if amount <= 0 or amount > MAX_AMOUNT:
        raise HTTPException(422, "Amount must be more than zero")
    return day, driver, amount


def _label(e: Expense) -> str:
    return f"{CATEGORY_TEXT[e.category].lower()} {to_sar(e.amount):,.2f} for {e.driver.code} on {e.business_date.isoformat()}"


@router.post("/expenses", status_code=201)
def add_expense(body: ExpenseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    day, driver, amount = _clean(db, body)
    if not driver.active:
        raise HTTPException(409, f"{driver.code} is inactive. Reactivate the driver on the Drivers page first")
    e = Expense(business_date=day, driver_id=driver.id, category=body.category, amount=amount,
                reference=body.reference.strip(), note=" ".join(body.note.split()), created_by=user)
    e.driver = driver
    db.add(e)
    db.flush()
    audit.record(db, user, "created", "expense", e.id, f"Paid {_label(e)}" + (f" ({e.reference})" if e.reference else ""))
    db.commit()
    return expense_dict(e)


def _expense_or_404(db: Session, eid: int) -> Expense:
    e = db.get(Expense, eid)
    if not e:
        raise HTTPException(404, "Expense not found")
    return e


@router.put("/expenses/{eid}")
def edit_expense(eid: int, body: ExpenseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    e = _expense_or_404(db, eid)
    if e.settled_on:
        raise HTTPException(409, "This advance is already recovered. Reopen it before changing it")
    day, driver, amount = _clean(db, body)
    before = _label(e)
    e.business_date, e.driver_id, e.category, e.amount = day, driver.id, body.category, amount
    e.driver = driver
    e.reference, e.note = body.reference.strip(), " ".join(body.note.split())
    after = _label(e)
    if before != after:
        audit.record(db, user, "updated", "expense", e.id, f"Changed {before} -> {after}")
    db.commit()
    return expense_dict(e)


@router.delete("/expenses/{eid}")
def delete_expense(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    e = _expense_or_404(db, eid)
    if e.settled_on:
        raise HTTPException(409, "This advance is already recovered. Reopen it before deleting it")
    audit.record(db, user, "deleted", "expense", e.id, f"Deleted {_label(e)}")
    db.delete(e)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- advances

@router.get("/advances")
def advances(status: str = "open", db: Session = Depends(get_db)):
    q = db.query(Expense).join(Driver).filter(Expense.category == "advance")
    if status == "open":
        q = q.filter(Expense.settled_on.is_(None))
    rows = q.order_by(Expense.settled_on.isnot(None), Expense.business_date, Driver.code).all()
    today = date.today()
    out = [{**expense_dict(e), "days_open": ((e.settled_on or today) - e.business_date).days} for e in rows]
    open_rows = [e for e in rows if not e.settled_on]
    return {"rows": out, "open_total": to_sar(sum(e.amount for e in open_rows)), "open_count": len(open_rows),
            "drivers": len({e.driver_id for e in open_rows})}


class SettleIn(BaseModel):
    settled_on: str
    method: str = Field(pattern="^(salary|cash)$")
    note: str = Field("", max_length=300)


@router.post("/advances/{eid}/settle")
def settle(eid: int, body: SettleIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    e = _expense_or_404(db, eid)
    if e.category != "advance":
        raise HTTPException(409, "Only advances are recovered")
    if e.settled_on:
        raise HTTPException(409, "This advance is already recovered")
    day = not_future(parse_day(body.settled_on, "settled_on"), "Recovery date")
    if day < e.business_date:
        raise HTTPException(422, "An advance cannot be recovered before the day it was given")
    e.settled_on, e.settlement_method, e.settlement_note = day, body.method, " ".join(body.note.split())
    how = "cash returned at the desk (added to that day's deposit)" if body.method == "cash" else "deducted from salary"
    audit.record(db, user, "settled", "expense", e.id, f"Recovered advance {_label(e)} on {day.isoformat()}: {how}")
    db.commit()
    return expense_dict(e)


@router.post("/advances/{eid}/reopen")
def reopen(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    e = _expense_or_404(db, eid)
    if not e.settled_on:
        raise HTTPException(409, "This advance is still open")
    audit.record(db, user, "reopened", "expense", e.id, f"Reopened advance {_label(e)} (was recovered {e.settled_on.isoformat()} by {e.settlement_method})")
    e.settled_on, e.settlement_method, e.settlement_note = None, "", ""
    db.commit()
    return expense_dict(e)
