"""Regression tests: reproduce indexarb.com's published S&P 500 fair values.

Each session is taken from indexarb.com's "Fair Value Premium Decomposition"
page (spot + fair value), with the contract interest rate interpolated from that
day's published zero-coupon yield-curve nodes and the dividend points read from
its Dividend Amounts page. Reproducing the rate interpolation here means the
only external inputs are spot, the curve nodes, and the dividend amounts.

Sources: indexarb.com on 2026-02-13, 2026-03-11, 2026-04-13, 2026-05-29.
Note: every June 2026 contract settles 06-18 (Thursday), not the 3rd Friday the
19th, because the 19th is Juneteenth -- handled by the holiday-aware calendar.
"""

import datetime as dt

import pytest

from fairvalue import compute_fair_value
from fairvalue.calendar import days_to_expiry, next_quarterly_settlement
from fairvalue.providers.base import interpolate_rate

D = dt.date

# (name, expiry, days, dividend_points, rate%, interest, fair_value, is_front_month)
SESSIONS = [
    dict(
        label="2026-02-13", as_of=D(2026, 2, 13), spot=6832.76,
        curve=[(1, 3.780349), (28, 4.206838), (124, 3.882614), (215, 3.739206)],
        contracts=[
            ("MAR", D(2026, 3, 20), 35, 10.223, 4.183197, 26.90, 16.68, True),
            ("JUN", D(2026, 6, 18), 125, 30.404, 3.881038, 89.68, 59.28, False),
        ],
    ),
    dict(
        label="2026-03-11", as_of=D(2026, 3, 11), spot=6781.48,
        curve=[(1, 3.790870), (31, 7.601384), (98, 3.828765), (189, 3.749328)],
        contracts=[
            ("MAR", D(2026, 3, 20), 9, 2.708, 4.807007, 7.86, 5.15, True),
            ("JUN", D(2026, 6, 18), 99, 22.857, 3.827892, 69.45, 46.59, False),
        ],
    ),
    dict(
        label="2026-04-13", as_of=D(2026, 4, 13), spot=6816.89,
        curve=[(1, 3.711984), (30, 4.383418), (156, 4.365854), (247, 4.143284)],
        contracts=[
            ("JUN", D(2026, 6, 18), 66, 16.002, 4.378400, 53.03, 37.03, True),
            ("SEP", D(2026, 9, 18), 158, 36.311, 4.360962, 127.13, 90.82, False),
        ],
    ),
    dict(
        label="2026-05-29", as_of=D(2026, 5, 29), spot=7563.63,
        curve=[(1, 3.743531), (31, 5.703780), (110, 3.968223), (201, 3.917712)],
        contracts=[
            ("JUN", D(2026, 6, 18), 20, 5.923, 4.985022, 20.19, 14.27, True),
            ("SEP", D(2026, 9, 18), 112, 26.206, 3.967113, 90.83, 64.63, False),
        ],
    ),
]


def _cases():
    for s in SESSIONS:
        for c in s["contracts"]:
            yield pytest.param(s, c, id=f"{s['label']}-{c[0]}")


@pytest.mark.parametrize("session,contract", list(_cases()))
def test_reproduces_published_fair_value(session, contract):
    name, expiry, days, div, ref_rate, ref_int, ref_fv, front = contract
    curve = [(t, r / 100.0) for t, r in session["curve"]]

    # 1) the interpolated contract rate matches the published 6-dp rate
    rate = interpolate_rate(curve, days)
    assert rate * 100 == pytest.approx(ref_rate, abs=1e-5)

    # 2) interest and fair value match to the cent
    rep = compute_fair_value(
        session["as_of"], session["spot"], rate, dividend_points=div,
        expiry=None if front else expiry,
    )
    assert rep.days_to_expiry == days
    assert rep.interest_component == pytest.approx(ref_int, abs=0.01)
    assert rep.fair_value_premium == pytest.approx(ref_fv, abs=0.01)

    # 3) for the front month, the holiday-aware calendar derives the expiry itself
    if front:
        assert next_quarterly_settlement(session["as_of"]) == expiry
        assert rep.expiry == expiry


def test_juneteenth_makes_june_2026_settle_on_the_18th():
    # The shared quirk across these sessions: June's 3rd Friday is Juneteenth.
    assert days_to_expiry(D(2026, 5, 29), D(2026, 6, 18)) == 20
    assert next_quarterly_settlement(D(2026, 5, 29)) == D(2026, 6, 18)
