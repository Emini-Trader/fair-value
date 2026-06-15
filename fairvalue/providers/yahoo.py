"""Price provider backed by the Yahoo Finance chart API.

Fetches daily closes for the cash index (``^GSPC`` for SPX) and the futures
(``ES=F``, the continuous front-month E-mini). The JSON parsing is pure and
unit-tested; the HTTP fetch takes an injectable ``opener`` for offline testing.

Network note: ``query1.finance.yahoo.com`` / ``query2.finance.yahoo.com`` must
be on the environment's network allowlist. The continuous ``ES=F`` series only
covers recent years and is back-adjusted, so for older or contract-specific
sessions supply the futures print explicitly instead.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request
from typing import Callable

#: Convenience symbols.
SPX = "^GSPC"
SPX_TOTAL_RETURN = "^SP500TR"
ES_FRONT = "ES=F"

Opener = Callable[[str, float], "object"]


def chart_url(symbol: str, start: dt.date, end: dt.date) -> str:
    """Build a Yahoo chart API URL for daily candles over [start, end]."""
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).timestamp())
    from urllib.parse import quote

    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )


def parse_chart_json(payload: dict) -> list[tuple[dt.date, float]]:
    """Parse a Yahoo chart payload into ``(date, close)`` rows (missing dropped)."""
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    rows: list[tuple[dt.date, float]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
        rows.append((day, float(close)))
    return rows


def close_on_or_before(rows: list[tuple[dt.date, float]], day: dt.date) -> float | None:
    """Return the close on ``day``, else the most recent close before it."""
    best: float | None = None
    for d, close in sorted(rows):
        if d <= day:
            best = close
        else:
            break
    return best


def _default_opener(url: str, timeout: float):
    # Yahoo rejects requests without a browser-like User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout)  # pragma: no cover - network


class YahooPriceProvider:
    """A :class:`~fairvalue.providers.base.PriceProvider` backed by Yahoo."""

    def __init__(
        self,
        *,
        opener: Opener = _default_opener,
        timeout: float = 15.0,
        lookback_days: int = 7,
    ) -> None:
        self._opener = opener
        self._timeout = timeout
        self._lookback_days = lookback_days

    def history(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, float]]:
        """Daily closes for ``symbol`` over [start, end] as ``(date, close)`` rows."""
        url = chart_url(symbol, start, end)
        with self._opener(url, self._timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return parse_chart_json(payload)

    def close(self, symbol: str, day: dt.date) -> float:
        rows = self.history(symbol, day - dt.timedelta(days=self._lookback_days), day)
        value = close_on_or_before(rows, day)
        if value is None:
            raise RuntimeError(f"no {symbol} close available on/before {day}")
        return value
