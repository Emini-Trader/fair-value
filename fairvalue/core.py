"""Core fair value mathematics for stock index futures.

This implements the standard *cost of carry* fair value model used to relate a
cash index (e.g. the S&P 500 / SPX) to its futures contract (e.g. the CME
E-mini / ES):

    interest_component = Index * ((1 + r) ** (days / B) - 1)
    dividend_component = dividend_points
    fair_value_premium = interest_component - dividend_component
    fair_value_price   = Index + fair_value_premium

where

    Index            current index level (e.g. the SPX close)
    r                annualised interest rate (decimal, e.g. 0.0525) that
                     corresponds to the exact number of days remaining in the
                     futures contract (interpolated off a yield curve)
    days             calendar days from the valuation date to futures
                     settlement / expiration
    B                day-count basis -- days per year (365 by the convention
                     shown in the reference equation)
    dividend_points  the sum of dividends whose ex-dividend date falls within
                     the remaining life of the contract, expressed in index
                     points.  Per the reference equation this equals
                         sum_of_cash_dividends / index_divisor

Terminology note (see README): colloquially, *fair value* means the
**premium** (futures - index), not the full futures price.  Both the premium
and the full price are returned so there is no ambiguity.

The functions here are pure (no I/O, no third-party dependencies) so they are
trivial to unit-test and reuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Union

#: Day-count basis implied by the reference equation (ACT/365 fixed).
DEFAULT_DAYS_PER_YEAR: float = 365.0


def interest_component(
    index_value: float,
    annual_rate: float,
    days_to_expiry: float,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Cost-of-carry (interest) component, in index points.

        Index * ((1 + r) ** (days / B) - 1)

    Args:
        index_value: Current index level (e.g. SPX). Must be >= 0.
        annual_rate: Annualised interest rate as a decimal (0.05 == 5%).
        days_to_expiry: Calendar days from valuation date to expiration.
        days_per_year: Day-count basis (365 by convention).
    """
    if index_value < 0:
        raise ValueError("index_value must be non-negative")
    if days_to_expiry < 0:
        raise ValueError("days_to_expiry must be non-negative")
    if days_per_year <= 0:
        raise ValueError("days_per_year must be positive")
    if annual_rate <= -1:
        raise ValueError("annual_rate must be greater than -100%")
    return index_value * ((1.0 + annual_rate) ** (days_to_expiry / days_per_year) - 1.0)


def dividend_points_from_cash(cash_dividends: float, index_divisor: float) -> float:
    """Convert a sum of cash dividends to index points via the index divisor.

        dividend_points = sum_of_cash_dividends / index_divisor
    """
    if index_divisor <= 0:
        raise ValueError("index_divisor must be positive")
    return cash_dividends / index_divisor


@dataclass(frozen=True)
class FairValueResult:
    """Result of a fair value calculation. All point figures are in index points."""

    index_value: float
    annual_rate: float
    days_to_expiry: float
    dividend_points: float
    days_per_year: float
    interest_component: float
    dividend_component: float
    fair_value_premium: float  # the colloquial "fair value" (futures - index)
    fair_value_price: float  # the full theoretical futures price

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"Index={self.index_value:.2f}  rate={self.annual_rate * 100:.3f}%  "
            f"days={self.days_to_expiry:g}\n"
            f"  interest component : {self.interest_component:+.2f}\n"
            f"  dividend component : {self.dividend_component:+.2f}\n"
            f"  fair value (premium): {self.fair_value_premium:+.2f}\n"
            f"  fair value price    : {self.fair_value_price:.2f}"
        )


def _compounded_dividend_points(
    dividend_points: Union[float, Iterable[tuple[float, float]]],
    annual_rate: float,
    horizon_days: float,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Dividend points reinvested to ``horizon_days`` (the contract's expiry).

    A float is already a sum and is returned unchanged. An iterable of
    ``(days_from_valuation, points)`` is compounded: each dividend, received on
    its ex-date, earns the financing rate until expiry -- the cost-of-carry
    convention. :func:`fair_value`, :func:`implied_rate` and
    :func:`implied_forward_rate` all invert this same convention, so they stay
    mutually consistent.
    """
    if isinstance(dividend_points, (int, float)):
        return float(dividend_points)
    total = 0.0
    for days_from_val, points in dividend_points:
        reinvest_days = max(0.0, horizon_days - days_from_val)
        total += points * (1.0 + annual_rate) ** (reinvest_days / days_per_year)
    return total


def fair_value(
    index_value: float,
    annual_rate: float,
    days_to_expiry: float,
    dividend_points: Union[float, Iterable[tuple[float, float]]] = 0.0,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> FairValueResult:
    """Compute the fair value premium and full fair value price.

    Args:
        index_value: Current index level (e.g. SPX).
        annual_rate: Annualised interest rate as a decimal.
        days_to_expiry: Calendar days from valuation date to expiration.
        dividend_points: Sum of dividends over the remaining life of the
            contract, already expressed in index points. Can be a float (sum)
            or an iterable of (days_from_valuation, points) for precise
            compounding of each dividend to expiration.
        days_per_year: Day-count basis (365 by convention).

    Returns:
        A :class:`FairValueResult`.
    """
    ic = interest_component(index_value, annual_rate, days_to_expiry, days_per_year)

    if isinstance(dividend_points, (int, float)):
        total_dividend_points = float(dividend_points)
    else:
        dividend_points = list(dividend_points)
        total_dividend_points = sum(points for _, points in dividend_points)
    # Reinvest each dividend from its ex-date to expiry (cost-of-carry); a float
    # is treated as an already-compounded sum. implied_rate / implied_forward_rate
    # invert this same convention, so the three stay mutually consistent.
    dc = _compounded_dividend_points(
        dividend_points, annual_rate, days_to_expiry, days_per_year
    )

    premium = ic - dc
    return FairValueResult(
        index_value=index_value,
        annual_rate=annual_rate,
        days_to_expiry=days_to_expiry,
        dividend_points=total_dividend_points,
        days_per_year=days_per_year,
        interest_component=ic,
        dividend_component=dc,
        fair_value_premium=premium,
        fair_value_price=index_value + premium,
    )


def basis(futures_price: float, index_value: float) -> float:
    """Observed basis of the futures vs the cash index (futures - index)."""
    return futures_price - index_value


def mispricing(futures_price: float, fair_value_price: float) -> float:
    """Futures richness/cheapness vs fair value.

    Positive => futures trade *rich* (above fair value); negative => *cheap*.
    This is what arbitrage desks watch: when it exceeds transaction costs it
    signals an index-arbitrage opportunity.
    """
    return futures_price - fair_value_price


def implied_rate(
    index_value: float,
    futures_price: float,
    days_to_expiry: float,
    dividend_points: Union[float, Iterable[tuple[float, float]]] = 0.0,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Back out the interest rate implied by an observed futures price.

    For a float ``dividend_points`` this inverts the closed form::

        r = ((futures + dividend_points) / index) ** (B / days) - 1

    For a ``(days_from_valuation, points)`` schedule each dividend compounds at
    the (unknown) rate, so the equation is transcendental; it is solved by a
    fixed-point iteration that discounts dividends exactly as :func:`fair_value`
    does, so backing out a rate and re-pricing round-trips.
    """
    if index_value <= 0:
        raise ValueError("index_value must be positive")
    if days_to_expiry <= 0:
        raise ValueError("days_to_expiry must be positive")

    if isinstance(dividend_points, (int, float)):
        base = (futures_price + float(dividend_points)) / index_value
        if base <= 0:
            raise ValueError("implied growth factor must be positive")
        return base ** (days_per_year / days_to_expiry) - 1.0

    divs = list(dividend_points)
    r = (futures_price + sum(p for _, p in divs)) / index_value
    if r <= 0:
        raise ValueError("implied growth factor must be positive")
    r = r ** (days_per_year / days_to_expiry) - 1.0  # undiscounted seed
    for _ in range(50):
        d = _compounded_dividend_points(divs, r, days_to_expiry, days_per_year)
        base = (futures_price + d) / index_value
        if base <= 0:
            raise ValueError("implied growth factor must be positive")
        r_next = base ** (days_per_year / days_to_expiry) - 1.0
        if abs(r_next - r) < 1e-13:
            return r_next
        r = r_next
    return r


def implied_forward_rate(
    near_price: float,
    near_dividend_points: Union[float, Iterable[tuple[float, float]]],
    near_days: float,
    far_price: float,
    far_dividend_points: Union[float, Iterable[tuple[float, float]]],
    far_days: float,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Financing rate implied by *two* futures on the same index -- free of spot.

    A single index level ``S`` underlies both contracts, so writing the fair
    value identity for each leg and dividing makes ``S`` cancel:

        near + near_div = S * (1 + f) ** (near_days / B)
        far  + far_div  = S * (1 + f) ** (far_days  / B)
        ------------------------------------------------------------------
        (far + far_div) / (near + near_div) = (1 + f) ** ((far - near) / B)

    so the rate comes purely from the two futures prices and their dividend
    points -- the cash index never enters. This is the calendar-spread (forward)
    financing rate for the period between the two settlements. Because it does
    not divide by spot, it is immune to a stale or inconsistent cash-index print
    (the failure mode that blows up :func:`implied_rate`); see
    :func:`fairvalue.session.compute_with_deferred_repo`.

    Args:
        near_price: Price of the nearer (front) future.
        near_dividend_points: Dividend points over the near contract's life.
        near_days: Calendar days from valuation to the near settlement.
        far_price: Price of the farther (deferred) future.
        far_dividend_points: Dividend points over the far contract's life.
        far_days: Calendar days from valuation to the far settlement.
        days_per_year: Day-count basis (365 by convention).

    Returns:
        The annualised forward financing rate as a decimal.
    """
    if far_days <= near_days:
        raise ValueError("far_days must be greater than near_days")

    near_is_float = isinstance(near_dividend_points, (int, float))
    far_is_float = isinstance(far_dividend_points, (int, float))
    if near_is_float and far_is_float:
        near = near_price + float(near_dividend_points)
        far = far_price + float(far_dividend_points)
        if near <= 0 or far <= 0:
            raise ValueError("price + dividend_points must be positive for both legs")
        return (far / near) ** (days_per_year / (far_days - near_days)) - 1.0

    # Dividend schedule(s): each dividend compounds to its own contract's expiry
    # at the (unknown) forward rate, matching fair_value. Solve by fixed point,
    # seeded with the undiscounted rate (r=0 compounding == the raw sum).
    r = 0.0
    for i in range(51):
        near = near_price + _compounded_dividend_points(
            near_dividend_points, r, near_days, days_per_year
        )
        far = far_price + _compounded_dividend_points(
            far_dividend_points, r, far_days, days_per_year
        )
        if near <= 0 or far <= 0:
            raise ValueError("price + dividend_points must be positive for both legs")
        r_next = (far / near) ** (days_per_year / (far_days - near_days)) - 1.0
        if i and abs(r_next - r) < 1e-13:
            return r_next
        r = r_next
    return r


def implied_dividend_points(
    index_value: float,
    futures_price: float,
    annual_rate: float,
    days_to_expiry: float,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Back out the dividend points implied by an observed futures price.

        dividend_points = index + interest_component - futures
    """
    ic = interest_component(index_value, annual_rate, days_to_expiry, days_per_year)
    return index_value + ic - futures_price
