"""Read a scanned bank deposit slip with a vision AI model that runs on this computer.

The model (through Ollama, free and local, so slips never leave the computer) only READS the slip:
date, bank, slip or seal number, the total, the amount in words, and each denomination line.
CODesk then CHECKS what was read with plain arithmetic, because a model can misread handwriting:

    every line:   notes x count = the line amount
    all lines:    add up to the total
    in words:     the amount in words says the same as the total
    the day:      which business day's cash this is (a day still to deposit, with the same amount
                  within rounding, deposited on or after that day)

Nothing is recorded by the AI. A slip that was read becomes a draft on the Bank deposits page,
with its picture, what was read and the checks, and a person records it with one click."""
import base64
import io
import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit, deposits
from .config import settings
from .database import get_db
from .deps import current_user, parse_day
from .files import read_date
from .models import SlipScan, iso
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/slips", tags=["slips"])

TYPES = (".pdf", ".jpg", ".jpeg", ".png")
MAX_SIDE = 1400  # pixels: enough for handwriting, small enough for a laptop model
NOTES = (500, 200, 100, 50, 20, 10, 5, 1)

SCHEMA = {
    "type": "object",
    "properties": {
        "bank": {"type": "string"},
        "date": {"type": "string", "description": "the date written on the slip, exactly as written"},
        "slip_number": {"type": "string", "description": "slip, seal or reference number, empty if none"},
        "total": {"type": "number"},
        "amount_in_words": {"type": "string"},
        "denominations": {"type": "array", "items": {"type": "object", "properties": {
            "note": {"type": "number"}, "count": {"type": "number"}, "amount": {"type": "number"}},
            "required": ["note", "count", "amount"]}},
    },
    "required": ["bank", "date", "slip_number", "total", "amount_in_words", "denominations"],
}
PROMPT = ("This is a scanned cash deposit slip from a Saudi bank, filled in by hand. Read it carefully and return JSON. "
          "bank: the bank's name in English. date: the date written in the Date box. slip_number: the slip, seal or "
          "reference number, or empty. total: the TOTAL of the cash denominations. amount_in_words: the amount written "
          "in words. denominations: one item for each filled cash line: note value (500, 200, 100, 50, 20, 10, 5 or 1), "
          "the count of notes written by hand, and the line amount written on the right. Skip empty lines. "
          "Copy what is written; do not correct the arithmetic.")


class SlipProblem(Exception):
    pass


# ---------------------------------------------------------------- reading

def to_image(filename: str, data: bytes) -> bytes:
    """The slip as a PNG no larger than MAX_SIDE: a PDF's first page, or the photo itself."""
    from PIL import Image
    name = filename.lower()
    if name.endswith(".pdf"):
        import pymupdf
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if not doc.page_count:
                    raise SlipProblem("The PDF has no pages")
                page = doc[0]
                zoom = min(3.0, MAX_SIDE / max(page.rect.width, page.rect.height))
                png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
        except SlipProblem:
            raise
        except Exception:
            raise SlipProblem("This PDF could not be opened")
        img = Image.open(io.BytesIO(png))
    else:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            raise SlipProblem("This picture could not be opened")
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _ollama(path: str, body: dict | None = None, timeout: float = 5) -> dict:
    req = urllib.request.Request(settings.ollama_url.rstrip("/") + path, method="POST" if body else "GET",
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  a fixed local address from settings
        return json.loads(r.read())


def ai_status() -> dict:
    """Is the local AI ready? Ollama running, and the slip model downloaded."""
    try:
        models = [m.get("name", "") for m in _ollama("/api/tags").get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return {"ready": False, "ollama": False, "model": settings.slip_model, "has_model": False}
    has = any(m == settings.slip_model or m == settings.slip_model + ":latest" for m in models)
    return {"ready": has, "ollama": True, "model": settings.slip_model, "has_model": has}


def ask_model(png: bytes) -> dict:
    """Send the picture to the local model and get back what it read."""
    body = {"model": settings.slip_model, "prompt": PROMPT, "images": [base64.b64encode(png).decode()],
            "format": SCHEMA, "stream": False, "think": False, "options": {"temperature": 0}}
    try:
        answer = _ollama("/api/generate", body, timeout=settings.slip_timeout)
    except urllib.error.HTTPError as e:
        raise SlipProblem(f"The AI model could not read the slip ({e.code}). Is {settings.slip_model} downloaded?")
    except (urllib.error.URLError, OSError):
        raise SlipProblem("The AI is not running. Start Ollama, then read the slip again")
    try:
        return json.loads(answer.get("response") or "{}")
    except ValueError:
        raise SlipProblem("The AI's answer could not be understood. Read the slip again")


# ---------------------------------------------------------------- checking

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen".split())}
WORDS.update({w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())})


def words_to_number(text: str) -> int | None:
    """'seven thousand nine hundred twenty five' -> 7925. Halalas and currency words are ignored."""
    text = re.split(r"\b(?:and\s+)?(?:halala|halalas)\b", text.lower())[0]
    total = part = 0
    found = False
    for w in re.findall(r"[a-z]+", text.replace("fourty", "forty")):
        if w in WORDS:
            part += WORDS[w]
        elif w == "hundred":
            part = (part or 1) * 100
        elif w in ("thousand", "million"):
            total += (part or 1) * (1000 if w == "thousand" else 1_000_000)
            part = 0
        elif w in ("and", "sar", "riyal", "riyals", "saudi", "only"):
            continue
        else:
            continue
        found = True
    return total + part if found else None


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def check(fields: dict, db: Session) -> dict:
    """Check what the AI read, and suggest the business day this deposit is for."""
    checks = []
    lines = [d for d in fields.get("denominations") or [] if _num(d.get("count"))]
    total = _num(fields.get("total"))
    for d in lines:
        note, count, amount = _num(d.get("note")), _num(d.get("count")), _num(d.get("amount"))
        if note not in NOTES:
            checks.append({"ok": False, "text": f"{note:g} is not a banknote value"})
        elif amount is not None and abs(note * count - amount) > 0.005:
            checks.append({"ok": False, "text": f"{note:g} x {count:g} = {note * count:,.2f}, but the line says {amount:,.2f}"})
    if lines and total is not None:
        added = sum(_num(d["note"]) * _num(d["count"]) for d in lines if _num(d.get("note")))
        ok = abs(added - total) < 0.005
        checks.append({"ok": ok, "text": f"The notes add up to {added:,.2f}" + ("" if ok else f", but the total says {total:,.2f}")})
    elif total is None:
        checks.append({"ok": False, "text": "No total could be read"})
    in_words = words_to_number(fields.get("amount_in_words") or "")
    if in_words is not None and total is not None:
        ok = abs(in_words - total) < 1
        checks.append({"ok": ok, "text": f"The amount in words says {in_words:,}" + ("" if ok else f", not {total:,.2f}")})
    deposit_day = read_date(fields.get("date") or "")
    if not deposit_day:
        checks.append({"ok": False, "text": "The date could not be read"})
    elif deposit_day > date.today():
        checks.append({"ok": False, "text": f"The date {deposit_day:%d %b %Y} is in the future"})
        deposit_day = None

    # which day's cash: a day still to deposit, on or before the slip's date, with the same amount within rounding
    day = None
    if total is not None:
        amount = to_halalas(total)
        candidates = [r for r in deposits.ledger(db) if r["pending"] > 0
                      and (deposit_day is None or date.fromisoformat(r["date"]) <= deposit_day)
                      and deposits.rounded(to_halalas(r["pending"]), amount)]
        if len(candidates) == 1:
            day = candidates[0]["date"]
            gap = round(total - candidates[0]["pending"], 2)
            checks.append({"ok": True, "text": f"Matches the cash of {date.fromisoformat(day):%a %d %b} ({candidates[0]['pending']:,.2f})"
                           + (f", rounded {gap:+,.2f}" if gap else "")})
        elif len(candidates) > 1:
            checks.append({"ok": False, "text": "More than one day has this amount: choose the day"})
        else:
            checks.append({"ok": False, "text": "No day still to deposit has this amount: check the slip or choose the day"})
    return {"checks": checks, "business_date": day, "deposit_date": deposit_day.isoformat() if deposit_day else None}


# ---------------------------------------------------------------- the drafts

def slip_dir() -> Path:
    path = Path(settings.data_dir) / "slips"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_slip(db: Session, filename: str, data: bytes, user: str) -> SlipScan:
    """Read one slip into a draft. A slip that cannot be read is kept as failed, with the reason."""
    scan = SlipScan(filename=filename[:260], status="failed", created_by=user)
    db.add(scan)
    db.flush()
    try:
        png = to_image(filename, data)
        (slip_dir() / f"{scan.id}.png").write_bytes(png)
        scan.has_image = True
        fields = ask_model(png)
        result = check(fields, db)
        scan.fields = json.dumps(fields)
        scan.checks = json.dumps(result["checks"])
        scan.business_date = date.fromisoformat(result["business_date"]) if result["business_date"] else None
        scan.deposit_date = date.fromisoformat(result["deposit_date"]) if result["deposit_date"] else None
        scan.status = "draft"
        audit.record(db, user, "read", "slip", scan.id, f"Deposit slip {filename} read: {_num(fields.get('total')) or 0:,.2f}"
                     + (f" for {scan.business_date.isoformat()}" if scan.business_date else ""))
    except SlipProblem as e:
        scan.error = str(e)
    db.commit()
    return scan


def slip_dict(s: SlipScan) -> dict:
    fields = json.loads(s.fields or "{}")
    return {"id": s.id, "at": iso(s.at), "filename": s.filename, "status": s.status, "error": s.error or None,
            "bank": fields.get("bank") or "", "slip_number": fields.get("slip_number") or "",
            "date_written": fields.get("date") or "", "total": _num(fields.get("total")),
            "amount_in_words": fields.get("amount_in_words") or "",
            "denominations": [{"note": _num(d.get("note")), "count": _num(d.get("count")), "amount": _num(d.get("amount"))}
                              for d in fields.get("denominations") or []],
            "checks": json.loads(s.checks or "[]"),
            "business_date": s.business_date.isoformat() if s.business_date else None,
            "deposit_date": s.deposit_date.isoformat() if s.deposit_date else None,
            "has_image": s.has_image, "deposit_id": s.deposit_id}


@router.get("/ai")
def ai():
    return ai_status()


@router.get("")
def drafts(db: Session = Depends(get_db)):
    rows = db.query(SlipScan).filter(SlipScan.status.in_(("draft", "failed"))).order_by(SlipScan.id.desc()).limit(20).all()
    return [slip_dict(s) for s in rows]


@router.post("/read")
async def read(file: UploadFile = File(...), db: Session = Depends(get_db), user: str = Depends(current_user)):
    name = file.filename or "slip"
    if Path(name).suffix.lower() not in TYPES:
        raise HTTPException(422, "Upload the slip as a PDF, JPG or PNG")
    data = await file.read(1 + 15_000_000)
    if len(data) > 15_000_000:
        raise HTTPException(422, "The file is larger than 15 MB")
    return slip_dict(read_slip(db, name, data, user))


@router.get("/{sid}/image")
def image(sid: int, db: Session = Depends(get_db)):
    s = db.get(SlipScan, sid)
    path = slip_dir() / f"{sid}.png"
    if not s or not path.exists():
        raise HTTPException(404, "No picture for this slip")
    return Response(path.read_bytes(), media_type="image/png")


class RecordIn(BaseModel):
    business_date: str
    deposit_date: str
    bank: str = Field(min_length=2, max_length=60)
    slip_ref: str = Field(min_length=2, max_length=60)
    amount: float | str


@router.post("/{sid}/record")
def record(sid: int, body: RecordIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = db.get(SlipScan, sid)
    if not s or s.status != "draft":
        raise HTTPException(404, "This slip is not waiting to be recorded")
    row = deposits.add_deposit(deposits.DepositIn(business_date=body.business_date, deposit_date=body.deposit_date,
                                                  bank=body.bank, slip_ref=body.slip_ref, amount=body.amount,
                                                  note=f"read from {s.filename}"), db, user)
    slip = next(x for x in row["slips"] if x["slip_ref"] == " ".join(body.slip_ref.split()).upper())
    s.status, s.deposit_id = "recorded", slip["id"]
    db.commit()
    return row


@router.post("/{sid}/dismiss")
def dismiss(sid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = db.get(SlipScan, sid)
    if not s or s.status not in ("draft", "failed"):
        raise HTTPException(404, "This slip is not waiting")
    s.status = "dismissed"
    audit.record(db, user, "dismissed", "slip", s.id, f"Deposit slip {s.filename} put aside")
    db.commit()
    return {"dismissed": True}
