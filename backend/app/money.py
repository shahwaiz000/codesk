"""Money is stored as whole halalas (1 SAR = 100 halalas) in integer columns.

Floats cannot hold 0.10 exactly, so adding many amounts as floats drifts by fractions of a
halala. Integers never drift, and every total in the app adds up to the halala."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_JUNK = re.compile(r"(?i)sar|sr|ر\.?س|﷼|\s|,")


def to_halalas(value) -> int | None:
    """Read an amount like 1234.5, "1,234.50", "SAR 99" or "(500.00)" into halalas. None if unreadable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _JUNK.sub("", text.strip("()"))
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -cents if negative else cents


def to_sar(halalas: int | None) -> float | None:
    """For JSON: 123456 -> 1234.56."""
    return None if halalas is None else round(halalas / 100, 2)
