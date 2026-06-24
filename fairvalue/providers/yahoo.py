"""Price provider backed by Yahoo Finance.

Daily closes for the cash index (``^GSPC``), the total-return index
(``^SP500TR``) and the futures (``ES=F`` and explicit contracts).

Two fetch paths are tried in order, so each covers the other's failure mode:

* **yfinance** (optional -- ``pip install fairvalue[yahoo]``) handles Yahoo's
  cookie/crumb churn; the robust primary on an open network (e.g. CI).
* **urllib** (standard library) hits the Yahoo chart API directly. It honours
  ``HTTPS_PROXY`` and the system CA bundle, so it works behind a proxy where
  yfinance's ``curl_cffi`` transport is blocked. Always available, no dependency.

The JSON parsing and date selection are pure and unit-tested; the provider takes
an injectable ``history_fn`` so its logic stays testable offline.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import quote

#: Convenience symbols.
SPX = "^GSPC"
SPX_TOTAL_RETURN = "^SP500TR"
ES_FRONT = "ES=F"

#: ``history_fn`` signature: (symbol, start, end) -> [(date, close), ...].
HistoryFn = Callable[[str, dt.date, dt.date], "list[tuple[dt.date, float]]"]

_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def chart_url(symbol: str, start: dt.date, end: dt.date) -> str:
    """Build a Yahoo chart API URL for daily candles over [start, end]."""
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).timestamp())
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
        f"?period1={p1}&period2={p2}&interval=1d"
    )


def parse_chart_json(payload: dict) -> list[tuple[dt.date, float]]:
    """Parse a Yahoo chart payload into ``(date, close)`` rows (missing dropped)."""
    result_list = payload.get("chart", {}).get("result")
    if not result_list:  # Yahoo error payload (e.g. unknown/delisted symbol)
        return []
    result = result_list[0]
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


def yfinance_history(symbol: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """Fetch daily closes via yfinance. Raises ImportError if it isn't installed."""
    import yfinance as yf  # lazy: keeps yfinance optional and out of import time

    end_exclusive = end + dt.timedelta(days=1)
    df = yf.Ticker(symbol).history(
        start=start.strftime("%Y-%m-%d"), end=end_exclusive.strftime("%Y-%m-%d")
    )
    rows: list[tuple[dt.date, float]] = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        if close is not None and close == close:  # drop NaN without importing pandas
            rows.append((ts.date(), float(close)))
    return rows


def _open(url: str, *, timeout: float, cookie: str | None = None):  # pragma: no cover - network
    headers = {"User-Agent": _BROWSER_UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _yahoo_cookie(timeout: float) -> str | None:  # pragma: no cover - network
    """A Yahoo session cookie (``fc.yahoo.com`` sets one even on a 404)."""
    try:
        with _open("https://fc.yahoo.com/", timeout=timeout) as resp:
            raw = resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as exc:
        raw = exc.headers.get("Set-Cookie")
    except Exception:  # noqa: BLE001 - cookie is best-effort
        return None
    return raw.split(";", 1)[0] if raw else None


def urllib_history(
    symbol: str, start: dt.date, end: dt.date, *, timeout: float = 15.0, retries: int = 3
) -> list[tuple[dt.date, float]]:
    """Fetch daily closes from the Yahoo chart API with stdlib urllib.

    Browser User-Agent; on a 401/403 (cookie/crumb gate) it grabs a Yahoo cookie
    and retries; on 429/transient errors it backs off. Proxy-friendly.
    """
    url = chart_url(symbol, start, end)
    cookie: str | None = None
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with _open(url, timeout=timeout, cookie=cookie) as resp:
                return parse_chart_json(json.loads(resp.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network
            last = exc
            if exc.code == 404:
                return []  # no data for this symbol/window (e.g. a delisted contract)
            if exc.code in (401, 403) and cookie is None:
                cookie = _yahoo_cookie(timeout)
                if cookie:
                    continue
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as exc:  # pragma: no cover - network
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    if last:  # pragma: no cover - defensive
        raise last
    raise RuntimeError(f"failed to fetch {symbol} from Yahoo")  # pragma: no cover


def default_history(symbol: str, start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """yfinance if available and non-empty, else the stdlib urllib chart fallback."""
    try:
        rows = yfinance_history(symbol, start, end)
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - missing/blocked yfinance -> urllib fallback
        pass
    return urllib_history(symbol, start, end)


class YahooPriceProvider:
    """A :class:`~fairvalue.providers.base.PriceProvider` backed by Yahoo.

    ``history_fn`` selects the fetch strategy (default: yfinance, then urllib);
    inject a fake for offline tests.
    """

    def __init__(
        self,
        *,
        history_fn: HistoryFn = default_history,
        lookback_days: int = 7,
    ) -> None:
        self._history_fn = history_fn
        self._lookback_days = lookback_days

    def history(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, float]]:
        """Daily closes for ``symbol`` over [start, end] as ``(date, close)`` rows."""
        return self._history_fn(symbol, start, end)

    def close(self, symbol: str, day: dt.date) -> float:
        rows = self.history(symbol, day - dt.timedelta(days=self._lookback_days), day)
        value = close_on_or_before(rows, day)
        if value is None:
            raise RuntimeError(f"no {symbol} close available on/before {day}")
        return value
