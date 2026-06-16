"""Compute a whole session: the fair value of each active quarterly contract.

indexarb listed two contracts per index (the front month and the next one); a
trading "session" view does the same. :func:`compute_session` orchestrates the
provider interfaces -- price, rate, dividends -- over the next ``n_contracts``
quarterly settlements, so it works with live providers or test fakes alike.
"""

from __future__ import annotations

import datetime as dt

from dataclasses import replace

from .calculator import FairValueReport, compute_fair_value
from .calendar import (
    contract_code,
    days_to_expiry,
    front_settlement,
    next_quarterly_settlement,
)
from .core import DEFAULT_DAYS_PER_YEAR, implied_forward_rate, implied_rate
from .providers.base import DividendProvider, PriceProvider, RateProvider

#: Default tolerance (decimal) for the deferred-zero vs calendar-spread rate
#: cross-check in :func:`compute_with_deferred_repo`. The two are the *same*
#: financing rate measured two ways: backing it out of the deferred future
#: (which divides by the cash spot) versus the spot-free calendar spread between
#: the two futures. On consistent data they agree to a few hundredths of a
#: percent (max 0.22% across all 19 validation sessions -- the gap is just the
#: curve's slope between the two horizons). They can only diverge by *percent*
#: when the cash spot is stale/inconsistent with the futures -- exactly the case
#: that inflates the deferred-zero rate. 1.5% sits an order of magnitude above
#: the legitimate gap and well below any blow-up, so the cross-check is a robust
#: data-quality flag, not a model calibration.
DEFAULT_MAX_RATE_DIVERGENCE: float = 0.015


def _front_future_price(price_provider, expiry, price_date, *, root, fallback):
    """Price of the active front contract for ``expiry``.

    Uses the explicit contract (e.g. ``ESU26.CME``), which is correct during roll
    week -- when the continuous ``ES=F`` still tracks the *expiring* contract even
    though the front has rolled. Falls back to the continuous ``fallback`` symbol
    when the explicit contract isn't listed (e.g. backtesting a front that has
    since expired and been delisted).
    """
    try:
        return price_provider.close(f"{contract_code(expiry, root=root)}.CME", price_date)
    except Exception:  # noqa: BLE001 - any fetch failure -> continuous fallback
        return price_provider.close(fallback, price_date)


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
        else _front_future_price(price_provider, expiry, price_date or as_of,
                                 root=root, fallback=futures_symbol)
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
    max_rate_divergence: float = DEFAULT_MAX_RATE_DIVERGENCE,
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

    **Spot-robustness.** The deferred implied repo divides by the cash spot::

        r = ((deferred + dividends) / spot) ** (365 / deferred_days) - 1

    and the exponent (~3) amplifies any spot/future inconsistency: when Yahoo
    publishes a stale ``^GSPC`` against fresh futures, a false basis sends the
    rate (and the fair value) up ~2x. As a guard we also compute the same
    financing rate from the *calendar spread* between the two futures
    (:func:`~fairvalue.core.implied_forward_rate`), which never touches spot. The
    deferred-zero rate is used normally (it best matches indexarb), but when it
    diverges from the spot-free rate by more than ``max_rate_divergence`` -- only
    possible when spot is inconsistent -- we fall back to the spot-free rate.
    :attr:`~fairvalue.calculator.FairValueReport.rate_source` records which was
    used (``"deferred_implied_repo"`` or ``"calendar_spread"``).
    """
    price_date = price_date or as_of
    front_expiry = front_settlement(as_of)
    deferred_expiry = next_quarterly_settlement(front_expiry, on_or_after=False)
    front_days = days_to_expiry(as_of, front_expiry)
    deferred_days = days_to_expiry(as_of, deferred_expiry)
    index = price_provider.close(spx_symbol, price_date)

    if deferred_futures is None:
        deferred_symbol = f"{contract_code(deferred_expiry, root=root)}.CME"
        deferred_futures = price_provider.close(deferred_symbol, price_date)
    if front_futures is None:
        front_futures = _front_future_price(price_provider, front_expiry, price_date,
                                            root=root, fallback=front_futures_symbol)
    front_div = dividend_provider.dividend_points(as_of, front_expiry, index)
    deferred_div = dividend_provider.dividend_points(as_of, deferred_expiry, index)

    # Primary rate: the deferred contract's implied repo (independent of the
    # front, best indexarb match) -- but it divides by the cash spot. Cross-check
    # it against the spot-free calendar-spread rate from the two futures; if they
    # disagree by more than the curve could justify, the spot is the suspect, so
    # use the spot-free rate. See DEFAULT_MAX_RATE_DIVERGENCE.
    deferred_rate = implied_rate(
        index, deferred_futures, deferred_days, deferred_div, days_per_year=days_per_year
    )
    calendar_rate = implied_forward_rate(
        front_futures, front_div, front_days,
        deferred_futures, deferred_div, deferred_days, days_per_year=days_per_year,
    )
    if abs(deferred_rate - calendar_rate) <= max_rate_divergence:
        rate, rate_source = deferred_rate, "deferred_implied_repo"
    else:
        rate, rate_source = calendar_rate, "calendar_spread"

    report = compute_fair_value(
        as_of, index, rate, front_div, expiry=front_expiry,
        futures_price=front_futures, days_per_year=days_per_year, root=root,
    )
    return replace(report, rate_source=rate_source)
