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


def fair_value(
    index_value: float,
    annual_rate: float,
    days_to_expiry: float,
    dividend_points: float = 0.0,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> FairValueResult:
    """Compute the fair value premium and full fair value price.

    Args:
        index_value: Current index level (e.g. SPX).
        annual_rate: Annualised interest rate as a decimal.
        days_to_expiry: Calendar days from valuation date to expiration.
        dividend_points: Sum of dividends over the remaining life of the
            contract, already expressed in index points
            (use :func:`dividend_points_from_cash` to convert a cash sum).
        days_per_year: Day-count basis (365 by convention).

    Returns:
        A :class:`FairValueResult`.
    """
    ic = interest_component(index_value, annual_rate, days_to_expiry, days_per_year)
    dc = dividend_points
    premium = ic - dc
    return FairValueResult(
        index_value=index_value,
        annual_rate=annual_rate,
        days_to_expiry=days_to_expiry,
        dividend_points=dividend_points,
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
    dividend_points: float = 0.0,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
) -> float:
    """Back out the interest rate implied by an observed futures price.

    Inverts the fair value equation:

        r = ((futures + dividend_points) / index) ** (B / days) - 1
    """
    if index_value <= 0:
        raise ValueError("index_value must be positive")
    if days_to_expiry <= 0:
        raise ValueError("days_to_expiry must be positive")
    base = (futures_price + dividend_points) / index_value
    if base <= 0:
        raise ValueError("implied growth factor must be positive")
    return base ** (days_per_year / days_to_expiry) - 1.0


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
