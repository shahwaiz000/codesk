"""The watch folder: save the day's files in one folder, and CODesk imports them by itself.

Every few seconds CODesk looks in the folder chosen on the Settings page. A new CSV or Excel file is
recognised by its columns (no special names needed) and imported with the same checks as the Import
buttons, saving only the good rows:

    collection report (one line per order)  -> new drivers, system POS orders, the day's handovers
    POS orders export (no driver names)     -> system POS orders
    terminal sheet (POS code + amount)      -> machine totals, matched with drivers
    expense sheet (driver + amount)         -> expenses and advances
    handover list, driver list              -> handovers, drivers
    PDF or photo                            -> a deposit slip, read by the local AI into a draft deposit

The file then moves to "Imported" (or "Problems" if it could not be read), so it is never imported
twice, and a line is kept in the watch log. A file still being copied, or open in Excel, waits."""
import hashlib
import shutil
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit, collections, driver_import, expense_import, pos, slip_reader
from .config import settings
from .database import SessionLocal, get_db
from .deps import current_user
from .files import FileProblem, find_column, find_header, read_upload
from .models import AppSetting, ImportedFile, iso, utcnow
from .terminals import TERMINAL_COLUMNS

router = APIRouter(prefix="/api/watch", tags=["watch"])

WHO = "watch folder"
TYPES = (".csv", ".xlsx") + slip_reader.TYPES  # a PDF or photo is a deposit slip
DONE, PROBLEMS = "Imported", "Problems"
KIND_TEXT = {"slip": "Deposit slip", "report": "Collection report", "orders": "System POS orders", "terminals": "Terminal sheet", "expenses": "Expense sheet",
             "handovers": "Handover list", "drivers": "Driver list"}

_lock = threading.Lock()
_seen: dict[str, tuple[int, float]] = {}  # file -> (size, modified) at the last look: a file must hold still once
_state = {"last_scan": None}


def folder(db: Session) -> str:
    s = db.get(AppSetting, "watch_folder")
    return s.value if s else ""


def detect(filename: str, data: bytes) -> str | None:
    """Which kind of file this is, from its columns."""
    raw = read_upload(filename, data, keep_unnamed=True)
    df = raw.loc[:, [not str(c).startswith("Unnamed") for c in raw.columns]]
    if collections._is_order_report(df):
        # the full collection report names the drivers; a plain POS-orders export does not
        return "report" if find_column(df, driver_import.COLUMNS["name"]) else "orders"
    if find_column(df, collections.COLUMNS["driver"]):
        if find_column(df, collections.COLUMNS["expected"]) and find_column(df, collections.COLUMNS["received"]):
            return "handovers"
        if find_column(df, expense_import.COLUMNS["amount"]):
            return "expenses"
        if find_column(df, driver_import.COLUMNS["name"]):
            return "drivers"
    if expense_import._no_header(df)[0] is not None:
        return "expenses"
    sheet, _ = find_header(raw, TERMINAL_COLUMNS["terminal"])
    if find_column(sheet, TERMINAL_COLUMNS["terminal"]):
        return "terminals"
    return None


def _counts(result: dict) -> str:
    c = result["counts"]
    parts = [f"{c[k]} {w}" for k, w in (("new", "new"), ("update", "updated"), ("error", "with problems")) if c.get(k)]
    return ", ".join(parts) or "nothing new"


def process(db: Session, filename: str, data: bytes) -> tuple[str | None, str, str]:
    """Import one file. Returns (kind, status, summary): status is done, attention (some rows had
    problems and were left out) or failed (the file could not be used)."""
    kind = None
    if filename.lower().endswith(slip_reader.TYPES):
        scan = slip_reader.read_slip(db, filename, data, WHO)
        if scan.status == "failed":
            return "slip", "failed", scan.error
        d = slip_reader.slip_dict(scan)
        bad = sum(not c["ok"] for c in d["checks"])
        return "slip", "attention" if bad else "done", (
            f"read {d['total'] or 0:,.2f}" + (f" for {d['business_date']}" if d["business_date"] else "")
            + (f", {bad} check(s) to look at" if bad else ", all checks passed") + ": confirm it on Bank deposits")
    try:
        kind = detect(filename, data)
        if not kind:
            return None, "failed", "Not recognised: no driver, order or POS code column found"
        if kind == "report":
            drv = driver_import.run(db, filename, data, True, WHO)
            orders = pos.run(db, "orders", filename, data, None, True, WHO)
            hand = collections.run(db, filename, data, None, True, WHO)
            results = (drv, orders, hand)
            days = ", ".join(sorted(set(orders["dates"]) | set(hand["dates"]))) or "-"
            summary = (f"{days}: drivers {_counts(drv)}; POS orders {_counts(orders)}; handovers {_counts(hand)}")
        else:
            run = {"orders": lambda: pos.run(db, "orders", filename, data, None, True, WHO),
                   "terminals": lambda: pos.run(db, "terminals", filename, data, None, True, WHO),
                   "expenses": lambda: expense_import.run(db, filename, data, None, True, WHO),
                   "handovers": lambda: collections.run(db, filename, data, None, True, WHO),
                   "drivers": lambda: driver_import.run(db, filename, data, True, WHO)}[kind]
            result = run()
            results = (result,)
            days = ", ".join(result["dates"])
            summary = (f"{days}: " if days else "") + _counts(result)
        bad = sum(r["counts"].get("error", 0) for r in results)
        return kind, "attention" if bad else "done", summary
    except FileProblem as e:
        db.rollback()
        return kind, "failed", str(e)


def _move(path: Path, sub: str) -> None:
    target = path.parent / sub
    target.mkdir(exist_ok=True)
    dest = target / path.name
    if dest.exists():
        dest = target / f"{datetime.now():%Y%m%d-%H%M%S} {path.name}"
    shutil.move(str(path), str(dest))


def scan(db: Session, wait: bool = True) -> list[dict]:
    """Look in the folder once and import what is ready. wait=False skips the hold-still check."""
    where = folder(db)
    if not where:
        return []
    base = Path(where)
    if not base.is_dir():
        return []
    out = []
    with _lock:
        _state["last_scan"] = utcnow()
        for path in sorted(base.iterdir()):
            if not path.is_file() or path.suffix.lower() not in TYPES or path.name.startswith(("~$", ".")):
                continue
            stat = path.stat()
            now = (stat.st_size, stat.st_mtime)
            if wait and _seen.get(str(path)) != now:
                _seen[str(path)] = now  # seen for the first time or still changing: next look
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue  # open in Excel or still being copied
            sha = hashlib.sha256(data).hexdigest()
            if db.query(ImportedFile).filter_by(sha256=sha, status="done").first():
                kind, status, summary = None, "done", "Already imported earlier: nothing to do"
            else:
                kind, status, summary = process(db, path.name, data)
            try:
                _move(path, PROBLEMS if status == "failed" else DONE)
            except OSError:
                db.rollback()
                continue  # could not move it (open in Excel): try again on the next look
            _seen.pop(str(path), None)
            row = ImportedFile(filename=path.name, kind=kind or "", status=status, summary=summary[:500], sha256=sha)
            db.add(row)
            audit.record(db, WHO, "imported", "file", None, f"{path.name} ({KIND_TEXT.get(kind, 'unknown')}): {summary}"[:500])
            db.commit()
            out.append(_file_dict(row))
    return out


def _file_dict(f: ImportedFile) -> dict:
    return {"id": f.id, "at": iso(f.at), "filename": f.filename, "kind": f.kind or None,
            "kind_text": KIND_TEXT.get(f.kind, "Unknown file"), "status": f.status, "summary": f.summary}


def _loop(stop: threading.Event):
    while not stop.wait(settings.watch_interval):
        db = SessionLocal()
        try:
            scan(db)
        except Exception:  # noqa: BLE001  the watcher must keep running; the next look tries again
            db.rollback()
        finally:
            db.close()


def start() -> threading.Event | None:
    if not settings.watch_enabled:
        return None
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="codesk-watch", daemon=True).start()
    return stop


# ---------------------------------------------------------------- the Settings panel

class WatchIn(BaseModel):
    folder: str = Field("", max_length=400)
    create: bool = False


@router.get("")
def status(db: Session = Depends(get_db)):
    where = folder(db)
    files = db.query(ImportedFile).order_by(ImportedFile.id.desc()).limit(20).all()
    return {"folder": where, "exists": bool(where) and Path(where).is_dir(), "running": settings.watch_enabled,
            "interval": settings.watch_interval, "last_scan": iso(_state["last_scan"]),
            "files": [_file_dict(f) for f in files]}


@router.put("")
def choose(body: WatchIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    where = body.folder.strip().strip('"')
    if where:
        path = Path(where).expanduser()
        if not path.is_absolute():
            raise HTTPException(422, r"Write the whole folder path, for example C:\Users\you\Documents\CODesk inbox")
        if not path.is_dir():
            if not body.create:
                raise HTTPException(404, "This folder does not exist yet")
            try:
                path.mkdir(parents=True)
            except OSError:
                raise HTTPException(422, "CODesk could not create this folder")
        where = str(path)
    s = db.get(AppSetting, "watch_folder") or AppSetting(key="watch_folder")
    before = s.value or "off"
    s.value = where
    db.add(s)
    audit.record(db, user, "updated", "settings", None, f"Watch folder: {before} -> {where or 'off'}")
    db.commit()
    return status(db)


@router.post("/scan")
def scan_now(db: Session = Depends(get_db), user: str = Depends(current_user)):
    if not folder(db):
        raise HTTPException(409, "Choose the watch folder first")
    return {"imported": scan(db, wait=False), **status(db)}
