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

# (code, city, region): a station in each main city and governorate of the Kingdom
KSA = [
    ("RUH", "Riyadh", "Riyadh"), ("KRJ", "Al Kharj", "Riyadh"), ("MJM", "Al Majmaah", "Riyadh"), ("ZUL", "Az Zulfi", "Riyadh"),
    ("DWD", "Ad Dawadmi", "Riyadh"), ("WDD", "Wadi Ad Dawasir", "Riyadh"), ("AFL", "Al Aflaj", "Riyadh"), ("SHQ", "Shaqra", "Riyadh"),
    ("QWY", "Al Quwayiyah", "Riyadh"), ("MZH", "Al Muzahimiyah", "Riyadh"),
    ("JED", "Jeddah", "Makkah"), ("MKH", "Makkah", "Makkah"), ("TIF", "Taif", "Makkah"), ("RAB", "Rabigh", "Makkah"),
    ("QNF", "Al Qunfudhah", "Makkah"), ("LIT", "Al Lith", "Makkah"), ("KHL", "Khulais", "Makkah"),
    ("MED", "Madinah", "Madinah"), ("YNB", "Yanbu", "Madinah"), ("ULA", "AlUla", "Madinah"), ("BDR", "Badr", "Madinah"),
    ("MHD", "Mahd adh Dhahab", "Madinah"),
    ("DMM", "Dammam", "Eastern Province"), ("KHB", "Khobar", "Eastern Province"), ("DHA", "Dhahran", "Eastern Province"),
    ("JUB", "Jubail", "Eastern Province"), ("HOF", "Al Ahsa (Hofuf)", "Eastern Province"), ("QTF", "Qatif", "Eastern Province"),
    ("HFB", "Hafar Al Batin", "Eastern Province"), ("KHF", "Khafji", "Eastern Province"), ("RTN", "Ras Tanura", "Eastern Province"),
    ("ABQ", "Abqaiq", "Eastern Province"), ("NAR", "An Nairyah", "Eastern Province"),
    ("BUR", "Buraidah", "Qassim"), ("UNZ", "Unaizah", "Qassim"), ("RAS", "Ar Rass", "Qassim"), ("BKY", "Al Bukayriyah", "Qassim"),
    ("AHB", "Abha", "Asir"), ("KMS", "Khamis Mushait", "Asir"), ("BSH", "Bisha", "Asir"), ("MHY", "Muhayil", "Asir"),
    ("NMS", "An Namas", "Asir"),
    ("TUU", "Tabuk", "Tabuk"), ("DBA", "Duba", "Tabuk"), ("TMA", "Tayma", "Tabuk"), ("UMJ", "Umluj", "Tabuk"),
    ("HAS", "Hail", "Hail"),
    ("ARR", "Arar", "Northern Borders"), ("RAE", "Rafha", "Northern Borders"), ("TUI", "Turaif", "Northern Borders"),
    ("GIZ", "Jazan", "Jazan"), ("SAB", "Sabya", "Jazan"), ("ABR", "Abu Arish", "Jazan"),
    ("EAM", "Najran", "Najran"), ("SHW", "Sharurah", "Najran"),
    ("ABT", "Al Baha", "Al Baha"), ("BLJ", "Baljurashi", "Al Baha"),
    ("SKK", "Sakaka", "Al Jouf"), ("QRY", "Al Qurayyat", "Al Jouf"), ("DMJ", "Dumat Al Jandal", "Al Jouf"),
]


def ensure_defaults(db: Session) -> int:
    """On a database with no stations yet, add the station list. Returns how many were added."""
    if db.query(Station).count():
        return 0
    for code, city, region in KSA:
        db.add(Station(code=code, name=city, city=city, region=region))
    db.commit()
    return len(KSA)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _clean(code: str, name: str) -> tuple[str, str]:
    return " ".join((code or "").split()).upper()[:30], " ".join((name or "").split())[:80]


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
    key = _norm(name or code)
    s = Station(code=code or key.upper()[:30], name=name or code, city="", region="")
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
        if len(found) == 1 and None not in found:
            dep.station_id = found.pop()
            changed += 1
    db.commit()
    return changed


def station_dict(s: Station, drivers: int = 0) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "city": s.city, "region": s.region, "active": s.active, "drivers": drivers}


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


@router.post("", status_code=201)
def add(body: StationIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    code = " ".join(body.code.split()).upper()
    if db.query(Station).filter(func.upper(Station.code) == code).first():
        raise HTTPException(409, f"Station {code} already exists")
    s = Station(code=code, name=" ".join(body.name.split()), city=body.city.strip(), region=body.region.strip(), active=body.active)
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
    audit.record(db, user, "updated", "station", s.id, f"Station {before} -> {s.code} {s.name} {s.city} ({'active' if s.active else 'off'})")
    db.commit()
    return station_dict(s)


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
    finally:
        current_station.reset(token)
    counts = dict(db.query(Driver.station_id, func.count(Driver.id)).filter(Driver.active.is_(True)).group_by(Driver.station_id))
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
        out.append({**station_dict(st, counts.get(st.id, 0)), "handed_over": f["drivers"],
                    **{k: f[k] for k in ("cash_received", "pos_system", "pos_terminal", "pos_difference", "pos_open",
                                         "paid_out", "to_deposit", "deposited", "pending", "deposit_status", "deposit_status_text")},
                    "cash_on_hand": round(sum(r["pending"] for r in mine if r["pending"] > 0), 2),
                    "late_days": len(late), "late_amount": round(sum(r["pending"] for r in late), 2)})
    add = lambda k: round(sum(x[k] for x in out), 2)  # noqa: E731
    return {"date": day.isoformat(), "stations": out, "active_stations": db.query(Station).filter(Station.active.is_(True)).count(),
            "totals": {k: add(k) for k in ("cash_received", "pos_system", "pos_terminal", "paid_out", "to_deposit", "deposited",
                                           "pending", "cash_on_hand", "late_amount")} | {"late_days": sum(x["late_days"] for x in out)}}
