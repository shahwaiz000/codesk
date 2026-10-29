"""Import the driver list from a CSV or Excel file: driver ID, name, hub, mobile and POS terminal ID.

Same two steps as every import: check the file first (nothing saved), then save the good rows.
A driver ID that already exists is updated, never duplicated. A terminal can belong to only one
active driver, so a terminal used twice in the file, or already given to another driver, is refused."""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import audit
from .collections import COLUMNS as HANDOVER_COLUMNS
from .database import get_db
from .deps import current_user
from .files import FileProblem, clean_code, find_column, read_upload
from .models import Driver
from .terminals import TERMINAL_COLUMNS

router = APIRouter(prefix="/api/drivers", tags=["drivers"])

CODE_OK = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")  # the same rule as adding a driver by hand
COLUMNS = {
    "driver": HANDOVER_COLUMNS["driver"],
    "name": ("drivername", "couriername", "daname", "deliveryagentname", "fullname", "name", "employeename"),
    "hub": ("hub", "station", "branch", "area", "zone", "city"),
    "phone": ("mobile", "mobileno", "mobilenumber", "phone", "phoneno", "phonenumber", "contact"),
    "terminal": TERMINAL_COLUMNS["terminal"],
}
TEMPLATE = "Driver ID,Driver name,Hub,Mobile,POS terminal ID\nD-101,Example Driver,North Hub,0500000000,60311101\n"
FIELDS = ("name", "hub", "phone", "pos_terminal")


@router.get("/template")
def template():
    return Response(TEMPLATE, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="codesk-drivers-template.csv"'})


def _text(r, col) -> str:
    return " ".join(str(r[col]).split()) if col else ""


def _check(db: Session, df) -> list[dict]:
    cols = {k: find_column(df, v) for k, v in COLUMNS.items()}
    missing = [label for key, label in (("driver", "Driver ID"), ("name", "Driver name")) if not cols[key]]
    if missing:
        raise FileProblem(f"The file needs these columns: {', '.join(missing)}. Download the template to see the layout")
    existing = {d.code: d for d in db.query(Driver)}
    terminal_owner = {d.pos_terminal: d.code for d in existing.values() if d.active and d.pos_terminal}
    seen_codes: dict[str, int] = {}
    seen_terminals: dict[str, int] = {}
    out = []
    for i, r in df.iterrows():
        line, problems = i + 2, []
        code = clean_code(r[cols["driver"]])
        name = _text(r, cols["name"])
        hub = _text(r, cols["hub"])[:60]
        phone = clean_code(r[cols["phone"]]).replace(" ", "")[:20] if cols["phone"] else ""
        terminal = clean_code(r[cols["terminal"]]).replace(" ", "")[:30] if cols["terminal"] else ""
        if not code:
            problems.append("no driver ID")
        elif not CODE_OK.match(code):
            problems.append(f"driver ID '{code}' can only use letters, numbers and dashes")
        elif code in seen_codes:
            first = seen_codes[code]
            if (name, terminal) == first[1]:  # an order report lists a driver once per order: that is fine
                out.append({"line": line, "status": "skipped", "problems": [f"already in this file, row {first[0]}"],
                            "date": None, "driver_code": code, "driver_name": name, "hub": hub, "phone": phone,
                            "terminal": terminal or None, "inactive": False, "changes": [], "_values": {}})
                continue
            problems.append(f"driver repeated with different details, first on row {first[0]}")
        else:
            seen_codes[code] = (line, (name, terminal))
        if len(name) < 2:
            problems.append("no driver name")
        elif len(name) > 80:
            problems.append("name is longer than 80 characters")
        if terminal:
            owner = terminal_owner.get(terminal)
            if terminal in seen_terminals:
                problems.append(f"terminal {terminal} repeated, first on row {seen_terminals[terminal]}")
            elif owner and owner != code:
                problems.append(f"terminal {terminal} already belongs to {owner}")
            else:
                seen_terminals[terminal] = line
        values = {"name": name, "hub": hub, "phone": phone, "pos_terminal": terminal}
        drv = existing.get(code)
        status = "error" if problems else "new"
        changes = []
        if not problems and drv:
            # an empty cell never wipes what is already saved
            changes = [f for f in FIELDS if values[f] and getattr(drv, f) != values[f]]
            status = "update" if changes else "same"
        out.append({"line": line, "status": status, "problems": problems, "date": None, "driver_code": code or None,
                    "driver_name": name, "hub": hub, "phone": phone, "terminal": terminal or None,
                    "inactive": bool(drv and not drv.active), "changes": changes, "_values": values})
    return out


@router.post("/import")
async def import_drivers(file: UploadFile = File(...), commit: bool = Form(False),
                         db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        return run(db, file.filename or "file", await file.read(1 + 5_000_000), commit, user)
    except FileProblem as e:
        raise HTTPException(422, str(e))


def run(db: Session, filename: str, data: bytes, commit: bool, user: str) -> dict:
    """Check (and with commit, save) a driver list. Also used by the watch folder."""
    rows = _check(db, read_upload(filename, data))
    if not rows:
        raise FileProblem("The file has a header but no rows")
    saved = 0
    if commit:
        added = updated = 0
        for r in rows:
            v = r["_values"]
            if r["status"] == "new":
                d = Driver(code=r["driver_code"], **v)
                db.add(d)
                added += 1
            elif r["status"] == "update":
                d = db.query(Driver).filter_by(code=r["driver_code"]).one()
                before = "; ".join(f"{f}: {getattr(d, f)!r} -> {v[f]!r}" for f in r["changes"])
                for f in r["changes"]:
                    setattr(d, f, v[f])
                db.flush()
                audit.record(db, user, "updated", "driver", d.id, f"{d.code} (import {filename}): {before}")
                updated += 1
        saved = added + updated
        if saved:
            audit.record(db, user, "imported", "driver", None,
                         f"Driver import {filename}: {added} added, {updated} updated")
        db.commit()
    counts = {k: sum(r["status"] == k for r in rows) for k in ("new", "update", "same", "skipped", "error")}
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"file": filename, "rows": clean, "counts": counts, "committed": commit, "saved": saved, "dates": []}
