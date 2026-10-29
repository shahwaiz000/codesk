"""Ask CODesk: questions in plain English, answered from the desk's own figures.

The AI does not see the database. It is given a few tools, the same calculations the pages use, and
decides which to call (a day's figures, a period, one driver, the top drivers, the open items). CODesk
runs them and gives back the numbers; the AI writes the answer from those numbers only. Every tool call
is shown under the answer, so the person can see where each figure came from."""
import json
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import ai, audit, dashboard, deposits, pos
from .database import get_db
from .deps import current_user
from .expenses import CATEGORY_TEXT
from .models import Collection, Driver, Expense
from .money import to_sar

router = APIRouter(prefix="/api/ask", tags=["ask"])

MAX_ROUNDS = 6
MAX_DAYS = 93


def _day(v: str) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f"'{v}' is not a date (use YYYY-MM-DD)")


def _period(args: dict) -> tuple[date, date]:
    end = _day(args.get("end") or date.today().isoformat())
    start = _day(args.get("start") or (end - timedelta(days=29)).isoformat())
    if start > end:
        start, end = end, start
    return max(start, end - timedelta(days=MAX_DAYS)), end


def _driver(db: Session, text: str) -> Driver:
    t = (text or "").strip()
    d = db.query(Driver).filter(func.upper(Driver.code) == t.upper()).first()
    if d:
        return d
    found = db.query(Driver).filter(or_(Driver.name.ilike(f"%{t}%"), Driver.code.ilike(f"%{t}%"))).limit(5).all()
    if len(found) == 1:
        return found[0]
    raise ValueError(f"No single driver matches '{t}'" + (f": {', '.join(f'{x.code} {x.name}' for x in found)}" if found else ""))


# ---------------------------------------------------------------- the tools

def t_day_summary(db: Session, args: dict) -> dict:
    day = _day(args["date"])
    rows = {r["date"]: r for r in deposits.by_day(deposits.ledger(db))}
    f = dashboard.day_figures(db, day, rows)
    return {"date": day.isoformat(), "weekday": f"{day:%A}", **{k: f[k] for k in (
        "cash_received", "pos_system", "pos_terminal", "pos_difference", "pos_differences", "total_collected", "orders",
        "drivers", "expenses", "advances", "paid_out", "to_deposit", "deposited", "pending", "deposit_status_text", "due_on")}}


def t_period(db: Session, args: dict) -> dict:
    start, end = _period(args)
    cash = dict(db.query(Collection.business_date, func.sum(Collection.cash_received))
                .filter(Collection.business_date.between(start, end)).group_by(Collection.business_date))
    rows = {r["date"]: r for r in deposits.by_day(deposits.ledger(db))}
    days = []
    for d in sorted(cash):
        _, p = pos.day_summary(db, d)
        r = rows.get(d.isoformat(), {})
        days.append({"date": d.isoformat(), "cash": to_sar(int(cash[d])), "pos_system": p["system_total"],
                     "pos_machines": p["machines_total"], "pos_difference": p["difference"], "paid_out": r.get("paid_out", 0),
                     "to_deposit": r.get("to_deposit", 0), "deposited": r.get("deposited", 0), "deposit": r.get("status_text", "")})
    total = lambda k: round(sum(x[k] for x in days), 2)  # noqa: E731
    return {"start": start.isoformat(), "end": end.isoformat(), "working_days": len(days),
            "totals": {k: total(k) for k in ("cash", "pos_system", "pos_machines", "paid_out", "to_deposit", "deposited")},
            "days": days}


def t_driver(db: Session, args: dict) -> dict:
    d = _driver(db, args.get("driver", ""))
    start, end = _period(args)
    days = []
    for h in db.query(Collection).filter(Collection.driver_id == d.id, Collection.business_date.between(start, end)).order_by(Collection.business_date):
        row = next((r for r in pos.day_rows(db, h.business_date) if r["driver_id"] == d.id), None)
        days.append({"date": h.business_date.isoformat(), "orders": h.orders, "cash": to_sar(h.cash_received),
                     "cash_difference": to_sar(h.cash_received - h.expected_cash),
                     "pos_system": row["system_total"] if row else 0, "pos_terminal": row["terminal_total"] if row else None,
                     "pos_difference": row["difference"] if row else None})
    spent = [{"date": e.business_date.isoformat(), "type": CATEGORY_TEXT[e.category], "amount": to_sar(e.amount),
              "recovered": e.settled_on.isoformat() if e.settled_on else None}
             for e in db.query(Expense).filter(Expense.driver_id == d.id, Expense.business_date.between(start, end)).order_by(Expense.business_date)]
    return {"driver": d.code, "name": d.name, "hub": d.hub, "active": d.active, "start": start.isoformat(), "end": end.isoformat(),
            "days_worked": len(days), "cash_total": round(sum(x["cash"] for x in days), 2),
            "orders_total": sum(x["orders"] for x in days), "days": days, "payments": spent}


def t_top(db: Session, args: dict) -> dict:
    start, end = _period(args)
    metric, limit = args.get("metric", "cash"), max(1, min(int(args.get("limit") or 5), 20))
    score: dict[int, float] = defaultdict(float)
    if metric in ("cash", "orders"):
        col = Collection.cash_received if metric == "cash" else Collection.orders
        for did, v in db.query(Collection.driver_id, func.sum(col)).filter(Collection.business_date.between(start, end)).group_by(Collection.driver_id):
            score[did] = to_sar(int(v)) if metric == "cash" else int(v)
    elif metric == "paid_out":
        for did, v in db.query(Expense.driver_id, func.sum(Expense.amount)).filter(Expense.business_date.between(start, end)).group_by(Expense.driver_id):
            score[did] = to_sar(int(v))
    elif metric == "pos_differences":
        days = sorted({d for (d,) in db.query(Collection.business_date).filter(Collection.business_date.between(start, end)).distinct()})
        for d in days:
            for r in pos.day_rows(db, d):
                if r["status"] in ("terminal_short", "terminal_over"):
                    score[r["driver_id"]] += 1
    else:
        raise ValueError("metric must be cash, orders, paid_out or pos_differences")
    drivers = {d.id: d for d in db.query(Driver).filter(Driver.id.in_(list(score)))} if score else {}
    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {"metric": metric, "start": start.isoformat(), "end": end.isoformat(),
            "drivers": [{"driver": drivers[i].code, "name": drivers[i].name, "value": round(v, 2)} for i, v in ranked]}


def t_open_items(db: Session, args: dict) -> dict:
    board = dashboard.dashboard(date_=date.today().isoformat(), db=db)
    return {"count": board["alert_count"], "items": [{"date": a["date"], "what": a["text"], "amount": a["amount"]} for a in board["alerts"]],
            "cash_on_hand": board["cash_on_hand"]}


def t_drivers(db: Session, args: dict) -> dict:
    return {"drivers": [{"driver": d.code, "name": d.name, "hub": d.hub, "active": d.active}
                        for d in db.query(Driver).order_by(Driver.code)]}


def t_stations(db: Session, args: dict) -> dict:
    from . import stations
    from .scope import current_station
    if current_station.get() is not None:
        return {"note": "Only one station is being looked at; switch to All stations to compare stations"}
    day = _day(args.get("date") or (db.query(func.max(Collection.business_date)).scalar() or date.today()).isoformat())
    ov = stations.overview(date_=day.isoformat(), db=db)
    return {"date": ov["date"], "totals": ov["totals"], "stations": [
        {k: s[k] for k in ("code", "name", "region", "drivers", "handed_over", "cash_received", "pos_system", "paid_out",
                           "to_deposit", "deposit_status_text", "cash_on_hand", "late_days", "late_amount")} for s in ov["stations"]]}


def _fn(name, description, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}}


PERIOD = {"start": {"type": "string", "description": "first day, YYYY-MM-DD (default: 30 days before end)"},
          "end": {"type": "string", "description": "last day, YYYY-MM-DD (default: today)"}}
TOOLS = {
    "day_summary": (t_day_summary, _fn("day_summary", "Figures of one business day: cash, POS (system and machines), paid out, cash to deposit and its deposit status.",
                                       {"date": {"type": "string", "description": "YYYY-MM-DD"}}, ["date"])),
    "period": (t_period, _fn("period", "Day by day figures and totals for a period of up to 93 days.", PERIOD)),
    "driver": (t_driver, _fn("driver", "One driver's handovers, POS differences and payments in a period.",
                             {"driver": {"type": "string", "description": "driver ID or part of the name"}, **PERIOD}, ["driver"])),
    "top_drivers": (t_top, _fn("top_drivers", "Drivers ranked by cash collected, orders, money paid out to them, or number of POS differences.",
                               {"metric": {"type": "string", "enum": ["cash", "orders", "paid_out", "pos_differences"]},
                                "limit": {"type": "integer"}, **PERIOD}, ["metric"])),
    "open_items": (t_open_items, _fn("open_items", "What needs attention now: deposits overdue or short, unexplained POS differences, unusual amounts, old advances.")),
    "drivers": (t_drivers, _fn("drivers", "The list of drivers with their IDs, names and hubs.")),
    "stations": (t_stations, _fn("stations", "Every station (warehouse) side by side for one day: cash, POS, paid out, deposit status, "
                                 "cash still on hand and late deposits. Use it to compare stations or regions.",
                                 {"date": {"type": "string", "description": "YYYY-MM-DD (default: the latest business day)"}})),
}


def system_prompt(db: Session) -> str:
    latest = db.query(func.max(Collection.business_date)).scalar()
    return (f"You are Ask CODesk, the assistant of a delivery company's cash-on-delivery finance desk in Saudi Arabia. "
            f"Today is {date.today():%A %d %B %Y}. The latest business day with data is {latest.isoformat() if latest else 'none'}. "
            "The company has stations (warehouses) in many Saudi cities; each deposits its own cash. "
            "Friday is the weekly day off; each day's cash goes to the bank on the next working day; amounts are in SAR. "
            "Answer ONLY from the results of your tools: call them to get every figure, never guess or invent a number. "
            "If the tools cannot answer, say so. Keep answers short and clear, with amounts written like 1,234.50 SAR, "
            "and use a short list when there are several items.")


def run(db: Session, question: str) -> dict:
    messages = [{"role": "system", "content": system_prompt(db)}, {"role": "user", "content": question}]
    used = []
    for _ in range(MAX_ROUNDS):
        msg = ai.chat(db, messages, tools=[t[1] for t in TOOLS.values()])
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"answer": (msg.get("content") or "").strip() or "The AI gave no answer. Try asking in another way.", "used": used}
        messages.append(msg)  # exactly as received: Gemini needs its thought signatures back
        for c in calls:
            name = c.get("function", {}).get("name", "")
            raw = c.get("function", {}).get("arguments") or "{}"
            args: dict = {}
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                if name not in TOOLS:
                    raise ValueError(f"unknown tool {name}")
                result = TOOLS[name][0](db, args)
            except (ValueError, KeyError, TypeError) as e:
                result = {"error": str(e)}
            used.append({"tool": name, "args": args})
            messages.append({"role": "tool", "tool_call_id": c.get("id", name), "name": name,
                             "content": json.dumps(result, default=str)})
    return {"answer": "The question needed too many steps. Try asking something narrower.", "used": used}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("")
def ask(body: AskIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        out = run(db, " ".join(body.question.split()))
    except ai.AiProblem as e:
        raise HTTPException(422, str(e))
    audit.record(db, user, "asked", "ai", None, f"Ask CODesk ({ai.engine(db)}): {body.question[:200]}")
    db.commit()
    return out
