"""Dividend points from the total-return vs price index (autonomous, seasonal).

The S&P 500 has no free feed of forward dividend points, but it *can* be backed
out of two freely available index series:

  * ``^GSPC``    -- the price index (P), and
  * ``^SP500TR`` -- the total-return index (TR), which reinvests dividends.

On any day the dividend points that went ex equal

    D_t = P_{t-1} * ( TR_t / TR_{t-1}  -  P_t / P_{t-1} )

(total-return outperformance times the prior price level). Summing D_t over a
window gives the *realised* dividend points for that window.

Fair value needs *forward* dividends (over the contract's remaining life), so we
take the realised dividends from the same calendar window one year earlier as a
seasonal estimate -- capturing the strong seasonality of S&P 500 ex-dividend
dates -- scaled up by the year-over-year dividend growth measured from the data
itself (no hand-set constant), so the estimate keeps pace with rising payouts.

The two helpers here are pure and unit-tested; only the provider touches Yahoo.
"""

from __future__ import annotations

import datetime as dt
from typing import Union, Iterable

from .yahoo import SPX, SPX_TOTAL_RETURN, YahooPriceProvider


def daily_dividend_points(
    price_rows: list[tuple[dt.date, float]],
    tr_rows: list[tuple[dt.date, float]],
) -> list[tuple[dt.date, float]]:
    """Per-day dividend points from aligned price and total-return series.

    Args:
        price_rows: ``(date, close)`` for the price index (e.g. ^GSPC).
        tr_rows: ``(date, close)`` for the total-return index (e.g. ^SP500TR).

    Returns:
        ``(date, dividend_points)`` for each day after the first common date.
        Values on non-ex days hover around zero (data noise) and are kept signed
        so that noise cancels when summed over a window.
    """
    price = dict(price_rows)
    total = dict(tr_rows)
    common = sorted(set(price) & set(total))
    out: list[tuple[dt.date, float]] = []
    for prev, cur in zip(common, common[1:]):
        p0, p1 = price[prev], price[cur]
        t0, t1 = total[prev], total[cur]
        if p0 <= 0 or t0 <= 0:
            continue
        out.append((cur, p0 * (t1 / t0 - p1 / p0)))
    return out


def _shift_years(day: dt.date, n: int) -> dt.date:
    try:
        return day.replace(year=day.year - n)
    except ValueError:  # Feb 29 -> Feb 28
        return day.replace(year=day.year - n, day=28)


def seasonal_forward_dividends(
    daily_divs: list[tuple[dt.date, float]],
    as_of: dt.date,
    expiry: dt.date,
    *,
    years_back: int = 1,
    growth: float = 1.0,
) -> list[tuple[float, float]]:
    """Estimate forward dividend points over [as_of, expiry] from seasonality.

    Returns a list of ``(days_from_valuation, points)`` for each dividend,
    reconstructed from the realised daily dividend points from the same calendar
    window ``years_back`` year(s) earlier, scaled by ``growth``.
    """
    start_prev = _shift_years(as_of, years_back)
    end_prev = _shift_years(expiry, years_back)
    out = []
    for day, v in daily_divs:
        if start_prev <= day <= end_prev:
            # Distance from the historical valuation date
            days_from_val = float((day - start_prev).days)
            out.append((days_from_val, v * growth))
    return out


def estimate_yoy_growth(
    daily_divs: list[tuple[dt.date, float]], as_of: dt.date
) -> float:
    """Year-over-year dividend growth measured from two trailing 12-month windows.

    Returns the multiplier (e.g. 1.066 for +6.6%) by which last year's realised
    dividends should be scaled to estimate this year's. Measured from the data,
    so there is no hand-set growth constant. Falls back to 1.0 when the prior
    window has no data, and is clamped to [0.5, 2.0] to guard against feed gaps.
    """
    recent = sum(v for d, v in daily_divs if _shift_years(as_of, 1) < d <= as_of)
    prior = sum(
        v for d, v in daily_divs
        if _shift_years(as_of, 2) < d <= _shift_years(as_of, 1)
    )
    if prior <= 0:
        return 1.0
    return min(2.0, max(0.5, recent / prior))


class TotalReturnDividendProvider:
    """Seasonal forward dividend points backed by Yahoo ^GSPC / ^SP500TR.

    The estimate takes last year's realised dividends over the same calendar
    window and, by default (``growth="auto"``), scales them by the year-over-year
    growth measured from the data -- so the forward estimate keeps up with rising
    dividends without any hand-set constant. Pass a float to fix the growth
    multiplier instead (1.0 = last year's amounts unscaled).
    """

    def __init__(
        self,
        price_provider: YahooPriceProvider | None = None,
        *,
        years_back: int = 1,
        growth: float | str = "auto",
    ) -> None:
        self._pp = price_provider or YahooPriceProvider()
        self._years_back = years_back
        self._growth = growth

    def dividend_points(
        self, as_of: dt.date, expiry: dt.date, index_value: float
    ) -> Union[float, Iterable[tuple[float, float]]]:
        # Cover the prior-year window [as_of-Ny, expiry-Ny]; auto-growth needs
        # one extra trailing year to measure the year-over-year change.
        extra = 1 if self._growth == "auto" else 0
        start = _shift_years(as_of, self._years_back + extra) - dt.timedelta(days=10)
        price = self._pp.history(SPX, start, as_of)
        total = self._pp.history(SPX_TOTAL_RETURN, start, as_of)
        divs = daily_dividend_points(price, total)
        if self._growth == "auto":
            growth = estimate_yoy_growth(divs, as_of) ** self._years_back
        else:
            growth = self._growth
        return seasonal_forward_dividends(
            divs, as_of, expiry, years_back=self._years_back, growth=growth
        )
