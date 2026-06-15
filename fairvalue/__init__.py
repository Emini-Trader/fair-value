"""fairvalue -- S&P 500 (SPX) index vs E-mini (ES) futures fair value.

Public API::

    from fairvalue import fair_value, FairValueResult
    from fairvalue.calendar import next_quarterly_expiration, days_to_expiry

    result = fair_value(index_value=5000.0, annual_rate=0.0525,
                        days_to_expiry=90, dividend_points=12.3)
    print(result.fair_value_premium)  # the colloquial "fair value"
"""

from __future__ import annotations

from .calculator import FairValueReport, compute_fair_value
from .core import (
    DEFAULT_DAYS_PER_YEAR,
    FairValueResult,
    basis,
    dividend_points_from_cash,
    fair_value,
    implied_dividend_points,
    implied_rate,
    interest_component,
    mispricing,
)

__all__ = [
    "DEFAULT_DAYS_PER_YEAR",
    "FairValueResult",
    "FairValueReport",
    "compute_fair_value",
    "basis",
    "dividend_points_from_cash",
    "fair_value",
    "implied_dividend_points",
    "implied_rate",
    "interest_component",
    "mispricing",
]

__version__ = "0.1.0"
