"""Fictional demo data: 12 drivers and 30 days of collections, expenses and deposits.

Every name, ID, amount and reference here is made up. The random numbers use a fixed seed, and a
few mistakes are planted on purpose (PLANTED) so the app has something real to catch and the tests
know the right answers. Day positions count back from the latest business day (0 = latest)."""
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import Collection, Deposit, Driver, Expense

DRIVERS = [
    ("D-101", "Faisal Al-Harbi", "North Hub"), ("D-102", "Imran Qureshi", "North Hub"),
    ("D-103", "Yousef Al-Amri", "North Hub"), ("D-104", "Bilal Ahmed", "Central Hub"),
    ("D-105", "Majed Al-Otaibi", "Central Hub"), ("D-106", "Rashid Khan", "Central Hub"),
    ("D-107", "Saeed Al-Zahrani", "Central Hub"), ("D-108", "Naveed Iqbal", "South Hub"),
    ("D-109", "Turki Al-Shehri", "South Hub"), ("D-110", "Arif Hussain", "South Hub"),
    ("D-111", "Omar Al-Ghamdi", "South Hub"), ("D-112", "Kamran Malik", "South Hub"),
]
INACTIVE = {"D-112"}
BANKS = ("Coastal National Bank", "Gulf Trade Bank")
DAYS = 30

PLANTED = {
    # (day position, driver, cash received minus expected, in SAR)
    "cash_differences": [(1, "D-103", -50), (3, "D-107", -120), (6, "D-101", -20),
                         (8, "D-110", 30), (11, "D-109", -300), (17, "D-104", -75)],
    # (day given, driver, SAR, day settled or None while still open)
    "advances": [(25, "D-102", 1000, 15), (18, "D-106", 500, 10), (9, "D-108", 300, None), (2, "D-111", 800, None)],
    "short_deposit": (12, 500),   # this day's deposit was 500 SAR less than the cash to deposit
    "late_deposit": (20, 3),      # this day's cash reached the bank 3 working days later instead of 1
    "split_deposit": 5,           # this day was deposited with two slips
    "undeposited": 0,             # the latest day: cash is on hand, deposit is due today
}


def is_working_day(d: date) -> bool:
    return d.weekday() != 4  # Friday is the weekly day off


def next_working_day(d: date, n: int = 1) -> date:
    while n:
        d += timedelta(days=1)
        if is_working_day(d):
            n -= 1
    return d


def business_days(end: date, count: int = DAYS) -> list[date]:
    """The last `count` working days up to and including `end`, newest first."""
    days, d = [], end
    while len(days) < count:
        if is_working_day(d):
            days.append(d)
        d -= timedelta(days=1)
    return days


def default_end_date(today: date | None = None) -> date:
    d = (today or date.today()) - timedelta(days=1)
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def seed_demo(db: Session, end: date | None = None) -> None:
    """Fill an empty database. Does nothing if any driver exists."""
    if db.query(Driver).count():
        return
    rng = random.Random(2026)
    days = business_days(end or default_end_date())
    by_code = {}
    for code, name, hub in DRIVERS:
        drv = Driver(code=code, name=name, hub=hub, phone=f"05{rng.randint(10_000_000, 99_999_999)}",
                     active=code not in INACTIVE)
        db.add(drv)
        by_code[code] = drv
    db.flush()

    differences = {(pos, code): sar * 100 for pos, code, sar in PLANTED["cash_differences"]}
    cash_by_day: dict[int, int] = {}
    for pos, day in enumerate(days):
        total = 0
        for code, drv in by_code.items():
            if not drv.active:
                continue
            orders = rng.randint(14, 34)
            cash = pos_amt = 0
            for _ in range(orders):
                value = rng.randint(70, 840) * 50  # 35 to 420 SAR, in halalas
                if rng.random() < 0.62:
                    cash += value
                else:
                    pos_amt += value
            received = cash + differences.get((pos, code), 0)
            db.add(Collection(business_date=day, driver_id=drv.id, orders=orders, expected_cash=cash,
                              cash_received=received, pos_amount=pos_amt, created_by="demo"))
            total += received
        cash_by_day[pos] = total

    active = [d for d in by_code.values() if d.active]
    ranges = {"fuel": (40, 120), "toll": (10, 30), "parking": (5, 20), "travel": (50, 200), "maintenance": (80, 250)}
    spent_by_day: dict[int, int] = {pos: 0 for pos in range(len(days))}
    for pos, day in enumerate(days):
        for _ in range(rng.randint(2, 4)):
            cat = rng.choices(list(ranges), weights=[5, 3, 2, 2, 1])[0]
            lo, hi = ranges[cat]
            amount = rng.randint(lo, hi) * 100
            db.add(Expense(business_date=day, driver_id=rng.choice(active).id, category=cat, amount=amount,
                           reference=f"RC-{rng.randint(10000, 99999)}", created_by="demo"))
            spent_by_day[pos] += amount
    for pos, code, sar, settled in PLANTED["advances"]:
        db.add(Expense(business_date=days[pos], driver_id=by_code[code].id, category="advance", amount=sar * 100,
                       reference=f"ADV-{rng.randint(1000, 9999)}", note="Trip advance",
                       settled_on=days[settled] if settled is not None else None,
                       settlement_note="Recovered from salary" if settled is not None else "", created_by="demo"))
        spent_by_day[pos] += sar * 100

    short_pos, short_sar = PLANTED["short_deposit"]
    late_pos, late_days = PLANTED["late_deposit"]
    for pos, day in enumerate(days):
        if pos == PLANTED["undeposited"]:
            continue
        due = cash_by_day[pos] - spent_by_day[pos]
        if pos == short_pos:
            due -= short_sar * 100
        when = next_working_day(day, late_days if pos == late_pos else 1)
        bank = BANKS[pos % 2]
        parts = [due // 2, due - due // 2] if pos == PLANTED["split_deposit"] else [due]
        for part in parts:
            db.add(Deposit(business_date=day, deposit_date=when, bank=bank, slip_ref=f"DS-{rng.randint(100000, 999999)}",
                           amount=part, created_by="demo"))
    db.commit()
