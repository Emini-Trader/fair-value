"""Futures expiration calendar for S&P 500 index futures (ES / SP).

CME S&P 500 futures (both the standard "SP" and the E-mini "ES") use the
*quarterly* March cycle: contracts expire in March, June, September and
December.  Final settlement is on the **third Friday** of the contract month,
determined by the Special Opening Quotation (SOQ) of the S&P 500 on that
morning.

For fair value we need, for any valuation date, the date of the relevant
contract's expiration and the number of calendar days until it.
"""

from __future__ import annotations

import datetime as dt

#: Months in the quarterly (March) expiration cycle.
QUARTERLY_MONTHS: tuple[int, ...] = (3, 6, 9, 12)

_FRIDAY = 4  # Monday=0 ... Sunday=6


def third_friday(year: int, month: int) -> dt.date:
    """Return the third Friday of ``year``/``month`` (the SOQ / expiration date)."""
    first = dt.date(year, month, 1)
    offset = (_FRIDAY - first.weekday()) % 7
    first_friday = first + dt.timedelta(days=offset)
    return first_friday + dt.timedelta(days=14)


def is_quarterly_expiration(day: dt.date) -> bool:
    """True if ``day`` is a quarterly S&P 500 futures expiration (3rd Friday)."""
    return day.month in QUARTERLY_MONTHS and day == third_friday(day.year, day.month)


def next_quarterly_expiration(as_of: dt.date, *, on_or_after: bool = True) -> dt.date:
    """Soonest quarterly expiration on/after (or strictly after) ``as_of``.

    Args:
        as_of: Valuation date.
        on_or_after: If True (default), an ``as_of`` that *is* an expiration
            returns that same date; if False, returns the following contract.
    """
    candidates = [
        third_friday(year, month)
        for year in (as_of.year, as_of.year + 1)
        for month in QUARTERLY_MONTHS
    ]
    candidates.sort()
    for day in candidates:
        if (day >= as_of) if on_or_after else (day > as_of):
            return day
    raise RuntimeError("no expiration found (should be unreachable)")


def days_to_expiry(as_of: dt.date, expiry: dt.date) -> int:
    """Calendar days from ``as_of`` to ``expiry`` (may be 0 on expiration day)."""
    return (expiry - as_of).days


# Standard CME contract month codes (used in symbols such as ESM24 = June 2024).
MONTH_CODES: dict[int, str] = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def contract_code(expiry: dt.date, root: str = "ES") -> str:
    """Return a CME-style contract symbol, e.g. ``ESM24`` for June 2024."""
    return f"{root}{MONTH_CODES[expiry.month]}{expiry.year % 100:02d}"
