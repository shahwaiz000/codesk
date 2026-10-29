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


class Station(Base):
    """A warehouse or station: its own drivers, its own cash desk and its own bank deposits."""
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)   # e.g. JED or the system's Site Code
    name: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(60), default="")
    region: Mapped[str] = mapped_column(String(60), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # the driver ID used in system exports, e.g. D-104
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), default="")
    hub: Mapped[str] = mapped_column(String(60), default="")
    pos_terminal: Mapped[str] = mapped_column(String(30), default="")  # the terminal ID of the driver's POS machine
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)
    station: Mapped["Station | None"] = relationship()


class Collection(Base):
    """What one driver handed over at the end of one business day."""
    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("business_date", "driver_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)  # whose desk
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    orders: Mapped[int] = mapped_column(Integer, default=0)          # delivered COD orders
    expected_cash: Mapped[int] = mapped_column(Integer, default=0)   # cash the system says the driver collected
    cash_received: Mapped[int] = mapped_column(Integer, default=0)   # cash actually counted at the desk
    pos_amount: Mapped[int] = mapped_column(Integer, default=0)      # the day's total on the driver's POS terminal
    pos_terminal: Mapped[str] = mapped_column(String(30), default="")  # terminal used that day (machines can move)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver] = relationship()


EXPENSE_CATEGORIES = ("expense", "salary", "incentive", "settlement", "fuel", "toll", "parking", "travel", "maintenance", "other", "advance")


class Expense(Base):
    """Money paid out of the day's cash: travel expenses, and advances given to drivers.
    Everything here reduces the cash to deposit for its business day."""
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)  # whose desk
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    category: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(60), default="")  # receipt or voucher number
    note: Mapped[str] = mapped_column(String(300), default="")
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # advances only: when it was recovered
    settlement_method: Mapped[str] = mapped_column(String(10), default="")  # salary | cash (cash comes back into that day's deposit)
    settlement_note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver] = relationship()


class Deposit(Base):
    """A bank deposit of cash collected on one business day (a day can need more than one slip)."""
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)  # whose desk
    business_date: Mapped[date] = mapped_column(Date, index=True)  # the collection day this cash belongs to
    deposit_date: Mapped[date] = mapped_column(Date)
    bank: Mapped[str] = mapped_column(String(60))
    slip_ref: Mapped[str] = mapped_column(String(60))
    amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PosOrder(Base):
    """An order the delivery system shows as closed by POS (card) payment."""
    __tablename__ = "pos_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)  # whose desk
    order_no: Mapped[str] = mapped_column(String(40), unique=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    amount: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver] = relationship()


class AppSetting(Base):
    """How this desk works, chosen on the Settings page."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class UnusualReview(Base):
    """An unusual amount someone looked at and found fine, so it stops being pointed out."""
    __tablename__ = "unusual_reviews"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)  # e.g. expense:123
    note: Mapped[str] = mapped_column(String(300), default="")
    decided_by: Mapped[str] = mapped_column(String(40), default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SlipScan(Base):
    """A deposit slip read by the local AI, waiting for a person to record it (or put it aside)."""
    __tablename__ = "slip_scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    filename: Mapped[str] = mapped_column(String(260))
    status: Mapped[str] = mapped_column(String(10))  # draft | failed | recorded | dismissed
    fields: Mapped[str] = mapped_column(Text, default="")   # what the AI read, as JSON
    checks: Mapped[str] = mapped_column(Text, default="")   # CODesk's checks of it, as JSON
    error: Mapped[str] = mapped_column(String(300), default="")
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deposit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    deposit_id: Mapped[int | None] = mapped_column(ForeignKey("deposits.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(40), default="")


class ImportedFile(Base):
    """A file the watch folder picked up, and what came of it."""
    __tablename__ = "imported_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    filename: Mapped[str] = mapped_column(String(260))
    kind: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(10))  # done | attention | failed
    summary: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)


class TerminalTotal(Base):
    """One POS machine's total for one day, from the terminal sheet. Machines move between drivers,
    so the driver is found each day: by the machine's known owner, by an exact amount match with a
    driver's system POS orders, or chosen by hand."""
    __tablename__ = "terminal_totals"
    __table_args__ = (UniqueConstraint("business_date", "terminal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)  # whose desk
    business_date: Mapped[date] = mapped_column(Date, index=True)
    terminal: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(Integer)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    paired_by: Mapped[str] = mapped_column(String(10), default="")  # terminal | amount | hand, empty when not paired
    created_by: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    driver: Mapped[Driver | None] = relationship()


class PosReview(Base):
    """A person's decision on one driver's POS difference for one day. The totals at the time of the
    decision are kept, so a review that no longer matches the numbers shows as out of date."""
    __tablename__ = "pos_reviews"
    __table_args__ = (UniqueConstraint("business_date", "driver_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    status: Mapped[str] = mapped_column(String(20))  # explained | follow_up
    note: Mapped[str] = mapped_column(String(300), default="")
    system_total: Mapped[int] = mapped_column(Integer)
    terminal_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(40), default="")
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
