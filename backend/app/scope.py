"""Which station the person is looking at, applied to every query by itself.

The screens send the chosen station with each request (the X-Station header, or ?station= on a download
link). For that request, every query on the money tables (handovers, POS orders, machine totals, expenses,
deposits) only sees that station's rows, and every new row is saved under it. With no station chosen
("All stations"), everything is seen. Doing this in one place means no page can forget the filter.

Drivers are filtered by the pages themselves, not here, so an old handover still shows its driver after
he moves to another station."""
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from .models import Collection, Deposit, Expense, PosOrder, TerminalTotal

current_station: ContextVar[int | None] = ContextVar("current_station", default=None)
SCOPED = (Collection, Expense, Deposit, PosOrder, TerminalTotal)


def station() -> int | None:
    return current_station.get()


@event.listens_for(Session, "do_orm_execute")
def _only_this_station(state):
    sid = current_station.get()
    if sid is None or not state.is_select or state.execution_options.get("all_stations"):
        return
    state.statement = state.statement.options(*[
        with_loader_criteria(m, lambda cls: cls.station_id == sid, include_aliases=True, track_closure_variables=True)
        for m in SCOPED])


@event.listens_for(Session, "before_flush")
def _stamp_station(session, flush_context, instances):
    """A new handover, POS order, expense or machine total belongs to its driver's station; anything
    without a driver (a deposit, a machine not yet matched) to the station being looked at."""
    for obj in session.new:
        if not isinstance(obj, SCOPED) or obj.station_id is not None:
            continue
        driver = getattr(obj, "driver", None)
        if driver is None and getattr(obj, "driver_id", None):
            from .models import Driver
            driver = session.get(Driver, obj.driver_id)
        obj.station_id = (driver.station_id if driver is not None else None) or current_station.get()


def drivers(db):
    """Drivers of the station being looked at (all drivers when none is chosen)."""
    from .models import Driver
    sid = current_station.get()
    q = db.query(Driver)
    return q.filter(Driver.station_id == sid) if sid is not None else q


def named(row: dict, text: str) -> str:
    """In the all-stations view, say which station a line is about."""
    return f"{text} ({row['station']})" if current_station.get() is None and row.get("station_id") else text
