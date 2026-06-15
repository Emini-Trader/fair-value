"""Tests for the high-level fair value calculator."""

import datetime as dt

import pytest

from fairvalue.calculator import compute_fair_value


def test_auto_selects_front_quarterly_expiry():
    r = compute_fair_value(dt.date(2024, 4, 15), index_value=5061.82, annual_rate=0.0533)
    assert r.expiry == dt.date(2024, 6, 21)
    assert r.contract == "ESM24"
    assert r.days_to_expiry == 67


def test_components_match_independent_calc():
    r = compute_fair_value(
        dt.date(2024, 4, 15),
        index_value=5061.82,
        annual_rate=0.0533,
        dividend_points=8.1,
    )
    # interest = 5061.82 * ((1.0533)**(67/365) - 1) ~= 48.48
    assert r.interest_component == pytest.approx(48.48, abs=0.1)
    assert r.dividend_component == 8.1
    assert r.fair_value_premium == pytest.approx(40.38, abs=0.1)
    assert r.fair_value_price == pytest.approx(5102.20, abs=0.2)


def test_expiry_override_changes_days_and_contract():
    r = compute_fair_value(
        dt.date(2024, 4, 15),
        index_value=5000.0,
        annual_rate=0.05,
        expiry=dt.date(2024, 9, 20),
    )
    assert r.contract == "ESU24"
    assert r.days_to_expiry == 158


def test_observed_futures_gives_basis_and_mispricing():
    r = compute_fair_value(
        dt.date(2024, 4, 15),
        index_value=5061.82,
        annual_rate=0.0533,
        dividend_points=8.1,
        futures_price=5101.00,
    )
    assert r.observed_basis == pytest.approx(5101.00 - 5061.82)
    # fair value price ~5102.2, so a 5101 future is slightly cheap
    assert r.mispricing == pytest.approx(5101.00 - r.fair_value_price)
    assert r.mispricing < 0


def test_str_is_renderable():
    r = compute_fair_value(dt.date(2024, 4, 15), 5000.0, 0.05, 7.0, futures_price=5040.0)
    text = str(r)
    assert "FAIR VALUE (premium)" in text
    assert "ESM24" in text
