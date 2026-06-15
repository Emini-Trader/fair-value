"""Tests for the whole-session computation (orchestration over fake providers)."""

import datetime as dt

import pytest

from fairvalue.core import fair_value
from fairvalue.session import compute_implied_repo, compute_session


class _Price:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def close(self, symbol, day):
        self.calls += 1
        return self.value


class _SymPrice:
    """Returns a different close per symbol (e.g. cash vs future)."""

    def __init__(self, prices):
        self.prices = prices
        self.seen = []

    def close(self, symbol, day):
        self.seen.append(symbol)
        return self.prices[symbol]


class _Rate:
    def zero_rate(self, as_of, days):
        return 0.05


class _Div:
    def __init__(self):
        self.seen = []

    def dividend_points(self, as_of, expiry, index_value):
        self.seen.append((expiry, days := (expiry - as_of).days))
        return 0.10 * days  # proportional, just to vary by contract


def test_session_returns_front_and_next_quarter():
    price = _Price(7600.0)
    reports = compute_session(dt.date(2026, 6, 15), price, _Rate(), _Div())
    assert [r.contract for r in reports] == ["ESM26", "ESU26"]
    # Front = JUN settle 2026-06-18 (Juneteenth), back = SEP settle 2026-09-18
    assert reports[0].expiry == dt.date(2026, 6, 18)
    assert reports[0].days_to_expiry == 3
    assert reports[1].expiry == dt.date(2026, 9, 18)
    assert reports[1].days_to_expiry == 95
    # index fetched exactly once, reused for both contracts
    assert price.calls == 1


def test_session_resolves_inputs_per_contract():
    div = _Div()
    reports = compute_session(dt.date(2026, 6, 15), _Price(7600.0), _Rate(), div,
                              n_contracts=2)
    # dividend provider was queried once per contract with each expiry
    assert [e for e, _ in div.seen] == [dt.date(2026, 6, 18), dt.date(2026, 9, 18)]
    # the proportional fake -> different dividend points per contract
    assert reports[0].dividend_points == pytest.approx(0.10 * 3)
    assert reports[1].dividend_points == pytest.approx(0.10 * 95)


def test_session_n_contracts_one():
    reports = compute_session(dt.date(2026, 6, 15), _Price(7600.0), _Rate(), _Div(),
                              n_contracts=1)
    assert len(reports) == 1
    assert reports[0].contract == "ESM26"


def test_implied_repo_premium_equals_basis_and_is_self_fair():
    price = _SymPrice({"^GSPC": 7600.0, "ES=F": 7625.0})
    rep = compute_implied_repo(dt.date(2026, 6, 15), price, _Div())
    # fair value price equals the future by construction; premium is the basis
    assert rep.fair_value_price == pytest.approx(7625.0)
    assert rep.fair_value_premium == pytest.approx(25.0)
    assert rep.mispricing == pytest.approx(0.0, abs=1e-9)
    # the backed-out rate, fed forward, round-trips to the same future
    fv = fair_value(7600.0, rep.annual_rate, rep.days_to_expiry, rep.dividend_points)
    assert fv.fair_value_price == pytest.approx(7625.0)


def test_implied_repo_honours_explicit_futures_price():
    # ES=F would be 9999, but an explicit --futures must win and skip the fetch
    price = _SymPrice({"^GSPC": 7600.0, "ES=F": 9999.0})
    rep = compute_implied_repo(dt.date(2026, 6, 15), price, _Div(), futures_price=7625.0)
    assert rep.fair_value_price == pytest.approx(7625.0)
    assert "ES=F" not in price.seen
