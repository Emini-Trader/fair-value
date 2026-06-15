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
dates -- optionally scaled by a dividend-growth factor.

The two helpers here are pure and unit-tested; only the provider touches Yahoo.
"""

from __future__ import annotations

import datetime as dt

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
) -> float:
    """Estimate forward dividend points over [as_of, expiry] from seasonality.

    Sums the realised daily dividend points from the same calendar window
    ``years_back`` year(s) earlier, scaled by ``growth`` (e.g. 1.06 for +6%
    year-over-year dividend growth).
    """
    start_prev = _shift_years(as_of, years_back)
    end_prev = _shift_years(expiry, years_back)
    total = sum(v for day, v in daily_divs if start_prev <= day <= end_prev)
    return total * growth


class TotalReturnDividendProvider:
    """Seasonal forward dividend points backed by Yahoo ^GSPC / ^SP500TR."""

    def __init__(
        self,
        price_provider: YahooPriceProvider | None = None,
        *,
        years_back: int = 1,
        growth: float = 1.0,
    ) -> None:
        self._pp = price_provider or YahooPriceProvider()
        self._years_back = years_back
        self._growth = growth

    def dividend_points(
        self, as_of: dt.date, expiry: dt.date, index_value: float
    ) -> float:
        # Need trailing history covering the prior-year window [as_of-1y, expiry-1y].
        start = _shift_years(as_of, self._years_back) - dt.timedelta(days=10)
        price = self._pp.history(SPX, start, as_of)
        total = self._pp.history(SPX_TOTAL_RETURN, start, as_of)
        divs = daily_dividend_points(price, total)
        return seasonal_forward_dividends(
            divs, as_of, expiry, years_back=self._years_back, growth=self._growth
        )
