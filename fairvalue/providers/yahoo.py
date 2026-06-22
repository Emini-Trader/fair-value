"""Price provider backed by yfinance.

Fetches daily closes for the cash index (``^GSPC`` for SPX) and the futures
(``ES=F``, the continuous front-month E-mini).
"""

from __future__ import annotations

import datetime as dt
import yfinance as yf
import pandas as pd

#: Convenience symbols.
SPX = "^GSPC"
SPX_TOTAL_RETURN = "^SP500TR"
ES_FRONT = "ES=F"


def close_on_or_before(rows: list[tuple[dt.date, float]], day: dt.date) -> float | None:
    """Return the close on ``day``, else the most recent close before it."""
    best: float | None = None
    for d, close in sorted(rows):
        if d <= day:
            best = close
        else:
            break
    return best


class YahooPriceProvider:
    """A :class:`~fairvalue.providers.base.PriceProvider` backed by Yahoo via yfinance."""

    def __init__(
        self,
        *,
        lookback_days: int = 7,
    ) -> None:
        self._lookback_days = lookback_days

    def history(
        self, symbol: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, float]]:
        """Daily closes for ``symbol`` over [start, end] as ``(date, close)`` rows."""
        end_exclusive = end + dt.timedelta(days=1)
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start.strftime("%Y-%m-%d"), end=end_exclusive.strftime("%Y-%m-%d"))
        
        rows: list[tuple[dt.date, float]] = []
        if df.empty:
            return rows
            
        for timestamp, row in df.iterrows():
            day = timestamp.date()
            close_val = row.get("Close")
            if pd.notna(close_val):
                rows.append((day, float(close_val)))
        return rows

    def close(self, symbol: str, day: dt.date) -> float:
        rows = self.history(symbol, day - dt.timedelta(days=self._lookback_days), day)
        value = close_on_or_before(rows, day)
        if value is None:
            raise RuntimeError(f"no {symbol} close available on/before {day}")
        return value
