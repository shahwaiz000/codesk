import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from . import supervisor, audit, auth, collections, dashboard, deposits, driver_import, expenses, expense_import, pos, reports, terminals, ai, ask, morning, scope, slip_reader, stations, unusual, watcher
scope_module = scope  # the station filter (its events are registered on import)
from .deps import current_user
from .config import settings
from .database import Base, SessionLocal, add_missing_columns, engine, get_db
from .models import AppSetting, AuditEvent, Collection, Deposit, Driver, Expense, User, iso, Station
from .money import to_sar
from .seed import match_paid_mode, seed_demo, seed_more_stations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    added = add_missing_columns()
    if added:
        logging.getLogger("codesk").info("Updated the database: added %s", ", ".join(added))
    with SessionLocal() as db:
        stations.ensure_defaults(db)
    if settings.seed_demo_data:
        with SessionLocal() as db:
            seed_demo(db)
            seed_more_stations(db)
            match_paid_mode(db)
    with SessionLocal() as db:
        stations.assign_missing(db)
    stop = watcher.start()
    yield
    if stop:
        stop.set()


app = FastAPI(title="CODesk API", version="0.1.0", lifespan=lifespan)
app.include_router(collections.router)
app.include_router(pos.router)
app.include_router(expenses.router)
app.include_router(deposits.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(driver_import.router)
app.include_router(terminals.router)
app.include_router(expense_import.router)
app.include_router(watcher.router)
app.include_router(slip_reader.router)
app.include_router(unusual.router)
app.include_router(morning.router)
app.include_router(ai.router)
app.include_router(ask.router)
app.include_router(stations.router)
app.include_router(supervisor.router)


class StationScope:
    """Reads the station the person is looking at (X-Station header, or ?station= on a download link)
    and applies it to every query of the request (see scope.py). Empty or "all" means all stations."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        raw = dict(scope.get("headers") or []).get(b"x-station", b"").decode()
        if not raw:
            from urllib.parse import parse_qs
            raw = (parse_qs(scope.get("query_string", b"").decode()).get("station") or [""])[0]
        sid = int(raw) if raw.isdigit() else None
        token = scope_module.current_station.set(sid)
        try:
            await self.app(scope, receive, send)
        finally:
            scope_module.current_station.reset(token)


app.add_middleware(StationScope)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _err(status: int, code: str, message: str):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


OPEN_PATHS = ("/api/health", "/api/auth/")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if not settings.auth_enabled or not path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)
    if request.method not in SAFE_METHODS:  # a page on another site must not be able to act for the person
        origin = request.headers.get("origin")
        allowed = settings.cors_origins.split(",")
        if origin and origin not in allowed and origin.split("://")[-1] != request.headers.get("host"):
            return _err(403, "bad_origin", "This request came from an unknown website")
    if any(path.startswith(p) for p in OPEN_PATHS):
        return await call_next(request)
    with SessionLocal() as db:
        user = auth.user_for(db, request.cookies.get(auth.COOKIE))
    if not user:
        return _err(401, "not_logged_in", "Please log in")
    request.state.username = user.username
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return _err(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    def one(e):
        field = ".".join(str(p) for p in e["loc"] if p != "body")
        return f"{field}: {e['msg']}" if field else e["msg"]
    return _err(422, "validation_error", "; ".join(one(e) for e in exc.errors()))


@app.get("/api/health")
def health():
    return {"status": "ok", "currency": settings.currency}


# ---------------------------------------------------------------- drivers

CODE_OK = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")


class DriverIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field("", max_length=20)
    hub: str = Field("", max_length=60)
    pos_terminal: str = Field("", max_length=30)
    station_id: int | None = None  # empty: the station being looked at


class DriverPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    phone: str | None = Field(None, max_length=20)
    hub: str | None = Field(None, max_length=60)
    pos_terminal: str | None = Field(None, max_length=30)
    active: bool | None = None
    station_id: int | None = None


def _clean_terminal(db: Session, terminal: str, driver_id: int | None) -> str:
    """Terminal IDs are compared without spaces; one terminal can belong to one active driver."""
    t = "".join(terminal.split()).upper()
    if t:
        other = db.query(Driver).filter(Driver.pos_terminal == t, Driver.active.is_(True),
                                        Driver.id != (driver_id or 0)).first()
        if other:
            raise HTTPException(409, f"Terminal {t} is already given to {other.code} {other.name}. Remove it there first")
    return t


def _clean_code(code: str) -> str:
    code = code.strip().upper()
    if not CODE_OK.match(code):
        raise HTTPException(422, "Driver ID can use letters, numbers and dashes, for example D-104")
    return code


def _driver_or_404(db: Session, did: int) -> Driver:
    drv = db.get(Driver, did)
    if not drv:
        raise HTTPException(404, "Driver not found")
    return drv


def _driver_dict(d: Driver, stats: dict | None = None) -> dict:
    s = stats or {}
    return {"id": d.id, "code": d.code, "name": d.name, "phone": d.phone, "hub": d.hub, "active": d.active,
            "pos_terminal": d.pos_terminal, "station_id": d.station_id,
            "station": d.station.name if d.station else "", "station_code": d.station.code if d.station else "",
            "last_collection": iso(s.get("last")), "days_collected": s.get("days", 0),
            "cash_shortage": to_sar(s.get("short", 0)), "open_advances": to_sar(s.get("advances", 0)),
            "open_advance_count": s.get("advance_count", 0)}


@app.get("/api/drivers")
def list_drivers(db: Session = Depends(get_db)):
    diff = Collection.cash_received - Collection.expected_cash
    coll = dict(
        (r.driver_id, {"last": r.last, "days": r.days, "short": -int(r.short or 0)})
        for r in db.query(Collection.driver_id, func.max(Collection.business_date).label("last"),
                          func.count(Collection.id).label("days"),
                          func.sum(case((diff < 0, diff), else_=0)).label("short"))
        .group_by(Collection.driver_id)
    )
    for r in (db.query(Expense.driver_id, func.sum(Expense.amount), func.count(Expense.id))
              .filter(Expense.category == "advance", Expense.settled_on.is_(None)).group_by(Expense.driver_id)):
        coll.setdefault(r[0], {}).update(advances=int(r[1]), advance_count=r[2])
    drivers = scope.drivers(db).order_by(Driver.active.desc(), Driver.code).all()
    return [_driver_dict(d, coll.get(d.id)) for d in drivers]


@app.post("/api/drivers", status_code=201)
def create_driver(body: DriverIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    code = _clean_code(body.code)
    if db.query(Driver).filter(func.upper(Driver.code) == code).first():
        raise HTTPException(409, f"A driver with ID {code} already exists")
    station_id = body.station_id or scope.current_station.get()
    if station_id is not None and not db.get(Station, station_id):
        raise HTTPException(404, "Station not found")
    drv = Driver(code=code, name=" ".join(body.name.split()), phone=body.phone.strip(), hub=body.hub.strip(),
                 pos_terminal=_clean_terminal(db, body.pos_terminal, None), station_id=station_id)
    db.add(drv)
    db.flush()
    audit.record(db, user, "created", "driver", drv.id, f"Added driver {code} {drv.name}")
    db.commit()
    return _driver_dict(drv)


@app.patch("/api/drivers/{did}")
def update_driver(did: int, body: DriverPatch, db: Session = Depends(get_db), user: str = Depends(current_user)):
    drv = _driver_or_404(db, did)
    if body.pos_terminal is not None:
        body.pos_terminal = _clean_terminal(db, body.pos_terminal, drv.id)
    if body.active and not drv.active and drv.pos_terminal:
        _clean_terminal(db, drv.pos_terminal, drv.id)  # reactivating must not create two drivers on one terminal
    changes = []
    if body.station_id is not None and body.station_id != drv.station_id:
        new = db.get(Station, body.station_id)
        if not new:
            raise HTTPException(404, "Station not found")
        changes.append(f"station: {drv.station.code if drv.station else 'none'} -> {new.code}")
        drv.station = new  # his past records stay with the station they happened at
    for field in ("name", "phone", "hub", "pos_terminal", "active"):
        value = getattr(body, field)
        if value is None:
            continue
        if isinstance(value, str):
            value = " ".join(value.split())
        if getattr(drv, field) != value:
            changes.append(f"{field}: {getattr(drv, field)!r} -> {value!r}")
            setattr(drv, field, value)
    if changes:
        audit.record(db, user, "updated", "driver", drv.id, f"{drv.code}: " + "; ".join(changes))
        db.commit()
    return _driver_dict(drv)


@app.delete("/api/drivers/{did}")
def delete_driver(did: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    drv = _driver_or_404(db, did)
    used = (db.query(Collection).execution_options(all_stations=True).filter_by(driver_id=did).count()
            + db.query(Expense).execution_options(all_stations=True).filter_by(driver_id=did).count())
    if used:
        raise HTTPException(409, f"{drv.code} has finance records, so it cannot be deleted. Mark the driver inactive instead")
    audit.record(db, user, "deleted", "driver", drv.id, f"Deleted driver {drv.code} {drv.name}")
    db.delete(drv)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- activity log

@app.get("/api/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 500))).all()
    return [{"id": r.id, "at": iso(r.at), "username": r.username, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "summary": r.summary} for r in rows]


class SettingsIn(BaseModel):
    cash_mode: str = Field(pattern="^(count|paid)$")


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    return {"cash_mode": collections.cash_mode(db)}


@app.put("/api/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = db.get(AppSetting, "cash_mode") or AppSetting(key="cash_mode")
    before = collections.cash_mode(db)
    s.value = body.cash_mode
    db.add(s)
    if before != body.cash_mode:
        text = {"count": "the desk counts each driver's cash", "paid": "orders are closed only when paid in full"}
        audit.record(db, user, "updated", "settings", None, f"Cash handover: {text[before]} -> {text[body.cash_mode]}")
    db.commit()
    return {"cash_mode": body.cash_mode}


@app.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    """Facts the screens need on load: currency and the latest business day that has data."""
    latest = db.query(func.max(Collection.business_date)).scalar()
    first = db.query(func.min(Collection.business_date)).scalar()
    return {"currency": settings.currency, "latest_business_date": iso(latest), "first_business_date": iso(first),
            "deposit_count": db.query(Deposit).count()}


# ---------------------------------------------------------------- login

class Credentials(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=auth.MAX_PASSWORD)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=auth.MAX_PASSWORD)
    new_password: str = Field(max_length=auth.MAX_PASSWORD)


def _set_cookie(resp: JSONResponse, token: str):
    resp.set_cookie(auth.COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                    samesite="lax", secure=settings.auth_cookie_secure, path="/")


@app.get("/api/auth/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    user = auth.user_for(db, request.cookies.get(auth.COOKIE)) if settings.auth_enabled else None
    return {"auth_enabled": settings.auth_enabled, "needs_setup": settings.auth_enabled and db.query(User).count() == 0,
            "user": {"username": user.username} if user else None}


@app.post("/api/auth/setup", status_code=201)
def auth_setup(body: Credentials, db: Session = Depends(get_db)):
    if not settings.auth_enabled:
        raise HTTPException(409, "Login is turned off for this server")
    if db.query(User).count():
        raise HTTPException(409, "An account already exists. Please log in")
    problem = auth.check_username(body.username) or auth.check_password_rules(body.password)
    if problem:
        raise HTTPException(422, problem)
    user = User(username=body.username, password_hash=auth.hash_password(body.password))
    db.add(user)
    db.commit()
    resp = JSONResponse(status_code=201, content={"user": {"username": user.username}})
    _set_cookie(resp, auth.start_session(db, user))
    return resp


@app.post("/api/auth/login")
def auth_login(body: Credentials, db: Session = Depends(get_db)):
    if auth.locked(body.username):
        raise HTTPException(429, "Too many wrong attempts. Wait 10 minutes and try again")
    user = auth.login_ok(db, body.username, body.password)
    if not user:
        auth.record_fail(body.username)
        raise HTTPException(401, "Wrong username or password")
    auth.clear_fails(body.username)
    resp = JSONResponse(content={"user": {"username": user.username}})
    _set_cookie(resp, auth.start_session(db, user))
    return resp


@app.post("/api/auth/logout")
def auth_logout(request: Request, db: Session = Depends(get_db)):
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    resp = JSONResponse(content={"logged_out": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.post("/api/auth/password")
def auth_password(body: PasswordChange, request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(auth.COOKIE)
    user = auth.user_for(db, token)
    if not user:
        raise HTTPException(401, "Please log in")
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Your current password is wrong")
    problem = auth.check_password_rules(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = auth.hash_password(body.new_password)
    db.commit()
    auth.end_other_sessions(db, user, token)  # other devices must log in again
    return {"changed": True}
