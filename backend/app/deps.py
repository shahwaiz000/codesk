from datetime import date

from fastapi import HTTPException, Request


def current_user(request: Request) -> str:
    """The logged-in username (set by the login check), or "owner" when login is turned off."""
    return getattr(request.state, "username", "") or "owner"


def parse_day(value: str | None, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise HTTPException(422, f"{field} must be a date like 2026-10-26")


def not_future(day: date, field: str = "Business date") -> date:
    if day > date.today():
        raise HTTPException(422, f"{field} cannot be in the future")
    return day
