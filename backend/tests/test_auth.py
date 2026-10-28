"""Login: the whole API is locked until you sign in, and the account is handled safely."""
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import LoginSession, User

GOOD = "Sunshine2026x"


@pytest.fixture()
def locked_client(client):  # client creates the tables and demo data first
    settings.auth_enabled = True
    auth._fails.clear()
    with SessionLocal() as db:
        db.query(LoginSession).delete(); db.query(User).delete(); db.commit()
    with TestClient(app) as c:
        yield c
    settings.auth_enabled = False
    with SessionLocal() as db:
        db.query(LoginSession).delete(); db.query(User).delete(); db.commit()


def setup(c, name="owner", pw=GOOD):
    return c.post("/api/auth/setup", json={"username": name, "password": pw})


def test_password_hashing_is_salted_and_checked():
    a, b = auth.hash_password(GOOD), auth.hash_password(GOOD)
    assert a != b and GOOD not in a  # same password, different salt, never stored as text
    assert auth.verify_password(GOOD, a) and not auth.verify_password("wrong", a)
    assert not auth.verify_password(GOOD, "garbage")


def test_status_asks_for_first_time_setup(locked_client):
    s = locked_client.get("/api/auth/status").json()
    assert s == {"auth_enabled": True, "needs_setup": True, "user": None}


def test_api_is_locked_but_health_is_open(locked_client):
    assert locked_client.get("/api/health").status_code == 200
    for path in ("/api/drivers", "/api/audit", "/api/meta"):
        r = locked_client.get(path)
        assert r.status_code == 401 and r.json()["error"]["code"] == "not_logged_in"
    assert locked_client.post("/api/drivers", json={"code": "D-1", "name": "X Y"}).status_code == 401


def test_setup_logs_you_in_and_closes_registration(locked_client):
    r = setup(locked_client)
    assert r.status_code == 201 and "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert locked_client.get("/api/drivers").status_code == 200
    assert locked_client.get("/api/auth/status").json()["user"] == {"username": "owner"}
    assert setup(TestClient(app), "intruder").status_code == 409  # no second owner by the front door


def test_weak_passwords_and_bad_usernames_are_refused(locked_client):
    for pw in ("short1A", "alllowercase123", "NoNumbersHereAtAll"):
        assert setup(locked_client, pw=pw).status_code == 422
    assert setup(locked_client, name="a b!").status_code == 422
    assert setup(locked_client, name="ab").status_code == 422
    assert locked_client.get("/api/auth/status").json()["needs_setup"] is True


def test_login_logout_cycle(locked_client):
    setup(locked_client)
    locked_client.post("/api/auth/logout")
    assert locked_client.get("/api/drivers").status_code == 401
    bad = locked_client.post("/api/auth/login", json={"username": "owner", "password": "WrongPass123"})
    assert bad.status_code == 401 and bad.json()["error"]["message"] == "Wrong username or password"
    ghost = locked_client.post("/api/auth/login", json={"username": "nobody", "password": GOOD})
    assert ghost.json()["error"]["message"] == "Wrong username or password"  # does not reveal which part was wrong
    assert locked_client.post("/api/auth/login", json={"username": "OWNER", "password": GOOD}).status_code == 200
    assert locked_client.get("/api/drivers").status_code == 200


def test_repeated_wrong_passwords_lock_the_account_for_a_while(locked_client):
    setup(locked_client)
    locked_client.post("/api/auth/logout")
    for _ in range(auth.MAX_FAILS):
        assert locked_client.post("/api/auth/login", json={"username": "owner", "password": "nope"}).status_code == 401
    r = locked_client.post("/api/auth/login", json={"username": "owner", "password": GOOD})
    assert r.status_code == 429  # even the right password waits


def test_session_token_is_not_stored_in_the_database(locked_client):
    r = setup(locked_client)
    token = r.cookies.get(auth.COOKIE)
    with SessionLocal() as db:
        assert token and all(s.token_hash != token and len(s.token_hash) == 64 for s in db.query(LoginSession))
        row = db.query(LoginSession).first()
        row.expires_at = row.expires_at.replace(year=2000)  # expire it
        db.commit()
    assert locked_client.get("/api/drivers").status_code == 401


def test_changing_the_password_logs_out_other_devices(locked_client):
    setup(locked_client)
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "owner", "password": GOOD}).status_code == 200
    r = locked_client.post("/api/auth/password", json={"current_password": "Wrong12345678", "new_password": "NewSecret2026x"})
    assert r.status_code == 403
    assert locked_client.post("/api/auth/password", json={"current_password": GOOD, "new_password": "weak"}).status_code == 422
    assert locked_client.post("/api/auth/password", json={"current_password": GOOD, "new_password": "NewSecret2026x"}).status_code == 200
    assert locked_client.get("/api/drivers").status_code == 200  # this device stays in
    assert other.get("/api/drivers").status_code == 401  # the other one is out
    locked_client.post("/api/auth/logout")
    assert locked_client.post("/api/auth/login", json={"username": "owner", "password": GOOD}).status_code == 401
    assert locked_client.post("/api/auth/login", json={"username": "owner", "password": "NewSecret2026x"}).status_code == 200


def test_writes_from_an_unknown_website_are_refused_even_when_logged_in(locked_client):
    setup(locked_client)
    evil = {"Origin": "https://evil.example"}
    assert locked_client.post("/api/drivers", headers=evil).status_code == 403
    assert locked_client.delete("/api/drivers/999", headers=evil).status_code == 403
    ok = {"Origin": "http://localhost:5173"}
    assert locked_client.get("/api/drivers", headers=evil).status_code == 200  # reading is harmless without the cookie being readable
    assert locked_client.post("/api/drivers", headers=ok, json={"code": "D-900", "name": "Test Driver"}).status_code == 201




def test_login_can_be_turned_off(client):
    s = client.get("/api/auth/status").json()
    assert s["auth_enabled"] is False and s["needs_setup"] is False
    assert client.get("/api/drivers").status_code == 200


def test_changes_are_recorded_under_the_logged_in_name(locked_client):
    setup(locked_client, "shahwaiz")
    r = locked_client.post("/api/drivers", json={"code": "d-950", "name": "Audit Test"})
    assert r.status_code == 201 and r.json()["code"] == "D-950"
    top = locked_client.get("/api/audit").json()[0]
    assert top["username"] == "shahwaiz" and "D-950" in top["summary"]


def test_forgotten_password_can_be_reset_from_the_command_line(locked_client):
    from app.reset_password import reset
    setup(locked_client)
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            reset(db, "short")  # the same password rules as the setup page
        reset(db, "NewSunrise2026")
    assert locked_client.get("/api/drivers").status_code == 401  # old logins are ended
    assert locked_client.post("/api/auth/login", json={"username": "owner", "password": GOOD}).status_code == 401
    assert locked_client.post("/api/auth/login", json={"username": "owner", "password": "NewSunrise2026"}).status_code == 200
