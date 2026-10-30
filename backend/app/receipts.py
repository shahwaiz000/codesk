"""Card machine receipts: the cashier photographs each machine's end-of-day settlement receipt and sends
the photos. The AI reads every receipt in a photo (terminal ID, date, number of payments, total, and the
payment lines), CODesk checks what was read, and the supervisor saves the totals as the day's card machine
sheet, which is then compared with the system's card payments.

Privacy, as everywhere in CODesk: the cloud AI only reads demo receipts (ai.py enforces it). With real data
the photos are shown next to a short form and the totals are typed from them."""
import base64
import io
import random
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import ai, audit, terminals
from .config import settings
from .database import get_db
from .deps import current_user, not_future, parse_day
from .models import Collection, Driver, PosOrder, TerminalTotal
from .money import to_halalas, to_sar
from .slip_reader import SlipProblem, to_image

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

MAX_FILES = 12
PROMPT = ("This photo shows one or more end-of-day settlement receipts printed by card payment terminals in Saudi Arabia "
          "(mada). Each receipt has REPORT and a date, TERMINAL ID, the merchant and branch, SETTLED TRANS with one line per "
          "payment (the amount is at the end of the line), DB: count and amount, and Total: amount DB. Read every receipt in "
          "the photo, left to right. Return JSON: {\"receipts\": [{\"terminal_id\": \"8 digits\", \"date\": \"YYYY-MM-DD\", "
          "\"branch\": \"text\", \"count\": number of payments (the DB count), \"total\": the Total amount as a number, "
          "\"lines\": [each payment amount as a number]}]}. Write numbers without thousands separators. If a value cannot "
          "be read, use null.")


def _num(v) -> float | None:
    try:
        return round(float(str(v).replace(",", "").replace("SAR", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def check_receipt(r: dict, day: date | None) -> dict:
    """Tidy what the AI read and say what to look at."""
    tid = "".join(ch for ch in str(r.get("terminal_id") or "") if ch.isdigit())
    total = _num(r.get("total"))
    lines = [x for x in (_num(v) for v in (r.get("lines") or [])) if x is not None]
    count = r.get("count")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None
    when = None
    try:
        when = date.fromisoformat(str(r.get("date"))[:10])
    except ValueError:
        pass
    checks = []
    if len(tid) != 8:
        checks.append({"ok": False, "text": "The terminal ID could not be read (8 digits)"})
    if total is None:
        checks.append({"ok": False, "text": "The total could not be read"})
    elif lines:
        s = round(sum(lines), 2)
        checks.append({"ok": abs(s - total) < 0.01, "text": f"The payment lines add up to {s:,.2f}" + ("" if abs(s - total) < 0.01 else f", not {total:,.2f}")})
    if count is not None and lines:
        checks.append({"ok": count == len(lines), "text": f"{count} payments on the receipt, {len(lines)} lines read"})
    if day and when:
        checks.append({"ok": when == day, "text": f"Dated {when:%d %b %Y}" + ("" if when == day else f", not {day:%d %b}")})
    elif not when:
        checks.append({"ok": False, "text": "The date could not be read"})
    return {"terminal": tid, "date": when.isoformat() if when else None, "branch": str(r.get("branch") or "")[:60],
            "count": count, "total": total, "lines": lines, "checks": checks}


def read_photo(db: Session, png: bytes) -> list[dict]:
    content = [{"type": "text", "text": PROMPT}, ai.image_part(base64.b64encode(png).decode())]
    msg = ai.chat(db, [{"role": "user", "content": content}], json_mode=True, timeout=settings.slip_timeout)
    answer = ai.parse_json(msg.get("content") or "")
    found = answer.get("receipts") if isinstance(answer, dict) else None
    return found if isinstance(found, list) else []


@router.post("/read")
async def read(files: list[UploadFile] = File(...), business_date: str = Form(...), db: Session = Depends(get_db),
               user: str = Depends(current_user)):
    """Read the receipts in each photo. Without an AI that may read them, the photos come back empty, to be
    typed from (the screen shows them)."""
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"At most {MAX_FILES} photos at once")
    day = not_future(parse_day(business_date, "business_date"))
    st = ai.status(db)
    can = st["ready"] and st["engine"] == "gemini"
    reason = "" if can else ("Typing the totals from the photos: the AI only reads demo receipts, so real company data never leaves this computer"
                             if not settings.seed_demo_data else st["reason"] or "Choose Google Gemini on the Settings page to let the AI read receipts")
    out = []
    for f in files:
        data = await f.read(1 + 15_000_000)
        item = {"file": f.filename, "receipts": [], "error": ""}
        if can:
            try:
                png = to_image(f.filename or "photo", data)
                item["receipts"] = [check_receipt(r, day) for r in read_photo(db, png) if isinstance(r, dict)]
                if not item["receipts"]:
                    item["error"] = "No receipt was found in this photo"
            except (SlipProblem, ai.AiProblem) as e:
                item["error"] = str(e)
        out.append(item)
    if can:
        n = sum(len(i["receipts"]) for i in out)
        audit.record(db, user, "read", "receipts", None, f"AI read {n} card machine receipts in {len(out)} photos for {day.isoformat()}")
        db.commit()
    return {"date": day.isoformat(), "ai": can, "reason": reason, "photos": out}


class Line(BaseModel):
    terminal: str = Field(min_length=4, max_length=30)
    amount: float | str


class SaveIn(BaseModel):
    date: str
    rows: list[Line] = Field(min_length=1, max_length=200)


@router.post("/save")
def save(body: SaveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Save the receipts' totals as the day's card machine sheet (a machine already saved is updated)."""
    day = not_future(parse_day(body.date, "date"))
    seen, rows = set(), []
    for line in body.rows:
        t = "".join(line.terminal.split()).upper()
        amount = to_halalas(line.amount)
        if amount is None or amount < 0:
            raise HTTPException(422, f"The total of machine {t} is not a number")
        if t in seen:
            raise HTTPException(422, f"Machine {t} is there twice")
        seen.add(t)
        old = db.query(TerminalTotal).filter_by(business_date=day, terminal=t).first()
        rows.append({"_day": day, "terminal": t, "_amount": amount, "_old": old,
                     "status": "new" if not old else "same" if old.amount == amount else "update"})
    saved = terminals.save_sheet(db, rows, user, "receipt photos")
    db.commit()
    total = to_sar(sum(r["_amount"] for r in rows))
    return {"saved": saved, "machines": len(rows), "total": total}


# ---------------------------------------------------------------- demo receipts

@router.get("/demo")
def demo(date_: str = Query(alias="date"), part: int = 1, db: Session = Depends(get_db)):
    """A photo of fictional settlement receipts for the demo: one per driver's card machine on the day,
    four to a photo (part 1, 2, 3...). Only in demo mode."""
    if not settings.seed_demo_data:
        raise HTTPException(404, "Demo receipts are only made in demo mode")
    from PIL import Image, ImageDraw, ImageFont
    day = parse_day(date_)
    per_driver = dict(db.query(PosOrder.driver_id, func.sum(PosOrder.amount)).filter(PosOrder.business_date == day).group_by(PosOrder.driver_id))
    lines_by = {}
    for o in db.query(PosOrder).filter(PosOrder.business_date == day).order_by(PosOrder.id):
        lines_by.setdefault(o.driver_id, []).append(o.amount)
    handed = {c.driver_id: c for c in db.query(Collection).filter(Collection.business_date == day)}
    machines = []
    for did in sorted(per_driver):
        d = db.get(Driver, did)
        h = handed.get(did)
        amount = h.pos_amount if h and h.pos_amount else int(per_driver[did])  # what the machine really took
        lines = list(lines_by.get(did, []))
        if lines and sum(lines) != amount:  # a machine short or over: the last payment differs
            lines[-1] += amount - sum(lines)
        machines.append(((h.pos_terminal if h and h.pos_terminal else d.pos_terminal) or f"6480{did:04d}", amount, lines))
    chunk = machines[(part - 1) * 4: part * 4]
    if not chunk:
        raise HTTPException(404, "No more card machines on this day")
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 19)
        big = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 22)
    except OSError:
        font = big = ImageFont.load_default()
    rnd = random.Random(day.toordinal() * 10 + part)
    w, h = 390 * len(chunk) + 60, 1000
    img = Image.new("RGB", (w, h), "#2b2f33")
    for i, (tid, amount, lines) in enumerate(chunk):
        x0 = 30 + i * 390
        height = 500 + 36 * len(lines)
        paper = Image.new("RGB", (360, min(height, h - 60)), "#f7f6f1")
        dr = ImageDraw.Draw(paper)
        y = 20
        for text, f in ((f"REPORT  {day:%d/%m/%Y}", big), (f"TERMINAL ID: {tid}", big), ("CODESK DEMO LOGISTICS", font),
                        ("Demo Branch", font), ("", font), ("   SETTLED TRANS", font), (f"{rnd.randint(16, 21)}:{rnd.randint(10, 59)}   {day:%d/%m/%Y}", font)):
            dr.text((14, y), text, fill="#222", font=f)
            y += 30
        for amt in lines:
            dr.text((14, y), f"{rnd.randint(1000, 2359)} PUR {rnd.randint(1000, 9999)}", fill="#555", font=font)
            dr.text((346, y), f"{to_sar(amt):.2f}", fill="#222", font=font, anchor="ra")
            y += 34
        for text in ("", "Cash Back: 0.00", f"DB: {len(lines)}  {to_sar(amount):.2f}", "CR: 0  0.00", "", f"Total: {to_sar(amount):.2f} DB",
                     "", " **END OF RECORD**"):
            dr.text((14, y), text, fill="#222", font=big if text.startswith("Total") else font)
            y += 30
        paper = paper.rotate(rnd.uniform(-2.5, 2.5), expand=True, fillcolor="#2b2f33")
        img.paste(paper, (x0, 30))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return Response(buf.getvalue(), media_type="image/jpeg",
                    headers={"Content-Disposition": f'attachment; filename="demo-receipts-{day.isoformat()}-{part}.jpg"'})


@router.get("/demo/parts")
def demo_parts(date_: str = Query(alias="date"), db: Session = Depends(get_db)):
    if not settings.seed_demo_data:
        return {"parts": 0}
    n = db.query(func.count(func.distinct(PosOrder.driver_id))).filter(PosOrder.business_date == parse_day(date_)).scalar() or 0
    return {"parts": -(-n // 4)}
