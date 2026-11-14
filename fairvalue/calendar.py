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


# --- Holiday handling -------------------------------------------------------
#
# Final settlement is normally the 3rd Friday, but when that Friday is an
# exchange holiday the settlement (SOQ) moves to the previous trading day. Two
# holidays can land on a quarterly 3rd Friday: Good Friday (March cycle) and
# Juneteenth (June cycle, a market holiday since 2022). June 19, 2026 is exactly
# this case -- it is a Friday and Juneteenth -- so the June 2026 contract settles
# Thursday June 18, giving 20 (not 21) days from May 29.


def easter_sunday(year: int) -> dt.date:
    """Gregorian Easter Sunday (Anonymous / Meeus algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def good_friday(year: int) -> dt.date:
    """Good Friday (Easter Sunday minus two days)."""
    return easter_sunday(year) - dt.timedelta(days=2)


def juneteenth_observed(year: int) -> dt.date:
    """Observed Juneteenth holiday (shifts off a weekend to the nearest weekday)."""
    day = dt.date(year, 6, 19)
    if day.weekday() == 5:  # Saturday -> observed Friday
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:  # Sunday -> observed Monday
        return day + dt.timedelta(days=1)
    return day


def is_exchange_holiday(day: dt.date) -> bool:
    """Whether US equity markets are closed for a holiday."""
    if day.weekday() >= 5:
        return False
        
    def is_observed(d: dt.date, month: int, day_of_month: int) -> bool:
        holiday = dt.date(d.year, month, day_of_month)
        if holiday.weekday() == 5:
            return d == holiday - dt.timedelta(days=1)
        elif holiday.weekday() == 6:
            return d == holiday + dt.timedelta(days=1)
        return d == holiday

    if is_observed(day, 1, 1): return True
    if is_observed(day, 7, 4): return True
    if is_observed(day, 12, 25): return True
    
    if day == good_friday(day.year): return True
    if day.year >= 2022 and day == juneteenth_observed(day.year): return True
    
    def is_nth_weekday(d: dt.date, month: int, weekday: int, n: int) -> bool:
        return d.month == month and d.weekday() == weekday and (d.day - 1) // 7 + 1 == n
    
    def is_last_weekday(d: dt.date, month: int, weekday: int) -> bool:
        return d.month == month and d.weekday() == weekday and (d + dt.timedelta(days=7)).month != month

    if is_nth_weekday(day, 1, 0, 3): return True
    if is_nth_weekday(day, 2, 0, 3): return True
    if is_last_weekday(day, 5, 0): return True
    if is_nth_weekday(day, 9, 0, 1): return True
    if is_nth_weekday(day, 11, 3, 4): return True
    
    return False


def settlement_date(year: int, month: int) -> dt.date:
    """Quarterly settlement date: the 3rd Friday, rolled back to the previous
    trading day when that Friday is an exchange holiday."""
    day = third_friday(year, month)
    while day.weekday() >= 5 or is_exchange_holiday(day):
        day -= dt.timedelta(days=1)
    return day


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


def next_quarterly_settlement(as_of: dt.date, *, on_or_after: bool = True) -> dt.date:
    """Soonest quarterly *settlement* (holiday-adjusted) on/after ``as_of``.

    Like :func:`next_quarterly_expiration` but accounts for the settlement
    rolling back off an exchange holiday, matching the dates used for fair value.
    """
    candidates = sorted(
        settlement_date(year, month)
        for year in (as_of.year, as_of.year + 1)
        for month in QUARTERLY_MONTHS
    )
    for day in candidates:
        if (day >= as_of) if on_or_after else (day > as_of):
            return day
    raise RuntimeError("no settlement found (should be unreachable)")


def days_to_expiry(as_of: dt.date, expiry: dt.date) -> int:
    """Calendar days from ``as_of`` to ``expiry`` (may be 0 on expiration day)."""
    return (expiry - as_of).days


def roll_monday(year: int, month: int) -> dt.date:
    """Monday of the week containing the quarterly 3rd Friday.

    Index arbitrageurs advance their 'front' contract to the next quarterly on
    this day: by the Monday of expiration week, ES open interest and volume have
    already rolled to the next contract, so it -- not the still-listed expiring
    contract -- is the one the fair value is quoted against.
    """
    tf = third_friday(year, month)
    return tf - dt.timedelta(days=tf.weekday())


def front_settlement(as_of: dt.date) -> dt.date:
    """Settlement of the contract treated as the active *front* on ``as_of``.

    The nearest quarterly settlement, except during expiration week: from
    :func:`roll_monday` (the Monday of the week the quarterly 3rd Friday falls
    in) the front advances to the next quarterly, matching the ES volume roll and
    indexarb's listing. Use this, not :func:`next_quarterly_settlement`, wherever
    the *active* contract is wanted.
    """
    for year in (as_of.year, as_of.year + 1, as_of.year + 2):
        for month in QUARTERLY_MONTHS:
            if as_of < roll_monday(year, month):
                return settlement_date(year, month)
    raise RuntimeError("no front settlement found (should be unreachable)")


#: Calendar quarter-ends (last day of Mar/Jun/Sep/Dec), as (month, day). These
#: are the money-market "turns" where repo funding can tighten -- quarter-end
#: balance-sheet pressure, with year-end (Dec 31) the most pronounced.
QUARTER_END_MONTH_DAY: tuple[tuple[int, int], ...] = ((3, 31), (6, 30), (9, 30), (12, 31))


def funding_turn_in_window(start: dt.date, end: dt.date) -> dict | None:
    """Most significant money-market funding turn the window ``[start, end]`` spans.

    A front contract whose remaining life spans a quarter-end -- and especially
    the year-end -- carries a small upward funding bias (turn-of-quarter repo
    tightening) that the smooth carry model does not see. This is a pure calendar
    check: no market data, no constant.

    Returns ``{"date": <turn date>, "kind": "year_end" | "quarter_end"}`` for the
    most significant turn within ``[start, end]`` (year-end ranks above a plain
    quarter-end; otherwise the earliest quarter-end), or ``None`` if the window
    spans no quarter-end.
    """
    turns = [
        dt.date(year, month, day)
        for year in range(start.year, end.year + 1)
        for month, day in QUARTER_END_MONTH_DAY
        if start <= dt.date(year, month, day) <= end
    ]
    if not turns:
        return None
    year_ends = [d for d in turns if (d.month, d.day) == (12, 31)]
    if year_ends:
        return {"date": min(year_ends), "kind": "year_end"}
    return {"date": min(turns), "kind": "quarter_end"}


# Standard CME contract month codes (used in symbols such as ESM24 = June 2024).
MONTH_CODES: dict[int, str] = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def contract_code(expiry: dt.date, root: str = "ES") -> str:
    """Return a CME-style contract symbol, e.g. ``ESM24`` for June 2024."""
    return f"{root}{MONTH_CODES[expiry.month]}{expiry.year % 100:02d}"
