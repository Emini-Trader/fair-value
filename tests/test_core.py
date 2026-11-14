"""Unit tests for the fair value core mathematics."""

import math

import pytest

from fairvalue import core


def test_interest_component_independent_value():
    # Independently computed: 5000 * ((1.05) ** (90/365) - 1)
    # 90/365 = 0.2465753...; 1.05 ** that = exp(0.2465753 * ln 1.05) = 1.0121031
    # -> 5000 * 0.0121031 = 60.5154
    ic = core.interest_component(5000.0, 0.05, 90)
    assert ic == pytest.approx(60.5154, abs=0.01)


def test_interest_component_zero_days_is_zero():
    assert core.interest_component(5000.0, 0.05, 0) == 0.0


def test_dividend_points_from_cash():
    # If summed cash dividends total 70 billion and the divisor is ~8.3 billion
    assert core.dividend_points_from_cash(70e9, 8.3e9) == pytest.approx(8.4337, abs=1e-3)


def test_fair_value_premium_and_price():
    r = core.fair_value(
        index_value=5000.0, annual_rate=0.05, days_to_expiry=90, dividend_points=15.0
    )
    assert r.interest_component == pytest.approx(60.5154, abs=0.01)
    assert r.dividend_component == 15.0
    assert r.fair_value_premium == pytest.approx(45.5154, abs=0.01)
    assert r.fair_value_price == pytest.approx(5045.5154, abs=0.01)
    # premium is exactly price - index
    assert r.fair_value_price - r.index_value == pytest.approx(r.fair_value_premium)


def test_premium_can_be_negative_when_dividends_exceed_carry():
    # Low rate, high dividends -> negative fair value premium (futures < index),
    # which is normal in low-interest-rate regimes.
    r = core.fair_value(
        index_value=4000.0, annual_rate=0.005, days_to_expiry=80, dividend_points=15.0
    )
    assert r.fair_value_premium < 0
    assert r.fair_value_price < r.index_value


def test_basis_and_mispricing():
    assert core.basis(5046.0, 5000.0) == pytest.approx(46.0)
    # Futures at 5046 vs fair value price 5045.5154 -> slightly rich
    assert core.mispricing(5046.0, 5045.5154) == pytest.approx(0.4846, abs=1e-3)
    assert core.mispricing(5044.0, 5045.5154) < 0  # cheap


def test_implied_rate_round_trips():
    fv = core.fair_value(5000.0, 0.0525, 73, dividend_points=8.0)
    r = core.implied_rate(
        index_value=5000.0,
        futures_price=fv.fair_value_price,
        days_to_expiry=73,
        dividend_points=8.0,
    )
    assert r == pytest.approx(0.0525, abs=1e-9)


def test_implied_dividend_points_round_trips():
    fv = core.fair_value(5000.0, 0.0525, 73, dividend_points=8.0)
    d = core.implied_dividend_points(
        index_value=5000.0,
        futures_price=fv.fair_value_price,
        annual_rate=0.0525,
        days_to_expiry=73,
    )
    assert d == pytest.approx(8.0, abs=1e-9)


def test_implied_forward_rate_recovers_the_curve_rate():
    # Two futures generated from one spot at a single rate r must imply that r,
    # using only the two futures prices (no spot passed in).
    spot, r = 6800.0, 0.046
    near = core.fair_value(spot, r, 30, dividend_points=7.0)
    far = core.fair_value(spot, r, 120, dividend_points=28.0)
    f = core.implied_forward_rate(
        near.fair_value_price, 7.0, 30, far.fair_value_price, 28.0, 120
    )
    assert f == pytest.approx(r, abs=1e-9)


def test_implied_forward_rate_is_independent_of_spot():
    # The whole point: a stale/different cash spot must not move the rate. Build
    # the two futures from a *different* spot at the same r; the forward rate is
    # unchanged because it divides futures by futures, never by spot.
    r = 0.046
    for spot in (6800.0, 7563.63, 5000.0):
        near = core.fair_value(spot, r, 20, dividend_points=5.9)
        far = core.fair_value(spot, r, 112, dividend_points=26.2)
        f = core.implied_forward_rate(
            near.fair_value_price, 5.9, 20, far.fair_value_price, 26.2, 112
        )
        assert f == pytest.approx(r, abs=1e-9)


def test_implied_forward_rate_rejects_bad_horizons_and_legs():
    with pytest.raises(ValueError):  # far must be strictly beyond near
        core.implied_forward_rate(6800.0, 5.0, 100, 6850.0, 25.0, 100)
    with pytest.raises(ValueError):
        core.implied_forward_rate(6800.0, 5.0, 120, 6850.0, 25.0, 30)
    with pytest.raises(ValueError):  # price + dividends must be positive
        core.implied_forward_rate(-10.0, 0.0, 30, 6850.0, 25.0, 120)


def test_implied_rate_round_trips_with_a_dividend_schedule():
    # implied_rate must invert fair_value's per-dividend compounding, so backing
    # a rate out of a future and re-pricing it returns the same future.
    sched = [(10.0, 3.0), (45.0, 4.0), (90.0, 5.0)]  # (days_from_val, points)
    fv = core.fair_value(7000.0, 0.05, 110, sched)
    r = core.implied_rate(7000.0, fv.fair_value_price, 110, sched)
    assert r == pytest.approx(0.05, abs=1e-9)
    # discounting is genuinely active: compounded component exceeds the raw sum
    assert fv.dividend_component > fv.dividend_points
    assert fv.dividend_points == pytest.approx(12.0)


def test_implied_forward_rate_round_trips_with_schedules():
    spot, r = 7000.0, 0.05
    near = [(5.0, 2.0), (30.0, 3.0)]
    far = [(5.0, 2.0), (30.0, 3.0), (95.0, 4.0), (160.0, 4.0)]
    f_near = core.fair_value(spot, r, 34, near).fair_value_price
    f_far = core.fair_value(spot, r, 185, far).fair_value_price
    rr = core.implied_forward_rate(f_near, near, 34, f_far, far, 185)
    assert rr == pytest.approx(r, abs=1e-9)


def test_continuous_vs_discrete_sanity():
    # The reference equation uses annual compounding (1+r)^(d/B). For a
    # sub-year horizon (d < B) that curve is convex in time and therefore sits
    # *below* the simple-interest chord, which in turn sits below continuous
    # compounding:  discrete < simple < continuous.
    index, r, days = 5000.0, 0.05, 90
    simple = index * r * (days / 365)
    discrete = core.interest_component(index, r, days)
    continuous = index * (math.exp(r * days / 365) - 1)
    assert discrete < simple < continuous


@pytest.mark.parametrize("bad", [-1.0, -2.0])
def test_rejects_rate_at_or_below_minus_one(bad):
    with pytest.raises(ValueError):
        core.interest_component(5000.0, bad, 90)


def test_rejects_negative_days():
    with pytest.raises(ValueError):
        core.interest_component(5000.0, 0.05, -1)


def test_rejects_non_positive_divisor():
    with pytest.raises(ValueError):
        core.dividend_points_from_cash(70e9, 0.0)
