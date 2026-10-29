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
import zlib
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import scope, ai, audit, deposits
from .config import settings
from .database import get_db
from .deps import current_user, parse_day
from .files import read_date
from .models import SlipScan, iso
from .money import to_halalas, to_sar

router = APIRouter(prefix="/api/slips", tags=["slips"])

TYPES = (".pdf", ".jpg", ".jpeg", ".png")
MAX_SIDE = 1100  # pixels: enough for handwriting, small enough for a laptop model's memory
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


def _downloaded() -> list[str] | None:
    """The slip models downloaded in Ollama, best first; None when Ollama is not running."""
    try:
        names = {m.get("name", "") for m in _ollama("/api/tags").get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [m for m in (settings.slip_model, settings.slip_model_small) if m in names or m + ":latest" in names]


def ai_status() -> dict:
    """Is the local AI ready? Ollama running, and a slip model downloaded."""
    have = _downloaded()
    return {"ready": bool(have), "ollama": have is not None, "model": settings.slip_model, "small_model": settings.slip_model_small,
            "has_model": bool(have), "models": have or []}


def _error_text(e: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(e.read() or b"{}").get("error") or "")
    except (ValueError, OSError):
        return ""


def _no_room(why: str) -> bool:
    w = why.lower()
    return "memory" in w or "alloc" in w


def ask_model(png: bytes) -> dict:
    """Send the picture to the local model and get back what it read. When the bigger model does not fit
    in the laptop's memory, the smaller one is tried."""
    models = _downloaded()
    if models is None:
        raise SlipProblem("The AI is not running. Start Ollama, then read the slip again")
    if not models:
        raise SlipProblem(f"No slip model is downloaded. In PowerShell run: ollama pull {settings.slip_model_small}")
    image = base64.b64encode(png).decode()
    why = ""
    for model in models:
        body = {"model": model, "prompt": PROMPT, "images": [image], "format": SCHEMA, "stream": False, "think": False,
                "keep_alive": 0,  # give the memory back as soon as the slip is read
                "options": {"temperature": 0, "num_ctx": settings.slip_context}}
        for _ in range(2):
            try:
                answer = _ollama("/api/generate", body, timeout=settings.slip_timeout)
                try:
                    return json.loads(answer.get("response") or "{}")
                except ValueError:
                    raise SlipProblem("The AI's answer could not be understood. Read the slip again")
            except urllib.error.HTTPError as e:
                why = _error_text(e) or str(e.code)
                if "think" in why.lower() and "think" in body:  # an older Ollama, or a model without the switch
                    body.pop("think")
                    continue
                break
            except (urllib.error.URLError, OSError):
                raise SlipProblem("The AI is not running, or stopped while reading. Start Ollama, then read the slip again")
        if not _no_room(why):
            raise SlipProblem(f"The AI could not read the slip: {why}")
    if settings.slip_model_small not in models:
        raise SlipProblem(f"The AI does not fit in this laptop's free memory. Download the smaller model: in PowerShell run "
                          f"ollama pull {settings.slip_model_small}, then read the slip again")
    raise SlipProblem("The AI does not fit in this laptop's free memory. Close other programs (browser tabs, Excel, Teams) "
                      "and read the slip again")


def ask_cloud(db: Session, png: bytes) -> dict:
    """The same reading through the cloud engine (demo data only, see ai.py)."""
    shape = json.dumps(SCHEMA["properties"])
    content = [{"type": "text", "text": PROMPT + f" Answer with one JSON object with these fields: {shape}"},
               ai.image_part(base64.b64encode(png).decode())]
    try:
        msg = ai.chat(db, [{"role": "user", "content": content}], json_mode=True, timeout=settings.slip_timeout)
        return ai.parse_json(msg.get("content") or "")
    except ai.AiProblem as e:
        raise SlipProblem(str(e))


def read_with_engine(db: Session, png: bytes) -> dict:
    return ask_cloud(db, png) if ai.engine(db) == "gemini" else ask_model(png)


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
            checks.append({"ok": True, "text": scope.named(candidates[0], f"Matches the cash of {date.fromisoformat(day):%a %d %b} ({candidates[0]['pending']:,.2f})")
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
    except SlipProblem as e:
        scan.error = str(e)
        db.commit()
        return scan
    return _read_picture(db, scan, png, user)


def _read_picture(db: Session, scan: SlipScan, png: bytes, user: str) -> SlipScan:
    filename = scan.filename
    scan.status, scan.error = "failed", ""
    try:
        fields = read_with_engine(db, png)
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
def ai_ready(db: Session = Depends(get_db)):
    """Is the slip reader ready? With the cloud engine, that is the engine's own status."""
    if ai.engine(db) == "gemini":
        st = ai.status(db)
        return {"ready": st["ready"], "ollama": True, "model": st["gemini_model"], "small_model": "", "has_model": True,
                "models": [], "engine": "gemini", "reason": st["reason"]}
    return {**ai_status(), "engine": "local", "reason": ""}


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


@router.post("/{sid}/retry")
def retry(sid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Read a slip that failed again, from the picture already saved."""
    s = db.get(SlipScan, sid)
    path = slip_dir() / f"{sid}.png"
    if not s or s.status != "failed" or not path.exists():
        raise HTTPException(404, "This slip cannot be read again: upload it once more")
    return slip_dict(_read_picture(db, s, path.read_bytes(), user))


ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_to_words(n: int) -> str:
    def small(x: int) -> str:
        out = []
        if x >= 100:
            out.append(f"{ONES[x // 100]} hundred")
            x %= 100
        if x >= 20:
            out.append(TENS[x // 10 - 2] + (f" {ONES[x % 10]}" if x % 10 else ""))
        elif x:
            out.append(ONES[x])
        return " ".join(out)
    if n == 0:
        return "zero"
    parts = []
    if n >= 1000:
        parts.append(f"{small(n // 1000)} thousand")
        n %= 1000
    if n:
        parts.append(small(n))
    return " ".join(parts)


@router.get("/demo-slip")
def demo_slip(db: Session = Depends(get_db)):
    """A fictional, hand-filled deposit slip for the latest day still to deposit, to try the slip reader
    in demo mode. Only in demo mode: it is made from the fictional demo figures."""
    if not settings.seed_demo_data:
        raise HTTPException(404, "Demo slips are only made in demo mode")
    from PIL import Image, ImageDraw, ImageFont
    row = next((r for r in deposits.ledger(db) if r["pending"] > 0), None)
    if not row:
        raise HTTPException(409, "No day is waiting to be deposited")
    total = int(-(-row["pending"] // 5) * 5)  # rounded up to whole notes, as at the bank
    left, lines = total, []
    for note in (500, 200, 100, 50, 20, 10, 5):
        count = left // note
        if count:
            lines.append((note, count))
            left -= note * count
    day = next(r for r in deposits.ledger(db) if r["date"] == row["date"])["due_on"]
    img = Image.new("RGB", (1100, 1450), "#fdfdfb")
    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        for name in (("DejaVuSans-Bold.ttf", "arialbd.ttf") if bold else ("DejaVuSans.ttf", "arial.ttf")):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()
    pen, ink = "#1d3fa3", "#222222"
    d.rectangle((30, 30, 1070, 1420), outline=ink, width=3)
    d.text((60, 55), "COASTAL NATIONAL BANK", fill="#0f2e22", font=font(38, True))
    d.text((60, 105), "Cash deposit slip  (fictional bank, demo data)", fill="#7c8781", font=font(22))
    d.text((60, 180), "Date", fill=ink, font=font(24)); d.text((180, 172), f"{date.fromisoformat(day):%d-%b-%Y}", fill=pen, font=font(34))
    d.text((560, 180), "Slip no.", fill=ink, font=font(24)); d.text((680, 172), f"CN-{zlib.crc32(row['date'].encode()) % 90000 + 10000}", fill=pen, font=font(34))
    d.text((60, 250), "Customer", fill=ink, font=font(24)); d.text((200, 242), "CODesk Logistics (demo)", fill=pen, font=font(32))
    y = 340
    d.text((560, y - 50), "Cash denomination", fill=ink, font=font(24, True))
    for note in (500, 200, 100, 50, 20, 10, 5, 1):
        count = dict(lines).get(note)
        d.rectangle((540, y, 1040, y + 58), outline="#999999", width=1)
        d.text((560, y + 14), f"{note} x", fill=ink, font=font(26))
        if count:
            d.text((680, y + 6), str(count), fill=pen, font=font(36))
            d.text((850, y + 6), f"{note * count:,}", fill=pen, font=font(36))
        y += 58
    d.rectangle((540, y, 1040, y + 66), outline=ink, width=2)
    d.text((560, y + 18), "TOTAL", fill=ink, font=font(26, True))
    d.text((820, y + 10), f"{total:,}", fill=pen, font=font(40))
    d.text((60, y + 110), "Amount in words", fill=ink, font=font(24))
    d.text((60, y + 150), number_to_words(total), fill=pen, font=font(32))
    d.text((60, 1360), "Depositor signature", fill="#999999", font=font(20))
    out = io.BytesIO()
    img.rotate(-0.8, expand=False, fillcolor="#fdfdfb").save(out, "PNG")
    return Response(out.getvalue(), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="demo slip {row["date"]}.png"'})


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
    station_id: int | None = None


def _station_for(db: Session, body: RecordIn) -> int | None:
    """In the all-stations view, the station whose cash on that day has the slip's amount."""
    if body.station_id or scope.station() is not None:
        return body.station_id
    try:
        amount = to_halalas(body.amount)
    except Exception:  # noqa: BLE001  the deposit check below gives the clear message
        return None
    rows = [r for r in deposits.ledger(db) if r["date"] == body.business_date and r["pending"] > 0]
    fits = [r for r in rows if deposits.rounded(to_halalas(r["pending"]), amount)] or rows
    return fits[0]["station_id"] if len(fits) == 1 else None


@router.post("/{sid}/record")
def record(sid: int, body: RecordIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = db.get(SlipScan, sid)
    if not s or s.status != "draft":
        raise HTTPException(404, "This slip is not waiting to be recorded")
    row = deposits.add_deposit(deposits.DepositIn(business_date=body.business_date, deposit_date=body.deposit_date,
                                                  bank=body.bank, slip_ref=body.slip_ref, amount=body.amount,
                                                  station_id=_station_for(db, body), note=f"read from {s.filename}"), db, user)
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
