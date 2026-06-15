"""High-level fair value calculator.

Wires together the expiration :mod:`~fairvalue.calendar` and the
:mod:`~fairvalue.core` mathematics into a single call that takes a valuation
date and market inputs and returns a complete, presentable report.

This layer is deliberately independent of where the inputs come from: you can
pass values in by hand (works offline, today) or have a data provider supply
them (see :mod:`fairvalue.providers`). That keeps the reproduction testable and
lets us validate against known historical sessions before trusting any feed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .calendar import contract_code, days_to_expiry, next_quarterly_settlement
from .core import DEFAULT_DAYS_PER_YEAR, basis, fair_value, mispricing


@dataclass(frozen=True)
class FairValueReport:
    """Everything needed to read off (and check) a fair value calculation."""

    as_of: dt.date
    expiry: dt.date
    contract: str
    days_to_expiry: int
    index_value: float
    annual_rate: float
    dividend_points: float
    days_per_year: float
    interest_component: float
    dividend_component: float
    fair_value_premium: float  # colloquial "fair value" (futures - index)
    fair_value_price: float  # full theoretical futures price
    futures_price: float | None = None  # observed future, if supplied
    observed_basis: float | None = None  # futures_price - index
    mispricing: float | None = None  # futures_price - fair_value_price

    def __str__(self) -> str:  # pragma: no cover - cosmetic formatting
        lines = [
            f"Fair value for {self.as_of:%Y-%m-%d}  ->  {self.contract} "
            f"(exp {self.expiry:%Y-%m-%d}, {self.days_to_expiry} days)",
            f"  index level         : {self.index_value:.2f}",
            f"  interest rate        : {self.annual_rate * 100:.3f}%",
            f"  interest component   : {self.interest_component:+.2f}",
            f"  dividend component   : {self.dividend_component:+.2f}  "
            f"(points: {self.dividend_points:.2f})",
            f"  --------------------------------------------",
            f"  FAIR VALUE (premium) : {self.fair_value_premium:+.2f}",
            f"  fair value price     : {self.fair_value_price:.2f}",
        ]
        if self.futures_price is not None:
            mp = self.mispricing or 0.0
            verdict = "fair" if abs(mp) < 0.005 else ("rich" if mp > 0 else "cheap")
            lines += [
                f"  observed future      : {self.futures_price:.2f}",
                f"  observed basis       : {self.observed_basis:+.2f}",
                f"  vs fair value        : {self.mispricing:+.2f} ({verdict})",
            ]
        return "\n".join(lines)


def compute_fair_value(
    as_of: dt.date,
    index_value: float,
    annual_rate: float,
    dividend_points: float = 0.0,
    *,
    expiry: dt.date | None = None,
    futures_price: float | None = None,
    days_per_year: float = DEFAULT_DAYS_PER_YEAR,
    root: str = "ES",
) -> FairValueReport:
    """Compute a full fair value report for ``as_of``.

    Args:
        as_of: Valuation date.
        index_value: Index level on ``as_of`` (e.g. the SPX close).
        annual_rate: Annualised interest rate as a decimal (0.0533 == 5.33%).
        dividend_points: Dividends over the contract's remaining life, in index
            points (divisor-adjusted).
        expiry: Override the contract expiration date. By default the nearest
            quarterly settlement on/after ``as_of`` is used -- the 3rd Friday,
            rolled back off an exchange holiday (e.g. Juneteenth). Note real
            desks roll to the next contract in the ~week before expiry; pass
            ``expiry`` explicitly to match a specific contract during roll week.
        futures_price: If given, the report also reports observed basis and the
            futures' richness/cheapness vs fair value.
        days_per_year: Day-count basis (365 by convention).
        root: Contract root for the symbol label (default "ES").
    """
    if expiry is None:
        expiry = next_quarterly_settlement(as_of, on_or_after=True)
    days = days_to_expiry(as_of, expiry)

    fv = fair_value(
        index_value=index_value,
        annual_rate=annual_rate,
        days_to_expiry=days,
        dividend_points=dividend_points,
        days_per_year=days_per_year,
    )

    observed_basis = mp = None
    if futures_price is not None:
        observed_basis = basis(futures_price, index_value)
        mp = mispricing(futures_price, fv.fair_value_price)

    return FairValueReport(
        as_of=as_of,
        expiry=expiry,
        contract=contract_code(expiry, root=root),
        days_to_expiry=days,
        index_value=index_value,
        annual_rate=annual_rate,
        dividend_points=dividend_points,
        days_per_year=days_per_year,
        interest_component=fv.interest_component,
        dividend_component=fv.dividend_component,
        fair_value_premium=fv.fair_value_premium,
        fair_value_price=fv.fair_value_price,
        futures_price=futures_price,
        observed_basis=observed_basis,
        mispricing=mp,
    )
