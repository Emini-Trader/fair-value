"""Tests for the whole-session computation (orchestration over fake providers)."""

import datetime as dt

import pytest

from fairvalue.session import compute_session


class _Price:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def close(self, symbol, day):
        self.calls += 1
        return self.value


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
