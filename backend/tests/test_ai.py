"""The AI engine choice, Ask CODesk and the cloud slip reader (the AI itself is replaced by a stand-in)."""
import json

import pytest

from app import ai, ask, slip_reader
from app.config import settings
from app.database import SessionLocal
from tests.conftest import END


@pytest.fixture()
def cloud(client, monkeypatch):
    """The cloud engine switched on, in demo mode."""
    monkeypatch.setattr(settings, "seed_demo_data", True)
    client.put("/api/ai", json={"engine": "gemini", "gemini_key": "test-key-123456", "ack": True})
    yield
    client.put("/api/ai", json={"engine": "local"})


def test_the_cloud_engine_is_refused_with_real_data(client, monkeypatch):
    monkeypatch.setattr(settings, "seed_demo_data", False)  # real data
    s = client.put("/api/ai", json={"engine": "gemini", "gemini_key": "test-key-123456", "ack": True}).json()
    assert s["engine"] == "gemini" and not s["ready"] and "demo mode" in s["reason"]
    assert s["key_hint"] == "...3456" and "test-key" not in json.dumps(s)  # the key itself is never sent back
    with SessionLocal() as db, pytest.raises(ai.AiProblem, match="demo mode"):
        ai.chat(db, [{"role": "user", "content": "hi"}])
    monkeypatch.setattr(settings, "seed_demo_data", True)
    assert not client.put("/api/ai", json={"engine": "gemini", "ack": False}).json()["ready"]  # must confirm demo data only
    assert client.put("/api/ai", json={"engine": "gemini", "ack": True}).json()["ready"]       # the saved key is kept
    client.put("/api/ai", json={"engine": "local"})


def test_ask_codesk_answers_from_the_tools(client, cloud, monkeypatch):
    calls = []

    def fake_chat(db, messages, tools=None, json_mode=False, local_model=None, timeout=120):
        calls.append(messages)
        if len(calls) == 1:
            assert {t["function"]["name"] for t in tools} >= {"day_summary", "period", "driver", "top_drivers", "open_items"}
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "day_summary", "arguments": json.dumps({"date": END.isoformat()})},
                 "extra_content": {"google": {"thought_signature": "sig"}}},
                {"id": "c2", "type": "function", "function": {"name": "top_drivers", "arguments": json.dumps({"metric": "cash", "limit": 3})}}]}
        tool_results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        assert messages[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig"  # sent back as received
        return {"role": "assistant", "content": f"Cash collected: {tool_results[0]['cash_received']:,.2f} SAR. Top: {tool_results[1]['drivers'][0]['driver']}"}

    monkeypatch.setattr(ai, "chat", fake_chat)
    r = client.post("/api/ask", json={"question": "How much cash did we collect on the last day, and who brought the most?"}).json()
    assert r["answer"].startswith("Cash collected:") and [u["tool"] for u in r["used"]] == ["day_summary", "top_drivers"]
    assert len(calls) == 2


def test_the_tools_give_real_figures(client):
    with SessionLocal() as db:
        day = ask.t_day_summary(db, {"date": END.isoformat()})
        assert day["cash_received"] > 0 and day["weekday"]
        period = ask.t_period(db, {"start": "2026-10-01", "end": END.isoformat()})
        assert period["working_days"] > 10 and period["totals"]["cash"] > day["cash_received"]
        one = ask.t_driver(db, {"driver": "Faisal", "start": "2026-10-01", "end": END.isoformat()})
        assert one["driver"] == "D-101" and one["days_worked"] > 0
        assert len(ask.t_top(db, {"metric": "pos_differences", "start": "2026-09-01", "end": END.isoformat()})["drivers"]) >= 1
        with pytest.raises(ValueError):
            ask.t_driver(db, {"driver": "nobody at all"})


def test_a_bad_tool_call_is_answered_with_an_error_not_a_crash(client, cloud, monkeypatch):
    replies = iter([{"role": "assistant", "tool_calls": [{"id": "x", "function": {"name": "driver", "arguments": "{\"driver\": \"zzz\"}"}}]},
                    {"role": "assistant", "content": "I could not find that driver."}])
    monkeypatch.setattr(ai, "chat", lambda *a, **k: next(replies))
    r = client.post("/api/ask", json={"question": "How is driver zzz doing?"}).json()
    assert r["answer"] == "I could not find that driver."


def test_the_slip_reader_uses_the_cloud_engine(client, cloud, monkeypatch):
    sent = {}

    def fake_chat(db, messages, tools=None, json_mode=False, local_model=None, timeout=120):
        sent["parts"] = [p["type"] for p in messages[0]["content"]]
        return {"role": "assistant", "content": "```json\n" + json.dumps({"bank": "Coastal National Bank", "date": "02-Jun-2026",
                "slip_number": "CN-1", "total": 100, "amount_in_words": "one hundred", "denominations": [{"note": 100, "count": 1, "amount": 100}]}) + "\n```"}
    monkeypatch.setattr(ai, "chat", fake_chat)
    from tests.test_slips import _png
    r = client.post("/api/slips/read", files={"file": ("s.png", _png(), "image/png")}).json()
    assert r["status"] == "draft" and r["total"] == 100 and sent["parts"] == ["text", "image_url"]
    assert client.get("/api/slips/ai").json()["engine"] == "gemini"


def test_a_demo_slip_is_made_only_in_demo_mode(client, monkeypatch):
    assert client.get("/api/slips/demo-slip").status_code == 404
    monkeypatch.setattr(settings, "seed_demo_data", True)
    r = client.get("/api/slips/demo-slip")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert slip_reader.number_to_words(36810) == "thirty six thousand eight hundred ten"
    assert slip_reader.words_to_number(slip_reader.number_to_words(7925)) == 7925


def test_a_busy_google_is_tried_again_then_the_lighter_model(client, cloud, monkeypatch):
    import io
    import urllib.error
    monkeypatch.setattr(settings, "ai_retry_waits", (0, 0))
    tried = []

    def fake_post(url, headers, body, timeout, cloud_):
        tried.append(body["model"])
        if body["model"] == settings.gemini_fallback:
            return {"role": "assistant", "content": "ready"}
        raise ai._Busy("This model is currently experiencing high demand")
    monkeypatch.setattr(ai, "_post", fake_post)
    with SessionLocal() as db:
        assert ai.chat(db, [{"role": "user", "content": "hi"}])["content"] == "ready"
    assert tried == [ai.status(SessionLocal())["gemini_model"]] * 3 + [settings.gemini_fallback]

    def always_busy(url, headers, body, timeout, cloud_):
        if body["model"] == settings.gemini_fallback:
            raise ai.AiProblem("model not found")
        raise ai._Busy("high demand")
    monkeypatch.setattr(ai, "_post", always_busy)
    with SessionLocal() as db, pytest.raises(ai.AiProblem, match="busy right now"):
        ai.chat(db, [{"role": "user", "content": "hi"}])


def test_a_slow_answer_counts_as_busy(monkeypatch):
    import socket
    import urllib.request
    def slow(*a, **k):
        raise socket.timeout("timed out")
    monkeypatch.setattr(urllib.request, "urlopen", slow)
    with pytest.raises(ai._Busy):
        ai._post("http://x", {}, {}, 1, True)
    def offline(*a, **k):
        import urllib.error
        raise urllib.error.URLError("getaddrinfo failed")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(ai.AiProblem, match="getaddrinfo failed"):
        ai._post("http://x", {}, {}, 1, True)
