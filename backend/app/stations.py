"""Stations: the company's warehouses across Saudi Arabia, each with its own drivers, cash desk and deposits.

CODesk starts with a station in every main city (they can be renamed, switched off or added to). A station
that appears in a system report's Site column is recognised by its code or name, and added if it is new."""
import re

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import audit
from .database import get_db
from .deps import current_user, parse_day
from .models import Collection, Deposit, Driver, Expense, PosOrder, Station, TerminalTotal

router = APIRouter(prefix="/api/stations", tags=["stations"])

# (code, city, region): a station in each of the Kingdom's 25 best-known cities; more can be added on the Stations page
KSA = [
    ("RUH", "Riyadh", "Riyadh"), ("KRJ", "Al Kharj", "Riyadh"),
    ("JED", "Jeddah", "Makkah"), ("MKH", "Makkah", "Makkah"), ("TIF", "Taif", "Makkah"),
    ("MED", "Madinah", "Madinah"), ("YNB", "Yanbu", "Madinah"), ("ULA", "AlUla", "Madinah"),
    ("DMM", "Dammam", "Eastern Province"), ("KHB", "Khobar", "Eastern Province"), ("JUB", "Jubail", "Eastern Province"),
    ("HOF", "Al Ahsa", "Eastern Province"), ("QTF", "Qatif", "Eastern Province"), ("HFB", "Hafar Al Batin", "Eastern Province"),
    ("BUR", "Buraidah", "Qassim"), ("UNZ", "Unaizah", "Qassim"),
    ("AHB", "Abha", "Asir"), ("KMS", "Khamis Mushait", "Asir"),
    ("TUU", "Tabuk", "Tabuk"), ("HAS", "Hail", "Hail"), ("ARR", "Arar", "Northern Borders"),
    ("GIZ", "Jazan", "Jazan"), ("EAM", "Najran", "Najran"), ("ABT", "Al Baha", "Al Baha"), ("SKK", "Sakaka", "Al Jouf"),
]
# stations an earlier version added that are no longer in the list: removed while nothing uses them
RETIRED = {"MJM", "ZUL", "DWD", "WDD", "AFL", "SHQ", "QWY", "MZH", "RAB", "QNF", "LIT", "KHL", "BDR", "MHD", "DHA", "KHF",
           "RTN", "ABQ", "NAR", "RAS", "BKY", "BSH", "MHY", "NMS", "DBA", "TMA", "UMJ", "RAE", "TUI", "SAB", "ABR", "SHW",
           "BLJ", "QRY", "DMJ"}


def ensure_defaults(db: Session) -> int:
    """On a database with no stations yet, add the station list. Returns how many were added. On an
    older database, the stations dropped from the list are removed if no driver or record uses them."""
    if db.query(Station).count():
        for st in db.query(Station).filter(Station.code.in_(RETIRED)):
            used = db.query(Driver).filter(Driver.station_id == st.id).count() + sum(
                db.query(m).execution_options(all_stations=True).filter(m.station_id == st.id).count()
                for m in (Collection, Expense, Deposit, PosOrder, TerminalTotal))
            if not used:
                db.delete(st)
        db.commit()
        return 0
    for code, city, region in KSA:
        db.add(Station(code=code, name=city, city=city, region=region))
    db.commit()
    return len(KSA)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _clean(code: str, name: str) -> tuple[str, str]:
    """Tidy spaces; "Riyadh Al Aarid Station" is the station "Riyadh Al Aarid"."""
    name = " ".join((name or "").split())[:80]
    return " ".join((code or "").split()).upper()[:30], re.sub(r"\s+(station|hub|warehouse|branch)$", "", name, flags=re.I) or name


def match(db: Session, code: str, name: str = "") -> Station | None:
    """The station a report's Site Code / Site points to: by code, then by name or city."""
    code, name = _clean(code, name)
    if code:
        s = db.query(Station).filter(func.upper(Station.code) == code).first()
        if s:
            return s
    for key in {_norm(name), _norm(code)} - {""}:
        for s in db.query(Station):
            if key in (_norm(s.name), _norm(s.city), _norm(s.code)):
                return s
    return None


def find_or_add(db: Session, code: str, name: str = "", user: str = "system") -> Station | None:
    """Like match, and a station that is not known yet is added."""
    code, name = _clean(code, name)
    if not code and not name:
        return None
    found = match(db, code, name)
    if found:
        return found
    city = next(((c, r, k) for k, c, r in KSA if _norm(c) in _norm(name)), None)
    if not code:  # a short code like RUH-AAR: the city's code and the start of the area's name
        rest = [w for w in re.split(r"[^A-Za-z0-9]+", re.sub(re.escape(city[0]), "", name, flags=re.I) if city else name)
                if w and w.lower() not in ("al", "el", "station", "hub")]
        code = "-".join(x for x in ((city[2] if city else ""), (rest[0][:3].upper() if rest else "")) if x) or _norm(name).upper()[:8]
        while db.query(Station).filter(func.upper(Station.code) == code).first():
            code = code + "2"
    s = Station(code=code, name=name or code, city=city[0] if city else "", region=city[1] if city else "")
    db.add(s)
    db.flush()
    audit.record(db, user, "created", "station", s.id, f"Station {s.code} {s.name} (from a report)")
    return s


def assign_missing(db: Session) -> int:
    """Give rows saved before stations existed the station of their driver; a deposit takes the station of
    that day's handovers when they all belong to one. Returns how many rows were updated."""
    changed = 0
    by_hub = {_norm(s.name): s.id for s in db.query(Station)} | {_norm(s.city): s.id for s in db.query(Station) if s.city}
    for d in db.query(Driver).filter(Driver.station_id.is_(None), Driver.hub != ""):
        if _norm(d.hub) in by_hub:
            d.station_id = by_hub[_norm(d.hub)]
            changed += 1
    db.flush()
    driver_station = dict(db.query(Driver.id, Driver.station_id).filter(Driver.station_id.isnot(None)))
    for model in (Collection, Expense, PosOrder, TerminalTotal):
        for row in db.query(model).execution_options(all_stations=True).filter(model.station_id.is_(None), model.driver_id.isnot(None)):
            if row.driver_id in driver_station:
                row.station_id = driver_station[row.driver_id]
                changed += 1
    db.flush()
    for dep in db.query(Deposit).execution_options(all_stations=True).filter(Deposit.station_id.is_(None)):
        found = {s for (s,) in db.query(Collection.station_id).execution_options(all_stations=True)
                 .filter(Collection.business_date == dep.business_date).distinct()}
        if len(found) > 1:  # several stations had cash that day: the slip is the one station's without a slip of its own
            found -= {s for (s,) in db.query(Deposit.station_id).execution_options(all_stations=True)
                      .filter(Deposit.business_date == dep.business_date, Deposit.station_id.isnot(None)).distinct()}
        if len(found) == 1 and None not in found:
            dep.station_id = found.pop()
            changed += 1
    db.commit()
    return changed


def station_dict(s: Station, drivers: int = 0) -> dict:
    from .money import to_sar
    return {"id": s.id, "code": s.code, "name": s.name, "city": s.city, "region": s.region, "active": s.active, "drivers": drivers,
            "cashier_name": s.cashier_name or "", "cashier_phone": s.cashier_phone or "", "cashier_email": s.cashier_email or "",
            "cash_limit": to_sar(s.cash_limit or 0)}


@router.get("")
def stations(db: Session = Depends(get_db)):
    counts = dict(db.query(Driver.station_id, func.count(Driver.id)).filter(Driver.active.is_(True)).group_by(Driver.station_id))
    rows = db.query(Station).order_by(Station.region, Station.name).all()
    return {"stations": [station_dict(s, counts.get(s.id, 0)) for s in rows], "unassigned_drivers": counts.get(None, 0)}


class StationIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=80)
    city: str = Field("", max_length=60)
    region: str = Field("", max_length=60)
    active: bool = True
    cashier_name: str = Field("", max_length=80)
    cashier_phone: str = Field("", max_length=30)
    cashier_email: str = Field("", max_length=120)
    cash_limit: float = Field(0, ge=0, le=10_000_000)


def _cashier(s: Station, body: "StationIn"):
    s.cashier_name = " ".join(body.cashier_name.split())
    s.cashier_phone = "".join(body.cashier_phone.split())
    s.cashier_email = body.cashier_email.strip()
    s.cash_limit = round(body.cash_limit * 100)


@router.post("", status_code=201)
def add(body: StationIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    code = " ".join(body.code.split()).upper()
    if db.query(Station).filter(func.upper(Station.code) == code).first():
        raise HTTPException(409, f"Station {code} already exists")
    s = Station(code=code, name=" ".join(body.name.split()), city=body.city.strip(), region=body.region.strip(), active=body.active)
    _cashier(s, body)
    db.add(s)
    db.flush()
    audit.record(db, user, "created", "station", s.id, f"Station {s.code} {s.name}")
    db.commit()
    return station_dict(s)


@router.put("/{sid}")
def update(sid: int, body: StationIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = db.get(Station, sid)
    if not s:
        raise HTTPException(404, "Station not found")
    code = " ".join(body.code.split()).upper()
    if db.query(Station).filter(func.upper(Station.code) == code, Station.id != sid).first():
        raise HTTPException(409, f"Station {code} already exists")
    before = f"{s.code} {s.name} {s.city} ({'active' if s.active else 'off'})"
    s.code, s.name, s.city, s.region, s.active = code, " ".join(body.name.split()), body.city.strip(), body.region.strip(), body.active
    _cashier(s, body)
    audit.record(db, user, "updated", "station", s.id, f"Station {before} -> {s.code} {s.name} {s.city} ({'active' if s.active else 'off'})")
    db.commit()
    return station_dict(s)


@router.post("/{sid}/adopt")
def adopt(sid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Put every driver without a station in this one, with his records saved before stations existed."""
    s = db.get(Station, sid)
    if not s:
        raise HTTPException(404, "Station not found")
    drivers = db.query(Driver).filter(Driver.station_id.is_(None)).all()
    for d in drivers:
        d.station_id = s.id
    db.flush()
    records = assign_missing(db)
    audit.record(db, user, "updated", "station", s.id, f"{len(drivers)} drivers without a station put in {s.code} {s.name}")
    db.commit()
    return {"drivers": len(drivers), "records": records, "station": station_dict(s)}


def _check_day(db: Session, sid: int, day: date, f: dict, row: dict | None, late: list[dict]) -> tuple[dict, list[dict], str]:
    """Which of the day's files the station's cashier has sent, and what the supervisor should ask about.
    The level is "call" (money is late or the day's report is missing), "check" (something to look at)
    or "ok"."""
    q = lambda m: db.query(m).execution_options(all_stations=True).filter(m.station_id == sid)  # noqa: E731
    report = q(Collection).filter(Collection.business_date == day).count()
    orders = q(PosOrder).filter(PosOrder.business_date == day).count()
    machines = (q(TerminalTotal).filter(TerminalTotal.business_date == day).count()  # the machine sheet, or machine totals in the handovers
                + q(Collection).filter(Collection.business_date == day, Collection.pos_amount > 0).count())
    expenses = q(Expense).filter(Expense.business_date == day).count()
    slip_due = bool(row and row["to_deposit"] > 0)
    slip = "sent" if row and row["deposited"] > 0 else ("waiting" if slip_due and row["status"] in ("not_due", "due_today") else
                                                       "missing" if slip_due else "none")
    files = {"report": report > 0, "pos_orders": orders > 0, "terminal_sheet": machines > 0, "expenses": expenses, "slip": slip}
    problems: list[dict] = []
    if not report:
        problems.append({"level": "call", "kind": "missing_file", "text": "No collection report for this day"})
    elif not orders:
        problems.append({"level": "check", "kind": "missing_file", "text": "The system's POS orders file is missing"})
    elif not machines:
        problems.append({"level": "check", "kind": "missing_file", "text": "The card machine sheet is missing"})
    if orders and machines and abs(f["pos_difference"]) >= 0.01:  # the cashier's card machine sheet against the system's card payments
        problems.append({"level": "check", "kind": "card_sheet", "amount": abs(f["pos_difference"]), "date": day.isoformat(),
                         "text": f"Card machine sheet differs from the system by {f['pos_difference']:,.2f}"})
    if late:
        amount = sum(r["pending"] for r in late)
        days = ", ".join(f"{date.fromisoformat(r['date']):%a %d %b}" for r in sorted(late, key=lambda r: r["date"])[:3])
        first = sorted(late, key=lambda r: r["date"])[0]
        problems.append({"level": "call", "kind": "deposit_short" if first["status"] == "short" else "deposit_late",
                         "amount": round(amount, 2), "date": first["date"],
                         "text": f"Cash not in the bank: {amount:,.2f} SAR ({days}{'…' if len(late) > 3 else ''})"})
    if row and row["status"] == "due_today":
        problems.append({"level": "check", "kind": "deposit_late", "amount": row["pending"], "date": day.isoformat(),
                         "text": f"Deposit of {row['pending']:,.2f} due today"})
    level = "call" if any(p["level"] == "call" for p in problems) else "check" if problems else "ok"
    return files, problems, level


@router.get("/overview")
def overview(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    """Every station's figures for one day, side by side, plus each one's cash still to deposit."""
    from . import dashboard, deposits
    from .scope import current_station
    day = parse_day(date_)
    token = current_station.set(None)  # the overview always looks at all stations
    try:
        ledger = deposits.ledger(db, date.today())
        busy = {s for (s,) in db.query(Collection.station_id).filter(Collection.business_date == day).distinct()}
        busy |= {r["station_id"] for r in ledger if r["pending"] > 0}
        busy |= {s for (s,) in db.query(Driver.station_id).filter(Driver.active.is_(True)).distinct()}  # a station with drivers should send its files
    finally:
        current_station.reset(token)
    counts = dict(db.query(Driver.station_id, func.count(Driver.id)).filter(Driver.active.is_(True)).group_by(Driver.station_id))
    from .supervisor import checks_for
    checked = checks_for(db, day)
    out = []
    for st in db.query(Station).filter(Station.id.in_([b for b in busy if b])).order_by(Station.name):
        token = current_station.set(st.id)
        try:
            rows = {r["date"]: r for r in ledger if r["station_id"] == st.id}
            f = dashboard.day_figures(db, day, rows)
        finally:
            current_station.reset(token)
        mine = [r for r in ledger if r["station_id"] == st.id]
        late = [r for r in mine if r["status"] in ("overdue", "short")]
        files, problems, level = _check_day(db, st.id, day, f, rows.get(day.isoformat()), late)
        out.append({**station_dict(st, counts.get(st.id, 0)), "handed_over": f["drivers"],
                    **{k: f[k] for k in ("cash_received", "pos_system", "pos_terminal", "pos_difference", "pos_open",
                                         "paid_out", "to_deposit", "deposited", "pending", "deposit_status", "deposit_status_text")},
                    "cash_on_hand": round(sum(r["pending"] for r in mine if r["pending"] > 0), 2),
                    "late_days": len(late), "late_amount": round(sum(r["pending"] for r in late), 2),
                    "late_dates": sorted(r["date"] for r in late), "files": files, "problems": problems, "level": level,
                    "check": checked.get(st.id)})
    out.sort(key=lambda x: ({"call": 0, "check": 1, "ok": 2}[x["level"]], -x["late_amount"], x["name"]))
    add = lambda k: round(sum(x[k] for x in out), 2)  # noqa: E731
    return {"date": day.isoformat(), "stations": out, "active_stations": db.query(Station).filter(Station.active.is_(True)).count(),
            "totals": {k: add(k) for k in ("cash_received", "pos_system", "pos_terminal", "paid_out", "to_deposit", "deposited",
                                           "pending", "cash_on_hand", "late_amount")} | {"late_days": sum(x["late_days"] for x in out)}}
