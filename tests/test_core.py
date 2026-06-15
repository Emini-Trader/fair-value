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
