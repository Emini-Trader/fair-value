"""Reproduce indexarb.com's S&P 500 fair values for May 29, 2026.

Run:  python examples/reproduce_2026_05_29.py

Source data (indexarb.com, 2026-05-29):
  - Spot S&P 500 = 7563.63
  - Zero-coupon yield curve nodes (days from origin, rate %)
  - Dividend amounts (divisor-adjusted, in index points)
The contract interest rates are interpolated from the curve, exactly as the
site does, so this script reproduces every published number from first inputs.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue import compute_fair_value  # noqa: E402
from fairvalue.providers.base import interpolate_rate  # noqa: E402

AS_OF = dt.date(2026, 5, 29)
SPX = 7563.63

# Zero-coupon curve nodes: (days from origin, rate decimal)
CURVE = [(d, r / 100.0) for d, r in
         [(1, 3.743531), (31, 5.703780), (110, 3.968223), (201, 3.917712)]]

# Per-contract: expiry (holiday-adjusted), dividend points, and the published
# reference values to check against.
CONTRACTS = [
    ("JUN 2026", dt.date(2026, 6, 18), 5.923, dict(rate=4.985022, interest=20.19, fv=14.27)),
    ("SEP 2026", dt.date(2026, 9, 18), 26.206, dict(rate=3.967113, interest=90.83, fv=64.63)),
]


def main() -> None:
    print(f"indexarb reproduction  --  S&P 500 spot {SPX}  as of {AS_OF}\n")
    header = f"{'contract':9} {'days':>4} {'rate %':>9} {'interest':>9} {'div':>7} {'FAIR VALUE':>11}   vs ref"
    print(header)
    print("-" * len(header))
    for name, expiry, div, ref in CONTRACTS:
        days = (expiry - AS_OF).days
        rate = interpolate_rate(CURVE, days)
        rep = compute_fair_value(AS_OF, SPX, rate, div, expiry=expiry)
        ok = (
            abs(rate * 100 - ref["rate"]) < 5e-6
            and abs(rep.interest_component - ref["interest"]) < 0.01
            and abs(rep.fair_value_premium - ref["fv"]) < 0.01
        )
        print(
            f"{name:9} {days:4d} {rate * 100:9.6f} {rep.interest_component:9.2f} "
            f"{div:7.3f} {rep.fair_value_premium:11.2f}   "
            f"{'MATCH' if ok else 'DIFF'} (ref {ref['fv']})"
        )


if __name__ == "__main__":
    main()
