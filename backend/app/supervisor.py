"""The cashier supervisor's tools: the day sign-off, the follow-ups raised with cashiers, a ready-made
message to a cashier, and each cashier's monthly scorecard.

A station's cashier sends the day's files; the supervisor checks them in CODesk, marks the day as checked,
and raises a follow-up for anything wrong, which stays open until it is sorted out."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import ai, audit, pos
from .database import get_db
from .deposits import ledger
from .deps import current_user, parse_day
from .models import DayCheck, FollowUp, FollowUpNote, Station
from .money import to_halalas, to_sar
from .scope import current_station

router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])

KINDS = {"deposit_short": "Deposit short", "deposit_late": "Deposit late", "card_sheet": "Card sheet difference",
         "missing_file": "File missing", "other": "Other"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _station(db: Session, sid: int | None) -> Station:
    sid = sid or current_station.get()
    s = db.get(Station, sid) if sid else None
    if not s:
        raise HTTPException(422, "Choose the station first")
    return s


# ---------------------------------------------------------------- the day sign-off

def check_dict(c: DayCheck | None) -> dict | None:
    return {"checked_by": c.checked_by, "checked_at": c.checked_at.isoformat() + "Z", "note": c.note} if c else None


def checks_for(db: Session, day: date) -> dict[int, dict]:
    return {c.station_id: check_dict(c) for c in db.query(DayCheck).filter(DayCheck.business_date == day)}


class CheckIn(BaseModel):
    date: str
    station_id: int | None = None
    note: str = Field("", max_length=300)


@router.get("/check")
def get_check(date_: str = Query(alias="date"), station_id: int | None = None, db: Session = Depends(get_db)):
    s = _station(db, station_id)
    c = db.query(DayCheck).filter_by(station_id=s.id, business_date=parse_day(date_)).first()
    return {"station_id": s.id, "date": date_, "check": check_dict(c)}


@router.post("/check")
def mark_checked(body: CheckIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s, day = _station(db, body.station_id), parse_day(body.date)
    c = db.query(DayCheck).filter_by(station_id=s.id, business_date=day).first() or DayCheck(station_id=s.id, business_date=day)
    c.checked_by, c.checked_at, c.note = user, _now(), " ".join(body.note.split())
    db.add(c)
    audit.record(db, user, "checked", "station", s.id, f"{s.name}: day {day.isoformat()} checked" + (f" ({c.note})" if c.note else ""))
    db.commit()
    return {"station_id": s.id, "date": body.date, "check": check_dict(c)}


@router.delete("/check")
def undo_check(date_: str = Query(alias="date"), station_id: int | None = None, db: Session = Depends(get_db),
               user: str = Depends(current_user)):
    s, day = _station(db, station_id), parse_day(date_)
    c = db.query(DayCheck).filter_by(station_id=s.id, business_date=day).first()
    if c:
        db.delete(c)
        audit.record(db, user, "unchecked", "station", s.id, f"{s.name}: day {day.isoformat()} no longer marked as checked")
        db.commit()
    return {"station_id": s.id, "date": date_, "check": None}


# ---------------------------------------------------------------- follow-ups

def follow_dict(f: FollowUp) -> dict:
    return {"id": f.id, "station_id": f.station_id, "station": f.station.name, "station_code": f.station.code,
            "cashier_name": f.station.cashier_name or "", "cashier_phone": f.station.cashier_phone or "",
            "date": f.business_date.isoformat() if f.business_date else None, "kind": f.kind, "kind_text": KINDS.get(f.kind, f.kind),
            "title": f.title, "amount": to_sar(f.amount), "status": f.status, "created_by": f.created_by,
            "created_at": f.created_at.isoformat() + "Z", "closed_by": f.closed_by,
            "closed_at": f.closed_at.isoformat() + "Z" if f.closed_at else None,
            "days_open": ((f.closed_at or _now()).date() - f.created_at.date()).days,
            "notes": [{"id": n.id, "text": n.text, "by": n.by, "at": n.at.isoformat() + "Z"} for n in f.notes]}


@router.get("/follow-ups")
def follow_ups(status: str = "open", db: Session = Depends(get_db)):
    q = db.query(FollowUp)
    if current_station.get() is not None:
        q = q.filter(FollowUp.station_id == current_station.get())
    if status in ("open", "closed"):
        q = q.filter(FollowUp.status == status)
    rows = q.order_by(FollowUp.status.desc(), FollowUp.created_at.desc()).limit(300).all()
    counts = dict(db.query(FollowUp.status, func.count(FollowUp.id)).filter(
        *([FollowUp.station_id == current_station.get()] if current_station.get() is not None else [])).group_by(FollowUp.status))
    return {"rows": [follow_dict(f) for f in rows], "open": counts.get("open", 0), "closed": counts.get("closed", 0)}


class FollowIn(BaseModel):
    station_id: int | None = None
    date: str | None = None
    kind: str = Field("other", pattern="^(deposit_short|deposit_late|card_sheet|missing_file|other)$")
    title: str = Field(min_length=3, max_length=200)
    amount: float | str = 0
    note: str = Field("", max_length=600)


@router.post("/follow-ups", status_code=201)
def raise_follow_up(body: FollowIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = _station(db, body.station_id)
    amount = to_halalas(body.amount) if str(body.amount).strip() else 0
    if amount is None or amount < 0:
        raise HTTPException(422, "The amount is not a number")
    f = FollowUp(station_id=s.id, business_date=parse_day(body.date) if body.date else None, kind=body.kind,
                 title=" ".join(body.title.split()), amount=amount, created_by=user)
    if body.note.strip():
        f.notes.append(FollowUpNote(text=" ".join(body.note.split()), by=user))
    db.add(f)
    db.flush()
    audit.record(db, user, "created", "follow-up", f.id, f"{s.name}: {f.title}")
    db.commit()
    return follow_dict(f)


class NoteIn(BaseModel):
    text: str = Field(min_length=2, max_length=600)


@router.post("/follow-ups/{fid}/notes")
def add_note(fid: int, body: NoteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    f = db.get(FollowUp, fid) or _missing()
    f.notes.append(FollowUpNote(text=" ".join(body.text.split()), by=user))
    db.commit()
    return follow_dict(f)


class CloseIn(BaseModel):
    note: str = Field("", max_length=600)


@router.post("/follow-ups/{fid}/close")
def close(fid: int, body: CloseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    f = db.get(FollowUp, fid) or _missing()
    if body.note.strip():
        f.notes.append(FollowUpNote(text=" ".join(body.note.split()), by=user))
    f.status, f.closed_by, f.closed_at = "closed", user, _now()
    audit.record(db, user, "closed", "follow-up", f.id, f"{f.station.name}: {f.title}")
    db.commit()
    return follow_dict(f)


@router.post("/follow-ups/{fid}/reopen")
def reopen(fid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    f = db.get(FollowUp, fid) or _missing()
    f.status, f.closed_by, f.closed_at = "open", "", None
    audit.record(db, user, "reopened", "follow-up", f.id, f"{f.station.name}: {f.title}")
    db.commit()
    return follow_dict(f)


def _missing():
    raise HTTPException(404, "Follow-up not found")


# ---------------------------------------------------------------- a message to the cashier

TEMPLATES = {
    "en": {"greet": "Dear {name},", "greet_any": "Dear cashier,",
           "deposit_short": "The bank deposit for the cash of {day} is {amount} SAR short. Please deposit the missing amount today and send me the bank slip.",
           "deposit_late": "The cash of {day} ({amount} SAR) is not in the bank yet, and it was due on the next working day. Please deposit it today and send me the bank slip.",
           "card_sheet": "The card machine sheet for {day} does not match the card payments in the system: the difference is {amount} SAR. Please check the machines and send me the corrected sheet.",
           "missing_file": "I have not received {title_lc} for {day}. Please send it today.",
           "other": "About {day}: {title}. Please check and reply.",
           "end": "Thank you.\n{me}, Cashier Supervisor"},
    "ar": {"greet": "عزيزي {name}،", "greet_any": "عزيزي أمين الصندوق،",
           "deposit_short": "إيداع نقدية يوم {day} في البنك ناقص بمبلغ {amount} ريال. نرجو إيداع المبلغ الناقص اليوم وإرسال إيصال البنك.",
           "deposit_late": "نقدية يوم {day} (بمبلغ {amount} ريال) لم تُودع في البنك بعد، وكان موعدها يوم العمل التالي. نرجو إيداعها اليوم وإرسال إيصال البنك.",
           "card_sheet": "كشف أجهزة الشبكة ليوم {day} لا يطابق مدفوعات البطاقات في النظام، والفرق {amount} ريال. نرجو مراجعة الأجهزة وإرسال الكشف المصحح.",
           "missing_file": "لم يصلني {title} ليوم {day}. نرجو إرساله اليوم.",
           "other": "بخصوص يوم {day}: {title}. نرجو المراجعة والرد.",
           "end": "شكراً لكم.\n{me}، مشرف الصناديق"},
}


def template_message(f: FollowUp, lang: str, me: str) -> str:
    t = TEMPLATES[lang]
    day = f.business_date.strftime("%d %b %Y") if f.business_date else ("هذا الأمر" if lang == "ar" else "this matter")
    greet = t["greet"].format(name=f.station.cashier_name) if f.station.cashier_name else t["greet_any"]
    body = t.get(f.kind, t["other"]).format(day=day, amount=f"{to_sar(f.amount):,.2f}", title=f.title, title_lc=f.title[:1].lower() + f.title[1:])
    return f"{greet}\n\n{body}\n\n{t['end'].format(me=me)}"


class MessageIn(BaseModel):
    lang: str = Field("en", pattern="^(en|ar)$")
    polish: bool = False


@router.post("/follow-ups/{fid}/message")
def message(fid: int, body: MessageIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A ready-to-send message to the station's cashier about this follow-up. It is written from a fixed
    template, so it always works; with the AI on, the AI rewrites it to sound natural (the facts stay the same)."""
    f = db.get(FollowUp, fid) or _missing()
    text = template_message(f, body.lang, user)
    by = "template"
    if body.polish:
        st = ai.status(db)
        if not st["ready"]:
            raise HTTPException(422, st["reason"] or "The AI is not available")
        try:
            msg = ai.chat(db, [
                {"role": "system", "content": "You rewrite short work messages from a cashier supervisor to a station cashier at a delivery "
                 "company in Saudi Arabia. Keep every fact, date and amount exactly as given. Polite, clear and firm, under 90 words. "
                 f"Write in {'Arabic' if body.lang == 'ar' else 'English'}. Reply with the message only."},
                {"role": "user", "content": text}], timeout=40)
            text, by = (msg.get("content") or "").strip() or text, "ai"
        except ai.AiProblem as e:
            raise HTTPException(422, str(e))
    phone = "".join(ch for ch in (f.station.cashier_phone or "") if ch.isdigit())
    if phone.startswith("05") and len(phone) == 10:  # a Saudi mobile, written the local way
        phone = "966" + phone[1:]
    return {"text": text, "by": by, "phone": phone, "email": f.station.cashier_email or "",
            "subject": f"{f.station.name}: {KINDS.get(f.kind, 'Follow-up')}" + (f" {f.business_date:%d %b}" if f.business_date else "")}


# ---------------------------------------------------------------- the cashiers' scorecard

def _month(text: str | None) -> tuple[date, date]:
    today = date.today()
    try:
        y, m = (int(x) for x in (text or today.strftime("%Y-%m")).split("-")[:2])
        first = date(y, m, 1)
    except ValueError:
        raise HTTPException(422, "Month must look like 2026-10")
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, min(today, date.fromordinal(nxt.toordinal() - 1))


def scorecard_rows(db: Session, first: date, last: date) -> list[dict]:
    token = current_station.set(None)
    try:
        rows = [r for r in ledger(db, date.today()) if first.isoformat() <= r["date"] <= last.isoformat() and r["to_deposit"] > 0]
    finally:
        current_station.reset(token)
    wanted = current_station.get()
    checked = dict(db.query(DayCheck.station_id, func.count(DayCheck.id))
                   .filter(DayCheck.business_date.between(first, last)).group_by(DayCheck.station_id))
    opened = dict(db.query(FollowUp.station_id, func.count(FollowUp.id)).filter(FollowUp.status == "open").group_by(FollowUp.station_id))
    raised = dict(db.query(FollowUp.station_id, func.count(FollowUp.id))
                  .filter(FollowUp.business_date.between(first, last)).group_by(FollowUp.station_id))
    out = []
    for st in db.query(Station).order_by(Station.name):
        if wanted is not None and st.id != wanted:
            continue
        mine = [r for r in rows if r["station_id"] == st.id]
        if not mine and not st.cashier_name:
            continue
        on_time = [r for r in mine if r["status"] == "deposited" and not r["late"] and not r.get("paid_later_on")]
        short = [r for r in mine if r["status"] == "short" or r.get("paid_later_on")]
        late = [r for r in mine if r["status"] == "overdue" or (r["late"] and r["status"] == "deposited")]
        card_days, card_amount = 0, 0.0
        token = current_station.set(st.id)
        try:
            for r in mine:
                _, p = pos.day_summary(db, date.fromisoformat(r["date"]))
                if p["system_total"] and p["machines_total"] and abs(p["difference"]) >= 0.01:
                    card_days += 1
                    card_amount += abs(p["difference"])
        finally:
            current_station.reset(token)
        closed = [r for r in mine if r["status"] not in ("not_due", "due_today")]  # days whose deposit could be judged
        score = round(100 * len(on_time) / len(closed)) if closed else None
        out.append({"station_id": st.id, "station": st.name, "station_code": st.code, "region": st.region,
                    "cashier_name": st.cashier_name or "", "cashier_phone": st.cashier_phone or "",
                    "days": len(mine), "cash": round(sum(r["cash_received"] for r in mine), 2),
                    "deposited": round(sum(r["deposited"] for r in mine), 2),
                    "on_time": len(on_time), "short_days": len(short), "short_amount": round(sum(r["pending"] for r in short if r["pending"] > 0), 2),
                    "late_days": len(late), "card_days": card_days, "card_amount": round(card_amount, 2),
                    "checked_days": checked.get(st.id, 0), "follow_ups": raised.get(st.id, 0), "open_follow_ups": opened.get(st.id, 0),
                    "score": score, "grade": None if score is None else "good" if score >= 95 else "watch" if score >= 80 else "poor"})
    out.sort(key=lambda r: (r["score"] is None, r["score"] if r["score"] is not None else 0))
    return out


@router.get("/scorecard")
def scorecard(month: str | None = None, db: Session = Depends(get_db)):
    first, last = _month(month)
    return {"month": first.strftime("%Y-%m"), "start": first.isoformat(), "end": last.isoformat(), "rows": scorecard_rows(db, first, last)}


# ---------------------------------------------------------------- the month-end report

@router.get("/month-report")
def month_report(month: str | None = None, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A printable month-end summary: every station's cashier and money (or one station's, with its
    days), the follow-ups raised that month, and the supervisor's checks."""
    import io
    from xml.sax.saxutils import escape

    from fastapi.responses import Response
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .config import settings

    first, last = _month(month)
    sid = current_station.get()
    st = db.get(Station, sid) if sid else None
    cards = scorecard_rows(db, first, last)
    token = current_station.set(None)
    try:
        days = [r for r in ledger(db, date.today()) if first.isoformat() <= r["date"] <= last.isoformat() and (sid is None or r["station_id"] == sid)]
    finally:
        current_station.reset(token)
    follows = (db.query(FollowUp).filter(FollowUp.created_at >= datetime.combine(first, datetime.min.time()),
                                         FollowUp.created_at <= datetime.combine(last, datetime.max.time()),
                                         *([FollowUp.station_id == sid] if sid else []))
               .order_by(FollowUp.created_at).all())
    title = f"Month-end report: {st.name if st else 'all stations'}, {first:%B %Y}"

    green, ink, soft, line, red = (colors.HexColor(c) for c in ("#0f2e22", "#16211c", "#7c8781", "#e1e6e0", "#b8402e"))
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=green, spaceAfter=3)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, textColor=ink, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=8, textColor=soft)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=9, textColor=ink)
    m = lambda v: f"{v:,.2f}"  # noqa: E731

    def table(head, rows, widths, right=(), total=None):
        rows = rows or [["Nothing recorded"] + [""] * (len(head) - 1)]
        t = Table([head] + rows + ([total] if total else []), colWidths=[w * mm for w in widths], repeatRows=1)
        style = [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), green),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        style += [("ALIGN", (c, 0), (c, -1), "RIGHT") for c in right]
        if total:
            style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 7.5), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f5f2"))]
        t.setStyle(TableStyle(style))
        return t

    story = [Paragraph(escape(title), h1),
             Paragraph(f"{first:%d %b %Y} to {last:%d %b %Y}  |  prepared by {escape(user)} on {datetime.now():%d %b %Y %H:%M}  |  all amounts in SAR", small),
             Spacer(1, 8)]
    cash = sum(r["cash_received"] for r in days)
    summary = [["Cash collected", m(cash), "Days with cash", str(len({r['date'] for r in days if r['to_deposit'] > 0}))],
               ["Paid out", m(sum(r["paid_out"] - r["returned"] for r in days)), "Follow-ups raised", str(len(follows))],
               ["To deposit", m(sum(r["to_deposit"] for r in days)), "Still open", str(sum(f.status == "open" for f in follows))],
               ["Deposited", m(sum(r["deposited"] for r in days)), "Days you checked", str(sum(c["checked_days"] for c in cards))],
               ["Not yet in the bank", m(sum(r["pending"] for r in days if r["pending"] > 0)), "", ""]]
    t = Table(summary, colWidths=[55 * mm, 40 * mm, 55 * mm, 40 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, line), ("BOX", (0, 0), (-1, -1), 0.6, line),
                           ("FONT", (0, 4), (1, 4), "Helvetica-Bold", 9), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(t)

    story.append(Paragraph("Cashiers", h2))
    story.append(table(["Station", "Cashier", "Days", "Cash", "Deposited", "On time", "Short", "Late", "Card sheet", "Checked", "Score"],
                       [[Paragraph(escape(c["station"]), cell), Paragraph(escape(c["cashier_name"] or "-"), cell), str(c["days"]), m(c["cash"]),
                         m(c["deposited"]), str(c["on_time"]), str(c["short_days"]), str(c["late_days"]), str(c["card_days"]),
                         f"{c['checked_days']}/{c['days']}", "-" if c["score"] is None else f"{c['score']}%"] for c in cards],
                       [38, 38, 12, 26, 26, 14, 13, 13, 18, 16, 15], right=range(2, 11)))

    if st:
        story.append(Paragraph("Day by day", h2))
        rows = [[f"{date.fromisoformat(r['date']):%a %d %b}", m(r["cash_received"]), m(r["paid_out"] - r["returned"]), m(r["to_deposit"]),
                 m(r["brought_forward"]), m(r["deposited"]), m(max(r["left"], 0)), r["status_text"] + (" (late)" if r["late"] else "")]
                for r in sorted(days, key=lambda r: r["date"])]
        story.append(table(["Day", "Cash", "Paid out", "Day's cash", "From before", "Deposited", "Left", "Status"], rows,
                           [24, 30, 22, 30, 24, 30, 24, 45], right=range(1, 7)))

    story.append(Paragraph("Follow-ups raised this month", h2))
    story.append(table(["Raised", "Station", "About", "Amount", "Status", "Last note"],
                       [[f"{f.created_at:%d %b}", Paragraph(escape(f.station.name), cell), Paragraph(escape(f.title), cell), m(to_sar(f.amount)),
                         "Open" if f.status == "open" else f"Closed {f.closed_at:%d %b}", Paragraph(escape(f.notes[-1].text if f.notes else "-"), cell)]
                        for f in follows], [16, 30, 52, 22, 24, 85], right=(3,)))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(soft)
        canvas.drawString(15 * mm, 9 * mm, f"CODesk  |  {title}" + ("  |  fictional demo data" if settings.seed_demo_data else ""))
        canvas.drawRightString(landscape(A4)[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                      title=title, author=user).build(story, onFirstPage=footer, onLaterPages=footer)
    audit.record(db, user, "exported", "report", None, title)
    db.commit()
    name = f"codesk-month-{first:%Y-%m}" + (f"-{st.code}" if st else "")
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
