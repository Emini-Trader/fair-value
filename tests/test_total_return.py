"""Tests for the total-return-derived seasonal dividend logic (offline)."""

import datetime as dt

import pytest

from fairvalue.providers import total_return as tr
from fairvalue.providers.yahoo import SPX, SPX_TOTAL_RETURN

# A 5-day series with a single 0.5-point dividend going ex on 2025-07-02 (the
# day the price drops 102 -> 101 while the total-return index holds up).
DATES = [dt.date(2025, 6, 29), dt.date(2025, 6, 30), dt.date(2025, 7, 1),
         dt.date(2025, 7, 2), dt.date(2025, 7, 3)]
PRICE = [100.0, 101.0, 102.0, 101.0, 103.0]
# TR: 200 -> 202 -> 204 -> 203 (=204*101.5/102, the 0.5 dividend) -> 203*103/101
TR = [200.0, 202.0, 204.0, 203.0, 203.0 * 103.0 / 101.0]

PRICE_ROWS = list(zip(DATES, PRICE))
TR_ROWS = list(zip(DATES, TR))


def test_daily_dividend_points_recovers_the_dividend():
    divs = dict(tr.daily_dividend_points(PRICE_ROWS, TR_ROWS))
    assert divs[dt.date(2025, 7, 2)] == pytest.approx(0.5, abs=1e-9)
    # non-ex days are ~0
    assert divs[dt.date(2025, 7, 1)] == pytest.approx(0.0, abs=1e-9)
    assert divs[dt.date(2025, 7, 3)] == pytest.approx(0.0, abs=1e-9)


def test_seasonal_forward_window_includes_prior_year_dividend():
    divs = tr.daily_dividend_points(PRICE_ROWS, TR_ROWS)
    # Forward window 2026-06-15..2026-09-18 maps to 2025-06-15..2025-09-18,
    # which contains the 2025-07-01 dividend.
    pts = tr.seasonal_forward_dividends(
        divs, dt.date(2026, 6, 15), dt.date(2026, 9, 18), years_back=1
    )
    assert pts == pytest.approx(0.5, abs=1e-9)


def test_seasonal_growth_scaling():
    divs = tr.daily_dividend_points(PRICE_ROWS, TR_ROWS)
    pts = tr.seasonal_forward_dividends(
        divs, dt.date(2026, 6, 15), dt.date(2026, 9, 18), years_back=1, growth=1.06
    )
    assert pts == pytest.approx(0.53, abs=1e-9)


def test_seasonal_window_excludes_out_of_range_dividend():
    divs = tr.daily_dividend_points(PRICE_ROWS, TR_ROWS)
    # August-only window doesn't include the July dividend.
    pts = tr.seasonal_forward_dividends(
        divs, dt.date(2026, 8, 1), dt.date(2026, 9, 18), years_back=1
    )
    assert pts == pytest.approx(0.0, abs=1e-9)


class _FakePriceProvider:
    def __init__(self, price_rows, tr_rows):
        self._price = price_rows
        self._tr = tr_rows

    def history(self, symbol, start, end):
        return self._price if symbol == SPX else self._tr


def test_provider_wires_fetch_to_seasonal_estimate():
    provider = tr.TotalReturnDividendProvider(
        _FakePriceProvider(PRICE_ROWS, TR_ROWS), years_back=1
    )
    pts = provider.dividend_points(dt.date(2026, 6, 15), dt.date(2026, 9, 18), 7600.0)
    assert pts == pytest.approx(0.5, abs=1e-9)


def test_estimate_yoy_growth_measures_two_trailing_windows():
    divs = [(dt.date(2024, 7, 2), 0.50), (dt.date(2025, 7, 2), 0.55)]
    # recent (2025-06..2026-06]=0.55, prior (2024-06..2025-06]=0.50 -> +10%
    assert tr.estimate_yoy_growth(divs, dt.date(2026, 6, 15)) == pytest.approx(1.10)


def test_estimate_yoy_growth_falls_back_without_prior_year():
    divs = [(dt.date(2025, 7, 2), 0.55)]
    assert tr.estimate_yoy_growth(divs, dt.date(2026, 6, 15)) == 1.0


def test_auto_growth_scales_seasonal_estimate():
    d = dt.date
    dates = [d(2024, 7, 1), d(2024, 7, 2), d(2025, 7, 1), d(2025, 7, 2), d(2026, 6, 15)]
    price_rows = [(x, 100.0) for x in dates]
    # price flat at 100; TR jumps +0.5% (div 0.50) then +0.55% (div 0.55)
    tr_vals = [200.0, 201.0, 201.0, 201.0 * 1.0055, 201.0 * 1.0055]
    tr_rows = list(zip(dates, tr_vals))
    fake = _FakePriceProvider(price_rows, tr_rows)
    args = (d(2026, 6, 15), d(2026, 9, 18), 7600.0)
    fixed = tr.TotalReturnDividendProvider(fake, growth=1.0).dividend_points(*args)
    auto = tr.TotalReturnDividendProvider(fake, growth="auto").dividend_points(*args)
    assert fixed == pytest.approx(0.55, abs=1e-9)
    assert auto == pytest.approx(0.605, abs=1e-9)  # 0.55 * 1.10 measured growth


def test_symbols_distinct():
    assert SPX == "^GSPC"
    assert SPX_TOTAL_RETURN == "^SP500TR"
