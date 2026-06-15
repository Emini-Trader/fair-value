"""Interest-rate provider backed by FRED (Federal Reserve Economic Data).

Uses the free ``fredgraph.csv`` endpoint (no API key) to read U.S. Treasury
constant-maturity yields, then interpolates to the exact number of days
remaining in the futures contract -- the practical, free modern proxy for the
zero-coupon financing curve referenced in the fair value methodology.

T-bill yields are risk-free and sit *below* the financing rate indexarb uses;
this provider gives the clean risk-free rate. To source the funding rate
instead, back it out of the live future with
:func:`fairvalue.compute_implied_repo` (no constant needed). An optional manual
``funding_spread`` (off by default) is available for callers who want to add a
known spread.

Network note: ``fred.stlouisfed.org`` must be on the environment's network
allowlist. The CSV parsing and rate interpolation are pure and unit-tested; the
HTTP fetch takes an injectable ``opener`` so it can be tested without a network.
"""

from __future__ import annotations

import datetime as dt
import urllib.request
from typing import Callable

from .base import RatePoint, interpolate_rate

#: FRED constant-maturity Treasury series -> approximate tenor in days.
FRED_TENORS: dict[str, float] = {
    "DGS1MO": 30.0,
    "DGS3MO": 91.0,
    "DGS6MO": 182.0,
    "DGS1": 365.0,
}

#: Optional financing spread (decimal) added on top of the risk-free T-bill
#: curve. FRED ``DGS*`` are risk-free Treasury yields, which sit below the rate
#: at which an arbitrage desk actually finances the basket. This knob is **off
#: by default** (0.0): a single constant cannot track the funding premium, which
#: varies 0.5-1.3% by date/tenor. To source the funding rate *without* a
#: constant, use :func:`fairvalue.compute_implied_repo`, which backs the rate out
#: of the live future itself. ``funding_spread`` remains available for callers
#: who want to apply a known manual spread.
DEFAULT_FUNDING_SPREAD: float = 0.0

Opener = Callable[[str, float], "object"]


def fred_csv_url(series_id: str, start: dt.date, end: dt.date) -> str:
    """Build the keyless fredgraph CSV download URL for a series and window."""
    return (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={start:%Y-%m-%d}&coed={end:%Y-%m-%d}"
    )


def parse_fred_csv(text: str) -> list[tuple[dt.date, float | None]]:
    """Parse fredgraph CSV text into ``(date, value | None)`` rows.

    FRED encodes missing observations (weekends, holidays) as a single ``.``.
    The header row is ``observation_date,<SERIES_ID>`` (older exports use
    ``DATE``); both are skipped.
    """
    rows: list[tuple[dt.date, float | None]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        date_str, _, value_str = line.partition(",")
        if date_str.lower() in ("date", "observation_date"):
            continue
        try:
            day = dt.date.fromisoformat(date_str)
        except ValueError:
            continue  # header or malformed line
        value_str = value_str.strip()
        value = None if value_str in ("", ".") else float(value_str)
        rows.append((day, value))
    return rows


def latest_value(rows: list[tuple[dt.date, float | None]]) -> float | None:
    """Return the most recent non-missing value from parsed FRED rows."""
    for _, value in reversed(rows):
        if value is not None:
            return value
    return None


def _default_opener(url: str, timeout: float):
    return urllib.request.urlopen(url, timeout=timeout)  # pragma: no cover - network


class FredRateProvider:
    """A :class:`~fairvalue.providers.base.RateProvider` backed by FRED."""

    def __init__(
        self,
        tenors: dict[str, float] | None = None,
        *,
        opener: Opener = _default_opener,
        timeout: float = 15.0,
        lookback_days: int = 10,
        funding_spread: float = 0.0,
    ) -> None:
        self.tenors = tenors or dict(FRED_TENORS)
        self._opener = opener
        self._timeout = timeout
        self._lookback_days = lookback_days
        self.funding_spread = funding_spread

    def _fetch_latest(self, series_id: str, as_of: dt.date) -> float | None:
        start = as_of - dt.timedelta(days=self._lookback_days)
        url = fred_csv_url(series_id, start, as_of)
        with self._opener(url, self._timeout) as resp:
            text = resp.read().decode("utf-8")
        return latest_value(parse_fred_csv(text))

    def curve(self, as_of: dt.date) -> list[RatePoint]:
        """Fetch the available tenor knots as ``(days, rate_decimal)`` points."""
        points: list[RatePoint] = []
        for series_id, tenor_days in self.tenors.items():
            value = self._fetch_latest(series_id, as_of)
            if value is not None:
                points.append((tenor_days, value / 100.0))  # percent -> decimal
        if not points:
            raise RuntimeError(f"FRED returned no usable rates as of {as_of}")
        return points

    def zero_rate(self, as_of: dt.date, days: float) -> float:
        """Interpolated annualised rate (decimal) for ``days`` as of ``as_of``.

        Adds :attr:`funding_spread` to convert the risk-free T-bill curve into
        an approximate financing rate (see :data:`DEFAULT_FUNDING_SPREAD`).
        """
        return interpolate_rate(self.curve(as_of), days) + self.funding_spread
