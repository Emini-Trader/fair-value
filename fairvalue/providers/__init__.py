"""Data providers for fair value inputs (prices, rates, dividends).

Pure helpers (interpolation, parsing, estimates) are unit-tested directly. The
live HTTP providers (:class:`FredRateProvider`, :class:`YahooPriceProvider`)
require their hosts to be on the environment's network allowlist; each accepts
an injectable ``opener`` so the surrounding logic is testable offline.
"""

from __future__ import annotations

from .base import (
    DividendProvider,
    PriceProvider,
    RatePoint,
    RateProvider,
    interpolate_rate,
)
from .dividends import (
    ManualDividendProvider,
    YieldDividendProvider,
    estimate_dividend_points_from_yield,
)
from .fred import FredRateProvider, parse_fred_csv
from .total_return import (
    TotalReturnDividendProvider,
    daily_dividend_points,
    seasonal_forward_dividends,
)
from .yahoo import ES_FRONT, SPX, SPX_TOTAL_RETURN, YahooPriceProvider, parse_chart_json

__all__ = [
    "DividendProvider",
    "PriceProvider",
    "RateProvider",
    "RatePoint",
    "interpolate_rate",
    "FredRateProvider",
    "parse_fred_csv",
    "YahooPriceProvider",
    "parse_chart_json",
    "SPX",
    "SPX_TOTAL_RETURN",
    "ES_FRONT",
    "ManualDividendProvider",
    "YieldDividendProvider",
    "estimate_dividend_points_from_yield",
    "TotalReturnDividendProvider",
    "daily_dividend_points",
    "seasonal_forward_dividends",
]
