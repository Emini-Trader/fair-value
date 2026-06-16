"""Tests for the whole-session computation (orchestration over fake providers)."""

import datetime as dt

import pytest

from fairvalue.core import fair_value, implied_rate
from fairvalue.session import (
    compute_implied_repo,
    compute_session,
    compute_with_deferred_repo,
)


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
    # mid-quarter (well before the JUN roll Monday 06-15)
    reports = compute_session(dt.date(2026, 5, 15), price, _Rate(), _Div())
    assert [r.contract for r in reports] == ["ESM26", "ESU26"]
    # Front = JUN settle 2026-06-18 (Juneteenth), back = SEP settle 2026-09-18
    assert reports[0].expiry == dt.date(2026, 6, 18)
    assert reports[0].days_to_expiry == 34
    assert reports[1].expiry == dt.date(2026, 9, 18)
    assert reports[1].days_to_expiry == 126
    # index fetched exactly once, reused for both contracts
    assert price.calls == 1


def test_session_resolves_inputs_per_contract():
    div = _Div()
    reports = compute_session(dt.date(2026, 5, 15), _Price(7600.0), _Rate(), div,
                              n_contracts=2)
    # dividend provider was queried once per contract with each expiry
    assert [e for e, _ in div.seen] == [dt.date(2026, 6, 18), dt.date(2026, 9, 18)]
    # the proportional fake -> different dividend points per contract
    assert reports[0].dividend_points == pytest.approx(0.10 * 34)
    assert reports[1].dividend_points == pytest.approx(0.10 * 126)


def test_session_n_contracts_one():
    reports = compute_session(dt.date(2026, 5, 15), _Price(7600.0), _Rate(), _Div(),
                              n_contracts=1)
    assert len(reports) == 1
    assert reports[0].contract == "ESM26"


def test_implied_repo_premium_equals_basis_and_is_self_fair():
    price = _SymPrice({"^GSPC": 7600.0, "ES=F": 7625.0})
    rep = compute_implied_repo(dt.date(2026, 5, 15), price, _Div())
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
    rep = compute_implied_repo(dt.date(2026, 5, 15), price, _Div(), futures_price=7625.0)
    assert rep.fair_value_price == pytest.approx(7625.0)
    assert "ES=F" not in price.seen


def test_deferred_repo_prices_front_non_circularly():
    # 2026-05-15: front = ESM26 (Jun 18, 34d), deferred = ESU26 (Sep 18, 126d)
    price = _SymPrice({"^GSPC": 7600.0, "ESM26.CME": 7625.0, "ESU26.CME": 7700.0})
    rep = compute_with_deferred_repo(dt.date(2026, 5, 15), price, _Div())
    assert rep.contract == "ESM26"                       # the FRONT is priced
    assert rep.futures_price == pytest.approx(7625.0)    # explicit front contract
    assert "ESM26.CME" in price.seen                     # front fetched explicitly
    assert "ESU26.CME" in price.seen                     # rate fetched from deferred
    # consistent spot/futures -> the deferred implied repo is used (best match)
    assert rep.rate_source == "deferred_implied_repo"
    # the rate is the deferred contract's implied repo, not the front's
    assert rep.annual_rate == pytest.approx(implied_rate(7600.0, 7700.0, 126, 0.10 * 126))
    # so the front is NOT fair against itself -> a genuine rich/cheap signal
    assert abs(rep.mispricing) > 1.0


def test_deferred_repo_falls_back_to_calendar_rate_when_spot_is_stale():
    # The reported bug: a stale cash spot inflates the deferred implied repo
    # (~4.6% -> ~8%) and doubles the fair value. 2026-06-16: front = ESU26
    # (Sep 18, 94d), deferred = ESZ26 (Dec 18, 185d). Build two MUTUALLY
    # CONSISTENT futures at 4.6% from a "true" spot, then feed a 2%-stale spot.
    true_spot, r = 7600.0, 0.046
    f_front = fair_value(true_spot, r, 94, 0.10 * 94).fair_value_price
    f_def = fair_value(true_spot, r, 185, 0.10 * 185).fair_value_price
    stale = true_spot * 0.98
    price = _SymPrice({"^GSPC": stale, "ESU26.CME": f_front, "ESZ26.CME": f_def})

    rep = compute_with_deferred_repo(dt.date(2026, 6, 16), price, _Div())

    assert rep.contract == "ESU26"
    assert rep.rate_source == "calendar_spread"            # guard tripped -> spot-free
    assert rep.annual_rate == pytest.approx(r, abs=1e-6)   # 4.6%, not the inflated ~8%
    # the naive deferred-zero rate really would have blown past the guard...
    naive = implied_rate(stale, f_def, 185, 0.10 * 185)
    assert naive - r > 0.015
    # ...and would have ~doubled the fair value; the fallback keeps it sane.
    naive_fv = fair_value(stale, naive, 94, 0.10 * 94).fair_value_premium
    assert rep.fair_value_premium < naive_fv - 20


def test_deferred_repo_max_rate_divergence_is_tunable():
    # With an infinite tolerance the guard never trips: even a stale spot keeps
    # the (blown-up) deferred implied repo. Proves the fallback is what changes
    # the result above, and that the knob is honoured.
    true_spot, r = 7600.0, 0.046
    f_front = fair_value(true_spot, r, 94, 0.10 * 94).fair_value_price
    f_def = fair_value(true_spot, r, 185, 0.10 * 185).fair_value_price
    stale = true_spot * 0.98
    price = _SymPrice({"^GSPC": stale, "ESU26.CME": f_front, "ESZ26.CME": f_def})

    rep = compute_with_deferred_repo(
        dt.date(2026, 6, 16), price, _Div(), max_rate_divergence=float("inf")
    )
    assert rep.rate_source == "deferred_implied_repo"
    assert rep.annual_rate == pytest.approx(implied_rate(stale, f_def, 185, 0.10 * 185))
