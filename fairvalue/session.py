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
from .core import DEFAULT_DAYS_PER_YEAR, implied_rate
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


def compute_implied_repo(
    as_of: dt.date,
    price_provider: PriceProvider,
    dividend_provider: DividendProvider,
    *,
    futures_price: float | None = None,
    spx_symbol: str = "^GSPC",
    futures_symbol: str = "ES=F",
    expiry: dt.date | None = None,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
    root: str = "ES",
) -> FairValueReport:
    """Fair value with the financing rate backed out of the live futures price.

    Rather than *sourcing* an interest rate, this reads the rate the market has
    already priced into the front future -- the *implied repo*::

        r = ((futures + dividends) / index) ** (B / days) - 1

    The fair value price then equals the observed future by construction, so the
    fair value *premium* equals the observed basis (futures - index). Across the
    indexarb validation sessions this reproduces their published premium to
    within end-of-day timing noise -- fully autonomously, with no rate feed and
    no calibration constant -- because indexarb's financing curve tracks the
    same implied financing the futures price in.

    The flip side of the identity: this contract is "fair" against itself
    (mispricing is 0 by construction), so use a *risk-free* rate (a plain
    :class:`~fairvalue.providers.fred.FredRateProvider`) instead when you want an
    independent rich/cheap signal.

    The index and (for live use) the front future are fetched from the price
    provider; pass ``futures_price`` to pin a specific contract during roll week,
    when the continuous ``ES=F`` has already rolled to the next contract.
    """
    if expiry is None:
        expiry = next_quarterly_settlement(as_of, on_or_after=True)
    days = days_to_expiry(as_of, expiry)
    index = price_provider.close(spx_symbol, as_of)
    futures = (
        futures_price
        if futures_price is not None
        else price_provider.close(futures_symbol, as_of)
    )
    dividends = dividend_provider.dividend_points(as_of, expiry, index)
    rate = implied_rate(index, futures, days, dividends, days_per_year=days_per_year)
    return compute_fair_value(
        as_of, index, rate, dividends,
        expiry=expiry, futures_price=futures, days_per_year=days_per_year, root=root,
    )
