"""Simple local login: one owner account, hashed passwords, expiring sessions.

Passwords use scrypt from the Python standard library. Session tokens are random and
only their hash is stored. The cookie is HttpOnly so page scripts cannot read it."""
import hashlib
import hmac
import re
import secrets
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from .config import settings
from .models import LoginSession, User, utcnow

COOKIE = "codesk_session"
USERNAME_OK = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
MIN_PASSWORD, MAX_PASSWORD = 10, 128
MAX_FAILS, WINDOW_SECONDS = 5, 600
_fails: dict[str, list[float]] = {}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, expected = stored.split("$")
        got = hash_password(password, bytes.fromhex(salt)).split("$")[2]
    except (ValueError, IndexError):
        return False
    return hmac.compare_digest(got, expected)


_DUMMY = hash_password("dummy-password-for-timing")


def check_password_rules(password: str) -> str | None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"Password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters"
    if password.lower() == password or not any(c.isdigit() for c in password):
        return "Password needs at least one capital letter and one number"
    return None


def check_username(name: str) -> str | None:
    return None if USERNAME_OK.match(name) else "Username must be 3 to 40 letters, numbers, dot, dash or underscore"


def locked(username: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(username.lower(), []) if now - t < WINDOW_SECONDS]
    _fails[username.lower()] = recent
    return len(recent) >= MAX_FAILS


def record_fail(username: str):
    _fails.setdefault(username.lower(), []).append(time.time())


def clear_fails(username: str):
    _fails.pop(username.lower(), None)


def login_ok(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username.ilike(username)).first()
    if not user:
        verify_password(password, _DUMMY)  # same work either way, so timing does not reveal who exists
        return None
    return user if verify_password(password, user.password_hash) else None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, user: User) -> str:
    db.query(LoginSession).filter(LoginSession.expires_at < utcnow()).delete()
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=_digest(token), user_id=user.id,
                        expires_at=utcnow() + timedelta(days=settings.session_days)))
    db.commit()
    return token


def user_for(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.query(LoginSession).filter_by(token_hash=_digest(token)).first()
    if not s or s.expires_at < utcnow():
        return None
    return s.user


def end_session(db: Session, token: str | None):
    if token:
        db.query(LoginSession).filter_by(token_hash=_digest(token)).delete()
        db.commit()


def end_other_sessions(db: Session, user: User, keep_token: str | None):
    keep = _digest(keep_token) if keep_token else ""
    db.query(LoginSession).filter(LoginSession.user_id == user.id, LoginSession.token_hash != keep).delete()
    db.commit()
