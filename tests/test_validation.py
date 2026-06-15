"""Regression test: reproduce indexarb.com's published fair values.

Reference: indexarb.com "Fair Value Premium Decomposition" for May-29-2026
(S&P 500), cross-checked against its Yield Curve and Dividend Amounts pages.

    Spot S&P 500 = 7563.63

    Contract  Expiry       Days  Rate %     Interest  Dividends  Fair Value
    JUN 2026  2026-06-18*    20  4.985022     20.19     5.923      14.27
    SEP 2026  2026-09-18    112  3.967113     90.83    26.206      64.63

    * 3rd Friday (June 19) is Juneteenth, so settlement rolls back to June 18.

The interest rates are interpolated from the published zero-coupon yield curve
nodes; we reproduce that interpolation here too, so the only external inputs are
the spot index, the curve, and the dividend amounts.
"""

import datetime as dt

import pytest

from fairvalue import compute_fair_value
from fairvalue.calendar import days_to_expiry, next_quarterly_settlement
from fairvalue.providers.base import interpolate_rate

AS_OF = dt.date(2026, 5, 29)
SPX = 7563.63

# Zero-coupon curve nodes (days from origin, rate %) from the Yield Curve page.
CURVE = [(d, r / 100.0) for d, r in
         [(1, 3.743531), (31, 5.703780), (110, 3.968223), (201, 3.917712)]]


def test_curve_interpolation_matches_published_contract_rates():
    assert interpolate_rate(CURVE, 20) == pytest.approx(0.04985022, abs=1e-7)
    assert interpolate_rate(CURVE, 112) == pytest.approx(0.03967113, abs=1e-7)


def test_front_month_settlement_is_juneteenth_adjusted():
    expiry = next_quarterly_settlement(AS_OF)
    assert expiry == dt.date(2026, 6, 18)
    assert days_to_expiry(AS_OF, expiry) == 20


def test_reproduces_sp500_jun_2026():
    # Front month: expiry auto-selected (exercises the holiday-adjusted calendar).
    rate = interpolate_rate(CURVE, 20)
    r = compute_fair_value(AS_OF, SPX, rate, dividend_points=5.923)
    assert r.expiry == dt.date(2026, 6, 18)
    assert r.days_to_expiry == 20
    assert r.interest_component == pytest.approx(20.19, abs=0.01)
    assert r.fair_value_premium == pytest.approx(14.27, abs=0.01)


def test_reproduces_sp500_sep_2026():
    rate = interpolate_rate(CURVE, 112)
    r = compute_fair_value(
        AS_OF, SPX, rate, dividend_points=26.206, expiry=dt.date(2026, 9, 18)
    )
    assert r.days_to_expiry == 112
    assert r.interest_component == pytest.approx(90.83, abs=0.01)
    assert r.fair_value_premium == pytest.approx(64.63, abs=0.01)
