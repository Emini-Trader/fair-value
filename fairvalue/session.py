"""Compute a whole session: the fair value of each active quarterly contract.

indexarb listed two contracts per index (the front month and the next one); a
trading "session" view does the same. :func:`compute_session` orchestrates the
provider interfaces -- price, rate, dividends -- over the next ``n_contracts``
quarterly settlements, so it works with live providers or test fakes alike.
"""

from __future__ import annotations

import datetime as dt

from .calculator import FairValueReport, compute_fair_value
from .calendar import (
    contract_code,
    days_to_expiry,
    front_settlement,
    next_quarterly_settlement,
)
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
    expiry = front_settlement(as_of)
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
    price_date: dt.date | None = None,
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
    ``price_date`` sources the spot/future from a different date than ``as_of``
    (the horizon) -- e.g. indexarb's overnight convention prices off the prior
    session's close; days and dividends still run from ``as_of``.
    """
    if expiry is None:
        expiry = front_settlement(as_of)
    days = days_to_expiry(as_of, expiry)
    index = price_provider.close(spx_symbol, price_date or as_of)
    futures = (
        futures_price
        if futures_price is not None
        else price_provider.close(futures_symbol, price_date or as_of)
    )
    dividends = dividend_provider.dividend_points(as_of, expiry, index)
    rate = implied_rate(index, futures, days, dividends, days_per_year=days_per_year)
    return compute_fair_value(
        as_of, index, rate, dividends,
        expiry=expiry, futures_price=futures, days_per_year=days_per_year, root=root,
    )


def compute_with_deferred_repo(
    as_of: dt.date,
    price_provider: PriceProvider,
    dividend_provider: DividendProvider,
    *,
    front_futures: float | None = None,
    deferred_futures: float | None = None,
    spx_symbol: str = "^GSPC",
    front_futures_symbol: str = "ES=F",
    price_date: dt.date | None = None,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
    root: str = "ES",
) -> FairValueReport:
    """Front fair value priced with the funding rate of the *next* contract.

    Backs the financing rate out of the deferred (next-quarter) future -- which
    is *independent of the front* -- and prices the front contract with it. So,
    unlike front :func:`compute_implied_repo`, the front fair value is **not**
    pinned to the front future: the basis vs fair value is a genuine rich/cheap
    signal (non-circular).

    The deferred future carries the same market funding rate indexarb's curve
    uses (within ~0.5% across the validation sessions, vs ~1.3% light for a
    risk-free rate), at the cost of not seeing the front's own ~1-month curve
    hump. The deferred contract's Yahoo symbol (e.g. ``ESU26.CME``) is built from
    its expiry; pass ``deferred_futures`` / ``front_futures`` to override either
    print (e.g. during roll week, when ``ES=F`` has rolled to the next contract).
    ``price_date`` sources every price from a different date than ``as_of`` (the
    horizon) -- e.g. indexarb prices its session-D fair value off the D-1 close.
    """
    price_date = price_date or as_of
    front_expiry = front_settlement(as_of)
    deferred_expiry = next_quarterly_settlement(front_expiry, on_or_after=False)
    index = price_provider.close(spx_symbol, price_date)

    # Rate: implied repo of the deferred contract (does not depend on the front).
    if deferred_futures is None:
        deferred_symbol = f"{contract_code(deferred_expiry, root=root)}.CME"
        deferred_futures = price_provider.close(deferred_symbol, price_date)
    deferred_days = days_to_expiry(as_of, deferred_expiry)
    deferred_div = dividend_provider.dividend_points(as_of, deferred_expiry, index)
    rate = implied_rate(
        index, deferred_futures, deferred_days, deferred_div, days_per_year=days_per_year
    )

    # Price the FRONT with that rate; its own future is only the basis reference.
    front_div = dividend_provider.dividend_points(as_of, front_expiry, index)
    if front_futures is None:
        front_futures = price_provider.close(front_futures_symbol, price_date)
    return compute_fair_value(
        as_of, index, rate, front_div, expiry=front_expiry,
        futures_price=front_futures, days_per_year=days_per_year, root=root,
    )
