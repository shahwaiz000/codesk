"""The AI engine CODesk talks to: the local one (Ollama, on this computer) or Google Gemini (free tier, cloud).

Both are reached the same way, through the OpenAI-style chat API that Ollama and Gemini each offer, so
the slip reader and Ask CODesk do not care which one answers.

Privacy rule, enforced here and not only written on the screen: Google may use what is sent on its free
tier to improve its models, so the cloud engine only works while CODesk runs in demo mode (the fictional
drivers and days). Real company data never goes to the cloud; with real data, the local engine is used."""
import json
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import audit
from .config import settings
from .database import get_db
from .deps import current_user
from .models import AppSetting

router = APIRouter(prefix="/api/ai", tags=["ai"])

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
ENGINES = ("local", "gemini")


class AiProblem(Exception):
    pass


def _get(db: Session, key: str, default: str = "") -> str:
    s = db.get(AppSetting, key)
    return s.value if s and s.value else default


def _put(db: Session, key: str, value: str):
    s = db.get(AppSetting, key) or AppSetting(key=key)
    s.value = value
    db.add(s)


def engine(db: Session) -> str:
    e = _get(db, "ai_engine", "local")
    return e if e in ENGINES else "local"


def status(db: Session) -> dict:
    """Which engine, and whether it can be used right now (and if not, why)."""
    e = engine(db)
    key = _get(db, "gemini_key")
    out = {"engine": e, "demo_mode": settings.seed_demo_data, "gemini_model": _get(db, "gemini_model", settings.gemini_model),
           "has_key": bool(key), "key_hint": f"...{key[-4:]}" if len(key) > 8 else "", "ack": _get(db, "gemini_ack") == "yes",
           "ready": False, "reason": ""}
    if e == "gemini":
        if not settings.seed_demo_data:
            out["reason"] = "The cloud AI only works in demo mode, so company data never leaves this computer"
        elif not key:
            out["reason"] = "Add your free Gemini API key"
        elif not out["ack"]:
            out["reason"] = "Confirm that the cloud AI is used with demo data only"
        else:
            out["ready"] = True
    else:
        out["ready"], out["reason"] = True, ""
    return out


class _Busy(Exception):
    """Google's model is busy for a moment (a 503, or a 429 that is about demand, not the daily limit)."""


def _post(url: str, headers: dict, body: dict, timeout: float, cloud: bool) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  fixed addresses: Google's API or this computer
            answer = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
            detail = detail[0] if isinstance(detail, list) and detail else detail
            why = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("error")
        except (ValueError, OSError, AttributeError):
            why = ""
        why = why or ""
        if e.code in (401, 403):
            raise AiProblem("The Gemini API key was not accepted. Check it on the Settings page")
        if e.code in (500, 502, 503, 504) or "demand" in why.lower() or "overloaded" in why.lower():
            raise _Busy(why or str(e.code))
        if e.code == 429:
            raise AiProblem("The free AI limit is reached for now. Wait a minute and try again")
        raise AiProblem(f"The AI could not answer: {why or e.code}")
    except (urllib.error.URLError, OSError):
        raise AiProblem("The AI cannot be reached. " + ("Check the internet connection" if cloud else "Start Ollama, then try again"))
    try:
        return answer["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise AiProblem("The AI's answer could not be understood. Try again")


def chat(db: Session, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False,
         local_model: str | None = None, timeout: float = 120) -> dict:
    """One chat turn. Returns the assistant message (OpenAI format, kept exactly as received so it can be
    sent back in the next turn, which Gemini needs for its thought signatures). When Google's model is busy,
    CODesk waits and tries again, then tries the lighter free model."""
    st = status(db)
    if not st["ready"]:
        raise AiProblem(st["reason"])
    cloud = st["engine"] == "gemini"
    if cloud:
        url = GEMINI_URL + "chat/completions"
        key = _get(db, "gemini_key")
        headers = {"Authorization": f"Bearer {key}", "x-goog-api-key": key}  # both forms Google accepts, old and new keys
        models = [st["gemini_model"]] + [m for m in (settings.gemini_fallback,) if m and m != st["gemini_model"]]
        waits = settings.ai_retry_waits
    else:
        url, headers = settings.ollama_url.rstrip("/") + "/v1/chat/completions", {}
        models, waits = [local_model or settings.ask_model], ()
    body: dict = {"messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    busy = ""
    for i, model in enumerate(models):
        for wait in (0, *(waits if i == 0 else ())):
            if wait:
                time.sleep(wait)
            try:
                return _post(url, headers, {**body, "model": model}, timeout, cloud)
            except _Busy as e:
                busy = str(e)
            except AiProblem:
                if i == 0:
                    raise
                break  # the lighter model is not available to this account: give the busy message below
    raise AiProblem("Google's free AI is busy right now (this is on Google's side). Wait a minute and try again"
                    + (f". ({busy})" if busy and len(busy) < 160 else ""))


def image_part(png_b64: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}}


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    raise AiProblem("The AI's answer was not in the expected form. Try again")


# ---------------------------------------------------------------- the Settings panel

class AiIn(BaseModel):
    engine: str = Field(pattern="^(local|gemini)$")
    gemini_key: str | None = Field(None, max_length=200)  # empty keeps the saved key
    gemini_model: str | None = Field(None, max_length=60)
    ack: bool = False


@router.get("")
def get_status(db: Session = Depends(get_db)):
    return status(db)


@router.put("")
def choose(body: AiIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    before = engine(db)
    _put(db, "ai_engine", body.engine)
    if body.gemini_key:
        _put(db, "gemini_key", body.gemini_key.strip())
    if body.gemini_model:
        _put(db, "gemini_model", body.gemini_model.strip())
    _put(db, "gemini_ack", "yes" if body.ack else "")
    audit.record(db, user, "updated", "settings", None,
                 f"AI engine: {before} -> {body.engine}" + (" (new Gemini key)" if body.gemini_key else ""))
    db.commit()
    return status(db)


@router.post("/test")
def test(db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        msg = chat(db, [{"role": "user", "content": "Reply with the single word: ready"}], timeout=60)
    except AiProblem as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "reply": (msg.get("content") or "").strip()[:80]}
