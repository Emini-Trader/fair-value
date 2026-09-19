"""Provider interfaces and pure helpers shared by data sources.

The provider *interfaces* (Protocols) let the calculator stay agnostic about
where market inputs come from. The pure helpers here (rate interpolation) carry
the real logic and are unit-tested directly, with no network involved.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol, Sequence, runtime_checkable, Union, Iterable

#: A point on a yield curve: (tenor in days, rate as a decimal).
RatePoint = tuple[float, float]


@runtime_checkable
class RateProvider(Protocol):
    """Supplies an annualised interest rate for an exact horizon."""

    def zero_rate(self, as_of: dt.date, days: float) -> float: ...


@runtime_checkable
class PriceProvider(Protocol):
    """Supplies a closing price for a symbol on (or nearest before) a date."""

    def close(self, symbol: str, day: dt.date) -> float: ...


@runtime_checkable
class DividendProvider(Protocol):
    """Supplies dividend points accruing over a contract's remaining life."""

    def dividend_points(
        self, as_of: dt.date, expiry: dt.date, index_value: float
    ) -> Union[float, Iterable[tuple[float, float]]]: ...


def interpolate_rate(points: Sequence[RatePoint], target_days: float) -> float:
    """Linearly interpolate a rate for ``target_days`` from yield-curve points.

    Points need not be sorted. Outside the provided range the nearest endpoint
    is used (flat extrapolation), which is the conventional choice for the very
    short and long ends of a money-market curve.

    Args:
        points: Sequence of ``(tenor_days, rate_decimal)`` knots.
        target_days: Horizon to interpolate to, in days.

    Returns:
        The interpolated rate as a decimal.
    """
    if not points:
        raise ValueError("need at least one rate point to interpolate")
    pts = sorted(points)
    if target_days <= pts[0][0]:
        return pts[0][1]
    if target_days >= pts[-1][0]:
        return pts[-1][1]
    for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
        if d0 <= target_days <= d1:
            weight = (target_days - d0) / (d1 - d0)
            return r0 + weight * (r1 - r0)
    raise RuntimeError("unreachable: target_days within range but no bracket found")
