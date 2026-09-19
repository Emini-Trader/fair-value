"""Tests for data providers -- pure helpers plus fetchers with a fake opener."""

import datetime as dt

import pytest

from fairvalue.providers import base, dividends, fred, yahoo


class FakeResp:
    """Minimal context-manager response standing in for urllib's."""

    def __init__(self, text: str):
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- rate interpolation -----------------------------------------------------

def test_interpolate_rate_endpoints_and_midpoint():
    pts = [(30.0, 0.050), (90.0, 0.052)]
    assert base.interpolate_rate(pts, 30) == pytest.approx(0.050)
    assert base.interpolate_rate(pts, 90) == pytest.approx(0.052)
    assert base.interpolate_rate(pts, 60) == pytest.approx(0.051)


def test_interpolate_rate_clamps_outside_range_and_unsorted():
    pts = [(90.0, 0.052), (30.0, 0.050)]  # unsorted on purpose
    assert base.interpolate_rate(pts, 5) == pytest.approx(0.050)
    assert base.interpolate_rate(pts, 400) == pytest.approx(0.052)


def test_interpolate_rate_requires_points():
    with pytest.raises(ValueError):
        base.interpolate_rate([], 60)


# --- FRED -------------------------------------------------------------------

def test_parse_fred_csv_handles_headers_and_missing():
    text = "observation_date,DGS3MO\n2024-04-10,5.40\n2024-04-11,.\n2024-04-12,5.35\n"
    rows = fred.parse_fred_csv(text)
    assert rows[0] == (dt.date(2024, 4, 10), 5.40)
    assert rows[1] == (dt.date(2024, 4, 11), None)
    assert fred.latest_value(rows) == 5.35


def test_fred_rate_provider_interpolates_from_fake_feed():
    values = {"DGS1MO": 5.40, "DGS3MO": 5.35, "DGS6MO": 5.20, "DGS1": 4.90}

    def opener(url, timeout):
        for sid, val in values.items():
            if f"id={sid}" in url:
                return FakeResp(f"observation_date,{sid}\n2024-04-12,{val}\n")
        return FakeResp("observation_date,X\n2024-04-12,.\n")

    provider = fred.FredRateProvider(opener=opener)
    # 67 days sits between the 30d (5.40%) and 91d (5.35%) knots
    rate = provider.zero_rate(dt.date(2024, 4, 15), 67)
    assert rate == pytest.approx(0.053697, abs=1e-5)


def test_fred_funding_spread_lifts_zero_rate():
    values = {"DGS1MO": 5.40, "DGS3MO": 5.35, "DGS6MO": 5.20, "DGS1": 4.90}

    def opener(url, timeout):
        for sid, val in values.items():
            if f"id={sid}" in url:
                return FakeResp(f"observation_date,{sid}\n2024-04-12,{val}\n")
        return FakeResp("observation_date,X\n2024-04-12,.\n")

    base_rate = fred.FredRateProvider(opener=opener).zero_rate(dt.date(2024, 4, 15), 67)
    # the spread is added on top of the interpolated curve, in decimal
    lifted = fred.FredRateProvider(
        opener=opener, funding_spread=0.0055
    ).zero_rate(dt.date(2024, 4, 15), 67)
    assert lifted == pytest.approx(base_rate + 0.0055, abs=1e-9)
    # the raw curve knots are unaffected by the spread
    assert lifted == pytest.approx(0.059197, abs=1e-5)


# --- Yahoo ------------------------------------------------------------------

def test_close_on_or_before_picks_latest_not_after():
    rows = [
        (dt.date(2024, 4, 12), 5123.0),
        (dt.date(2024, 4, 15), 5061.82),
        (dt.date(2024, 4, 16), 5022.21),
    ]
    assert yahoo.close_on_or_before(rows, dt.date(2024, 4, 15)) == 5061.82
    # a weekend/holiday date falls back to the prior close
    assert yahoo.close_on_or_before(rows, dt.date(2024, 4, 13)) == 5123.0


def test_yahoo_price_provider_uses_injected_history():
    rows = [(dt.date(2024, 4, 12), 5100.0), (dt.date(2024, 4, 15), 5061.82)]
    provider = yahoo.YahooPriceProvider(history_fn=lambda s, a, b: rows)
    assert provider.close(yahoo.SPX, dt.date(2024, 4, 15)) == pytest.approx(5061.82)
    # on-or-before: a non-trading day returns the latest prior close
    assert provider.close(yahoo.SPX, dt.date(2024, 4, 16)) == pytest.approx(5061.82)


def test_yahoo_close_raises_when_no_data():
    provider = yahoo.YahooPriceProvider(history_fn=lambda s, a, b: [])
    with pytest.raises(RuntimeError):
        provider.close(yahoo.SPX, dt.date(2024, 4, 15))


def test_parse_chart_json_drops_missing_closes():
    t0 = int(dt.datetime(2024, 4, 12, tzinfo=dt.timezone.utc).timestamp())
    t1 = int(dt.datetime(2024, 4, 15, tzinfo=dt.timezone.utc).timestamp())
    payload = {"chart": {"result": [{
        "timestamp": [t0, t1],
        "indicators": {"quote": [{"close": [None, 5061.82]}]},
    }]}}
    assert yahoo.parse_chart_json(payload) == [(dt.date(2024, 4, 15), pytest.approx(5061.82))]


def test_parse_chart_json_handles_error_payload():
    # Yahoo returns a 200 with no 'result' for unknown/delisted symbols.
    assert yahoo.parse_chart_json({"chart": {"result": None, "error": {"code": "x"}}}) == []


def _et_timestamp(y, m, d, hour, minute=0):
    from zoneinfo import ZoneInfo

    return int(dt.datetime(y, m, d, hour, minute, tzinfo=ZoneInfo("America/New_York")).timestamp())


def test_parse_chart_json_backfills_last_null_close_from_quote():
    # ^GSPC-style bar: still null hours after the close, but the real-time
    # quote already carries the settled print for that same session.
    bar_ts = _et_timestamp(2026, 7, 14, 9, 30)
    payload = {"chart": {"result": [{
        "timestamp": [bar_ts],
        "indicators": {"quote": [{"close": [None]}]},
        "meta": {
            "regularMarketPrice": 7543.59,
            "regularMarketTime": _et_timestamp(2026, 7, 14, 16, 56),
        },
    }]}}
    assert yahoo.parse_chart_json(payload) == [(dt.date(2026, 7, 14), pytest.approx(7543.59))]


def test_parse_chart_json_does_not_backfill_from_a_still_open_quote():
    # The quote timestamp is intraday (before the 16:00 ET close) -- not a
    # settled close yet, so the bar should stay dropped, not backfilled.
    bar_ts = _et_timestamp(2026, 7, 14, 9, 30)
    payload = {"chart": {"result": [{
        "timestamp": [bar_ts],
        "indicators": {"quote": [{"close": [None]}]},
        "meta": {
            "regularMarketPrice": 7500.0,
            "regularMarketTime": _et_timestamp(2026, 7, 14, 11, 0),
        },
    }]}}
    assert yahoo.parse_chart_json(payload) == []


def test_parse_chart_json_does_not_backfill_from_a_different_days_quote():
    bar_ts = _et_timestamp(2026, 7, 14, 9, 30)
    payload = {"chart": {"result": [{
        "timestamp": [bar_ts],
        "indicators": {"quote": [{"close": [None]}]},
        "meta": {
            "regularMarketPrice": 7500.0,
            "regularMarketTime": _et_timestamp(2026, 7, 13, 16, 56),
        },
    }]}}
    assert yahoo.parse_chart_json(payload) == []


def test_chart_url_encodes_symbol_and_window():
    url = yahoo.chart_url("^GSPC", dt.date(2024, 4, 1), dt.date(2024, 4, 15))
    assert "%5EGSPC" in url and "interval=1d" in url and "period1=" in url


def test_default_history_falls_back_to_urllib_when_yfinance_fails(monkeypatch):
    def boom(*_):
        raise RuntimeError("yfinance blocked (e.g. proxy)")
    monkeypatch.setattr(yahoo, "yfinance_history", boom)
    monkeypatch.setattr(yahoo, "urllib_history", lambda s, a, b: [(dt.date(2024, 4, 15), 1.0)])
    assert yahoo.default_history("X", dt.date(2024, 4, 1), dt.date(2024, 4, 15)) == \
        [(dt.date(2024, 4, 15), 1.0)]


def test_default_history_falls_back_when_yfinance_returns_empty(monkeypatch):
    monkeypatch.setattr(yahoo, "yfinance_history", lambda *a: [])
    monkeypatch.setattr(yahoo, "urllib_history", lambda *a: [(dt.date(2024, 4, 15), 2.0)])
    assert yahoo.default_history("X", dt.date(2024, 4, 1), dt.date(2024, 4, 15))[0][1] == 2.0


def test_default_history_freshens_a_stale_yfinance_tail_for_todays_query(monkeypatch):
    # yfinance has the same underlying lag as the raw chart endpoint: it can
    # simply omit the most recent session rather than returning it as null.
    # ``end`` here is "today" -- missing yesterday (not just today) is what
    # should trigger the top-up.
    monkeypatch.setattr(yahoo, "_et_today", lambda: dt.date(2026, 7, 15))
    monkeypatch.setattr(
        yahoo, "yfinance_history", lambda *a: [(dt.date(2026, 7, 13), 100.0)])
    monkeypatch.setattr(
        yahoo, "urllib_history",
        lambda *a: [(dt.date(2026, 7, 13), 100.0), (dt.date(2026, 7, 14), 105.0)])
    rows = yahoo.default_history("X", dt.date(2026, 7, 1), dt.date(2026, 7, 15))
    assert (dt.date(2026, 7, 14), 105.0) in rows


def test_default_history_skips_freshening_when_yfinance_covers_yesterday(monkeypatch):
    # end == today, latest == yesterday: today's own session may still be
    # open, so a day behind is already as fresh as it can be.
    monkeypatch.setattr(yahoo, "_et_today", lambda: dt.date(2026, 7, 15))
    monkeypatch.setattr(
        yahoo, "yfinance_history", lambda *a: [(dt.date(2026, 7, 14), 100.0)])

    def boom(*_):
        raise AssertionError("should not need a freshening call")

    monkeypatch.setattr(yahoo, "urllib_history", boom)
    rows = yahoo.default_history("X", dt.date(2026, 7, 1), dt.date(2026, 7, 15))
    assert rows == [(dt.date(2026, 7, 14), 100.0)]


def test_default_history_requires_an_exact_match_for_a_past_target_date(monkeypatch):
    # end is a specific COMPLETED past session (e.g. resolving one exact
    # close, as build_fairvalue does for price_date) -- the one-day tolerance
    # used for "today" queries must not apply here, or a stale prior close
    # silently gets substituted for the requested day.
    monkeypatch.setattr(yahoo, "_et_today", lambda: dt.date(2026, 7, 16))
    monkeypatch.setattr(
        yahoo, "yfinance_history", lambda *a: [(dt.date(2026, 7, 13), 100.0)])
    monkeypatch.setattr(
        yahoo, "urllib_history",
        lambda *a: [(dt.date(2026, 7, 13), 100.0), (dt.date(2026, 7, 14), 105.0)])
    rows = yahoo.default_history("X", dt.date(2026, 7, 1), dt.date(2026, 7, 14))
    assert (dt.date(2026, 7, 14), 105.0) in rows


# --- dividends --------------------------------------------------------------

def test_estimate_dividend_points_from_yield():
    pts = dividends.estimate_dividend_points_from_yield(5000.0, 0.015, 90)
    assert pts == pytest.approx(18.493, abs=1e-3)


def test_manual_dividend_provider_points_and_cash():
    assert dividends.ManualDividendProvider(8.1).dividend_points(
        dt.date(2024, 4, 15), dt.date(2024, 6, 21), 5000.0
    ) == 8.1
    from_cash = dividends.ManualDividendProvider(
        cash_dividends=70e9, index_divisor=8.3e9
    )
    assert from_cash.dividend_points(
        dt.date(2024, 4, 15), dt.date(2024, 6, 21), 5000.0
    ) == pytest.approx(8.4337, abs=1e-3)


def test_manual_dividend_provider_requires_inputs():
    with pytest.raises(ValueError):
        dividends.ManualDividendProvider()


def test_yield_dividend_provider_uses_days_to_expiry():
    provider = dividends.YieldDividendProvider(0.015)
    pts = provider.dividend_points(dt.date(2024, 4, 15), dt.date(2024, 6, 21), 5000.0)
    # 67 days: 5000 * 0.015 * 67/365
    assert pts == pytest.approx(13.767, abs=1e-3)
