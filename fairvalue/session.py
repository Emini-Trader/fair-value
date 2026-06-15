"""Compute a whole session: the fair value of each active quarterly contract.

indexarb listed two contracts per index (the front month and the next one); a
trading "session" view does the same. :func:`compute_session` orchestrates the
provider interfaces -- price, rate, dividends -- over the next ``n_contracts``
quarterly settlements, so it works with live providers or test fakes alike.
"""

from __future__ import annotations

import datetime as dt

from .calculator import FairValueReport, compute_fair_value
from .calendar import days_to_expiry, next_quarterly_settlement
from .core import DEFAULT_DAYS_PER_YEAR
from .providers.base import DividendProvider, PriceProvider, RateProvider


def compute_session(
    as_of: dt.date,
    price_provider: PriceProvider,
    rate_provider: RateProvider,
    dividend_provider: DividendProvider,
    *,
    n_contracts: int = 2,
    spx_symbol: str = "^GSPC",
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
    root: str = "ES",
) -> list[FairValueReport]:
    """Fair value for each of the next ``n_contracts`` quarterly contracts.

    The index level is fetched once; the rate and dividend points are resolved
    per contract for its exact horizon and remaining life.
    """
    index = price_provider.close(spx_symbol, as_of)
    reports: list[FairValueReport] = []
    expiry = next_quarterly_settlement(as_of, on_or_after=True)
    for _ in range(n_contracts):
        days = days_to_expiry(as_of, expiry)
        rate = rate_provider.zero_rate(as_of, days)
        dividends = dividend_provider.dividend_points(as_of, expiry, index)
        reports.append(
            compute_fair_value(
                as_of, index, rate, dividends,
                expiry=expiry, days_per_year=days_per_year, root=root,
            )
        )
        expiry = next_quarterly_settlement(expiry, on_or_after=False)
    return reports
