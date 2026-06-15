"""Reproduce indexarb.com's published S&P 500 fair values for several sessions.

Run:  python examples/reproduce_indexarb.py

For each session the only inputs are the spot index, that day's zero-coupon
yield-curve nodes, and the divisor-adjusted dividend amounts. Contract interest
rates are interpolated from the curve exactly as the source does, so every
published number is reproduced from first inputs. June 2026 contracts settle
06-18 (Juneteenth moves the 3rd Friday back a day) -- handled automatically.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue import compute_fair_value  # noqa: E402
from fairvalue.providers.base import interpolate_rate  # noqa: E402

D = dt.date

# (name, expiry, days, dividend_points, ref rate%, ref interest, ref fair value, front?)
SESSIONS = [
    ("2026-02-13", D(2026, 2, 13), 6832.76,
     [(1, 3.780349), (28, 4.206838), (124, 3.882614), (215, 3.739206)],
     [("MAR", D(2026, 3, 20), 35, 10.223, 4.183197, 26.90, 16.68, True),
      ("JUN", D(2026, 6, 18), 125, 30.404, 3.881038, 89.68, 59.28, False)]),
    ("2026-03-11", D(2026, 3, 11), 6781.48,
     [(1, 3.790870), (31, 7.601384), (98, 3.828765), (189, 3.749328)],
     [("MAR", D(2026, 3, 20), 9, 2.708, 4.807007, 7.86, 5.15, True),
      ("JUN", D(2026, 6, 18), 99, 22.857, 3.827892, 69.45, 46.59, False)]),
    ("2026-04-13", D(2026, 4, 13), 6816.89,
     [(1, 3.711984), (30, 4.383418), (156, 4.365854), (247, 4.143284)],
     [("JUN", D(2026, 6, 18), 66, 16.002, 4.378400, 53.03, 37.03, True),
      ("SEP", D(2026, 9, 18), 158, 36.311, 4.360962, 127.13, 90.82, False)]),
    ("2026-05-29", D(2026, 5, 29), 7563.63,
     [(1, 3.743531), (31, 5.703780), (110, 3.968223), (201, 3.917712)],
     [("JUN", D(2026, 6, 18), 20, 5.923, 4.985022, 20.19, 14.27, True),
      ("SEP", D(2026, 9, 18), 112, 26.206, 3.967113, 90.83, 64.63, False)]),
]


def main() -> int:
    hdr = (f"{'session':11} {'ct':3} {'days':>4} {'rate% mine/ref':>17} "
           f"{'int mine/ref':>15} {'FV mine/ref':>15}  result")
    print(hdr)
    print("-" * len(hdr))
    all_ok = True
    for label, as_of, spot, nodes, contracts in SESSIONS:
        curve = [(t, r / 100.0) for t, r in nodes]
        for name, expiry, days, div, rr, ri, rfv, front in contracts:
            rate = interpolate_rate(curve, days)
            rep = compute_fair_value(as_of, spot, rate, div,
                                     expiry=None if front else expiry)
            ok = (abs(rate * 100 - rr) < 1e-5
                  and abs(rep.interest_component - ri) < 0.01
                  and abs(rep.fair_value_premium - rfv) < 0.01)
            all_ok &= ok
            print(f"{label:11} {name:3} {days:4d} {rate * 100:8.6f}/{rr:<8.6f} "
                  f"{rep.interest_component:7.2f}/{ri:<6.2f} "
                  f"{rep.fair_value_premium:7.2f}/{rfv:<6.2f}  "
                  f"{'MATCH' if ok else 'DIFF'}")
    print("-" * len(hdr))
    print("ALL MATCH" if all_ok else "SOME DIFFER")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
