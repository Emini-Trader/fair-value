"""Dividend-points providers.

The reference methodology wants the *sum of actual/forecast cash dividends*
whose ex-date falls within the contract's remaining life, normalised by the
index divisor -- a seasonal, per-name figure with no clean free feed. Two
practical options are offered:

* :class:`ManualDividendProvider` -- you supply the dividend points directly
  (or a cash sum + divisor). This is what we use to reproduce a known session
  exactly.
* :func:`estimate_dividend_points_from_yield` -- a flat dividend-yield
  approximation. It is convenient but ignores the strong seasonality of S&P 500
  ex-dividend dates, so treat it as a rough estimate, not a match.
"""

from __future__ import annotations

import datetime as dt

from ..calendar import days_to_expiry
from ..core import DEFAULT_DAYS_PER_YEAR, dividend_points_from_cash


def estimate_dividend_points_from_yield(
    index_value: float,
    annual_dividend_yield: float,
    days: float,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Rough dividend points from a flat annual yield (ignores seasonality).

        dividend_points ~ index * yield * (days / days_per_year)
    """
    if annual_dividend_yield < 0:
        raise ValueError("annual_dividend_yield must be non-negative")
    return index_value * annual_dividend_yield * (days / days_per_year)


class ManualDividendProvider:
    """Returns dividend points supplied directly (or via cash sum + divisor)."""

    def __init__(
        self,
        dividend_points: float | None = None,
        *,
        cash_dividends: float | None = None,
        index_divisor: float | None = None,
    ) -> None:
        if dividend_points is None:
            if cash_dividends is None or index_divisor is None:
                raise ValueError(
                    "provide dividend_points, or both cash_dividends and index_divisor"
                )
            dividend_points = dividend_points_from_cash(cash_dividends, index_divisor)
        self._points = dividend_points

    def dividend_points(
        self, as_of: dt.date, expiry: dt.date, index_value: float
    ) -> float:
        return self._points


class YieldDividendProvider:
    """Estimates dividend points from a flat annual dividend yield."""

    def __init__(
        self, annual_dividend_yield: float, days_per_year: float = DEFAULT_DAYS_PER_YEAR
    ) -> None:
        self._yield = annual_dividend_yield
        self._days_per_year = days_per_year

    def dividend_points(
        self, as_of: dt.date, expiry: dt.date, index_value: float
    ) -> float:
        days = days_to_expiry(as_of, expiry)
        return estimate_dividend_points_from_yield(
            index_value, self._yield, days, self._days_per_year
        )
