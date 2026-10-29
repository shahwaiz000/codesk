"""The morning summary: one page on the last business day, ready to send to the manager.

What came in (cash and POS), what went out, where the cash stands on its way to the bank, and what needs
attention today. It is shown on the Reports page as text to copy into WhatsApp or an email, and as a
one-page PDF. If a time is set on the Reports page, CODesk prepares both by itself every working morning
(Friday is the day off) and saves them in a "Morning summaries" folder next to the watch folder."""
import io
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit, dashboard, deposits, pos
from .config import settings
from .database import get_db
from .deps import current_user, parse_day
from .models import AppSetting, Collection, Expense
from .seed import next_working_day

router = APIRouter(prefix="/api/morning", tags=["morning"])

WHO = "morning summary"


def _m(v) -> str:
    return f"{v:,.2f}"


def build(db: Session, today: date) -> dict:
    """The summary as it should read on the morning of `today`."""
    day = dashboard.previous_day_with_data(db, today)
    if day is None:
        return {"today": today.isoformat(), "day": None, "lines": [], "attention": [], "due": [],
                "text": f"CODesk morning summary, {today:%a %d %b %Y}\nNothing recorded yet."}
    board = dashboard.dashboard(date_=day.isoformat(), db=db)
    f = board["figures"]
    _, p = pos.day_summary(db, day)
    payments = db.query(Expense).filter_by(business_date=day).count()
    drivers = db.query(Collection).filter_by(business_date=day).count()

    lines = [("Cash collected", f"{_m(f['cash_received'])} SAR", f"{drivers} drivers, {f['orders']} orders")]
    if f["cash_short"] or f["cash_over"]:
        lines.append(("Cash difference", _m(f["cash_received"] - f["expected_cash"]),
                      f"{f['short_count']} short, {f['over_count']} over"))
    if p["order_count"] or p["machines_total"]:
        lines.append(("POS", f"{_m(p['machines_total'])} SAR", f"system {_m(p['system_total'])}, difference {p['difference']:+,.2f}"))
    lines.append(("Total collected", f"{_m(f['total_collected'])} SAR", ""))
    lines.append(("Paid out", f"{_m(f['paid_out'])} SAR", f"{payments} payments" if payments else "nothing paid out"))
    if f["deposit_status"] == "deposited":
        deposit = f"deposited {_m(f['deposited'])}"
    elif f["deposited"]:
        deposit = f"deposited {_m(f['deposited'])}, {_m(f['pending'])} still to deposit ({f['deposit_status_text'].lower()})"
    else:
        due = date.fromisoformat(f["due_on"]) if f["due_on"] else next_working_day(day)
        when = "today" if due == today else f"{due:%a %d %b}"
        deposit = f"overdue, was due {when}" if f["deposit_status"] == "overdue" else f"due {when}"
    lines.append(("To the bank", f"{_m(f['to_deposit'])} SAR", deposit))

    attention = [a["text"] + (f" ({date.fromisoformat(a['date']):%d %b}" + (f", {_m(a['amount'])})" if a["amount"] else ")"))
                 for a in board["alerts"][:8]]
    if p.get("unpaired"):
        attention.insert(0, f"{p['unpaired']} POS machine(s) not matched to a driver yet")
    due = [f"{date.fromisoformat(r['date']):%a %d %b}: {_m(r['pending'])} SAR ({r['status_text'].lower()})"
           for r in deposits.ledger(db, today) if r["status"] in ("due_today", "overdue", "short") and r["pending"] > 0]

    text = [f"CODesk morning summary, {today:%a %d %b %Y}", f"For {day:%A %d %b %Y}", ""]
    text += [f"{label}: {value}" + (f" ({note})" if note else "") for label, value, note in lines]
    if due:
        text += ["", "To the bank today:"] + [f"- {d}" for d in due]
    text += ["", "Needs attention:"] + ([f"- {a}" for a in attention] if attention else ["- Nothing. All clear."])
    return {"today": today.isoformat(), "day": day.isoformat(),
            "lines": [{"label": a, "value": b, "note": c} for a, b, c in lines],
            "attention": attention, "due": due, "text": "\n".join(text)}


def build_pdf(s: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    green, ink, soft = colors.HexColor("#0f2e22"), colors.HexColor("#16211c"), colors.HexColor("#4a5650")
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=green)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=ink, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=9, textColor=soft)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=ink)
    today = date.fromisoformat(s["today"])
    story = [Paragraph("Morning summary", h1),
             Paragraph(f"{today:%A %d %b %Y}" + (f"  |  for {date.fromisoformat(s['day']):%A %d %b %Y}" if s["day"] else ""), small),
             Spacer(1, 6 * mm)]
    if s["lines"]:
        t = Table([[x["label"], x["value"], Paragraph(escape(x["note"]), small)] for x in s["lines"]],
                  colWidths=[42 * mm, 42 * mm, 90 * mm])
        t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica", 10), ("FONT", (1, 0), (1, -1), "Helvetica-Bold", 10),
                               ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e1e6e0")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(t)
    if s["due"]:
        story.append(Paragraph("To the bank today", h2))
        story += [Paragraph("- " + escape(d), body) for d in s["due"]]
    story.append(Paragraph("Needs attention", h2))
    story += [Paragraph("- " + escape(a), body) for a in s["attention"]] or [Paragraph("Nothing. All clear.", body)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title="CODesk morning summary").build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- prepared by itself every morning

def _setting(db: Session, key: str) -> str:
    s = db.get(AppSetting, key)
    return s.value if s else ""


def _set(db: Session, key: str, value: str):
    s = db.get(AppSetting, key) or AppSetting(key=key)
    s.value = value
    db.add(s)


def out_folder(db: Session) -> Path:
    watch = _setting(db, "watch_folder")
    return (Path(watch) if watch else Path(settings.data_dir)) / "Morning summaries"


def maybe_run(db: Session, now: datetime | None = None) -> Path | None:
    """Called every few seconds by the watcher: prepare today's summary once, at the chosen time."""
    now = now or datetime.now()
    when = _setting(db, "morning_time")
    today = now.date()
    if not when or today.weekday() == 4 or _setting(db, "morning_last") == today.isoformat():
        return None
    if now.strftime("%H:%M") < when:
        return None
    s = build(db, today)
    folder = out_folder(db)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"Morning summary {today.isoformat()}"
    (folder / f"{name}.pdf").write_bytes(build_pdf(s))
    (folder / f"{name}.txt").write_text(s["text"], encoding="utf-8")
    _set(db, "morning_last", today.isoformat())
    audit.record(db, WHO, "prepared", "summary", None, f"Morning summary for {s['day'] or 'no data'} saved in {folder}")
    db.commit()
    return folder


# ---------------------------------------------------------------- the Reports page

class MorningIn(BaseModel):
    time: str = Field("", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")


def _today(value: str | None) -> date:
    return parse_day(value) if value else date.today()


@router.get("")
def summary(date_: str | None = Query(None, alias="date"), db: Session = Depends(get_db)):
    s = build(db, _today(date_))
    return {**s, "time": _setting(db, "morning_time"), "folder": str(out_folder(db)), "last": _setting(db, "morning_last") or None}


@router.get("/pdf")
def summary_pdf(date_: str | None = Query(None, alias="date"), db: Session = Depends(get_db)):
    today = _today(date_)
    return Response(build_pdf(build(db, today)), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="CODesk morning summary {today.isoformat()}.pdf"'})


@router.put("/settings")
def set_time(body: MorningIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    before = _setting(db, "morning_time") or "off"
    _set(db, "morning_time", body.time)
    audit.record(db, user, "updated", "settings", None, f"Morning summary time: {before} -> {body.time or 'off'}")
    db.commit()
    return {"time": body.time}


@router.post("/prepare")
def prepare_now(db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Prepare today's files now (the same files the morning job makes)."""
    s = build(db, date.today())
    folder = out_folder(db)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = f"Morning summary {date.today().isoformat()}"
        (folder / f"{name}.pdf").write_bytes(build_pdf(s))
        (folder / f"{name}.txt").write_text(s["text"], encoding="utf-8")
    except OSError:
        raise HTTPException(422, f"CODesk could not save in {folder}")
    audit.record(db, user, "prepared", "summary", None, f"Morning summary for {s['day'] or 'no data'} saved in {folder}")
    db.commit()
    return {"folder": str(folder)}
