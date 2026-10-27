"""Database tables. All money columns are integer halalas (see money.py)."""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(d: datetime | date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat() + ("Z" if isinstance(d, datetime) else "")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginSession(Base):
    """Only a hash of the session token is stored, so a copy of the database cannot be used to log in."""
    __tablename__ = "login_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user: Mapped[User] = relationship()


class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # the driver ID used in system exports, e.g. D-104
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), default="")
    hub: Mapped[str] = mapped_column(String(60), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Collection(Base):
    """What one driver handed over at the end of one business day."""
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("business_date", "driver_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    orders: Mapped[int] = mapped_column(Integer, default=0)          # delivered COD orders
    expected_cash: Mapped[int] = mapped_column(Integer, default=0)   # cash the system says the driver collected
    cash_received: Mapped[int] = mapped_column(Integer, default=0)   # cash actually counted at the desk
    pos_amount: Mapped[int] = mapped_column(Integer, default=0)      # card payments taken on the driver's POS
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver] = relationship()


EXPENSE_CATEGORIES = ("fuel", "toll", "parking", "travel", "maintenance", "other", "advance")


class Expense(Base):
    """Money paid out of the day's cash: travel expenses, and advances given to drivers.
    Everything here reduces the cash to deposit for its business day."""
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    category: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(60), default="")  # receipt or voucher number
    note: Mapped[str] = mapped_column(String(300), default="")
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # advances only: when it was recovered
    settlement_note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver] = relationship()


class Deposit(Base):
    """A bank deposit of cash collected on one business day (a day can need more than one slip)."""
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)  # the collection day this cash belongs to
    deposit_date: Mapped[date] = mapped_column(Date)
    bank: Mapped[str] = mapped_column(String(60))
    slip_ref: Mapped[str] = mapped_column(String(60))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    """Who changed what and when. Rows are only ever added."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def _audit_is_append_only(*_):
    raise ValueError("Audit entries cannot be changed or deleted")
