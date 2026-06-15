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


# --- Yahoo ------------------------------------------------------------------

def _ts(d: dt.date) -> int:
    return int(dt.datetime.combine(d, dt.time(13, 30), dt.timezone.utc).timestamp())


def test_parse_chart_json_drops_missing():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [_ts(dt.date(2024, 4, 15)), _ts(dt.date(2024, 4, 16))],
                    "indicators": {"quote": [{"close": [5061.82, None]}]},
                }
            ]
        }
    }
    rows = yahoo.parse_chart_json(payload)
    assert rows == [(dt.date(2024, 4, 15), 5061.82)]


def test_close_on_or_before_picks_latest_not_after():
    rows = [
        (dt.date(2024, 4, 12), 5123.0),
        (dt.date(2024, 4, 15), 5061.82),
        (dt.date(2024, 4, 16), 5022.21),
    ]
    assert yahoo.close_on_or_before(rows, dt.date(2024, 4, 15)) == 5061.82
    # a weekend/holiday date falls back to the prior close
    assert yahoo.close_on_or_before(rows, dt.date(2024, 4, 13)) == 5123.0


def test_yahoo_price_provider_with_fake_opener():
    import json

    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [_ts(dt.date(2024, 4, 15))],
                    "indicators": {"quote": [{"close": [5061.82]}]},
                }
            ]
        }
    }

    def opener(url, timeout):
        return FakeResp(json.dumps(payload))

    provider = yahoo.YahooPriceProvider(opener=opener)
    assert provider.close(yahoo.SPX, dt.date(2024, 4, 15)) == pytest.approx(5061.82)


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
