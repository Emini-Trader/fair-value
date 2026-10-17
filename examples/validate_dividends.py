"""Validate the total-return dividend estimator against indexarb's own figures.

Run:  python examples/validate_dividends.py

indexarb publishes, per session, the divisor-adjusted dividend points for each
listed S&P 500 contract ("Dividend Amounts" page). The 18 sessions below
(2025-01 .. 2026-05, transcribed from those pages) are the ground truth. For
each we run the free estimator -- realised dividend points from ^SP500TR vs
^GSPC over last year's same calendar window, scaled by the data-measured YoY
growth (no hand-set constant) -- and compare.

The estimator tracks the *realised* dividends and lands a little above
indexarb's figure, because indexarb forecasts only known/announced dividends and
so runs ~0.7 pt below what actually goes ex. Needs Yahoo on the allowlist.
"""
import datetime as dt
import pathlib
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue.providers.total_return import (  # noqa: E402
    daily_dividend_points, estimate_yoy_growth, seasonal_forward_dividends,
)
from fairvalue.providers.yahoo import (  # noqa: E402
    SPX, SPX_TOTAL_RETURN, YahooPriceProvider,
)

D = dt.date.fromisoformat

# (session, [(contract, expiry, indexarb_divisor_adjusted_points), ...])
SESSIONS = [
    ("2025-01-17", [("MAR25", "2025-03-21", 14.622), ("JUN25", "2025-06-20", 34.155)]),
    ("2025-02-12", [("MAR25", "2025-03-21", 10.608), ("JUN25", "2025-06-20", 30.099)]),
    ("2025-04-24", [("JUN25", "2025-06-20", 14.228), ("SEP25", "2025-09-19", 33.447)]),
    ("2025-06-20", [("SEP25", "2025-09-19", 19.145), ("DEC25", "2025-12-19", 39.088)]),
    ("2025-06-23", [("SEP25", "2025-09-19", 18.995), ("DEC25", "2025-12-19", 38.921)]),
    ("2025-07-15", [("SEP25", "2025-09-19", 14.741), ("DEC25", "2025-12-19", 34.703)]),
    ("2025-08-07", [("SEP25", "2025-09-19", 12.266), ("DEC25", "2025-12-19", 32.203)]),
    ("2025-09-11", [("SEP25", "2025-09-19", 2.383), ("DEC25", "2025-12-19", 22.330)]),
    ("2025-10-06", [("DEC25", "2025-12-19", 16.804), ("MAR26", "2026-03-20", 37.362)]),
    ("2025-10-13", [("DEC25", "2025-12-19", 15.650), ("MAR26", "2026-03-20", 36.209)]),
    ("2025-11-14", [("DEC25", "2025-12-19", 9.613), ("MAR26", "2026-03-20", 30.193)]),
    ("2025-11-17", [("DEC25", "2025-12-19", 9.004), ("MAR26", "2026-03-20", 29.598)]),
    ("2025-12-12", [("DEC25", "2025-12-19", 1.776), ("MAR26", "2026-03-20", 22.364)]),
    ("2026-01-20", [("MAR26", "2026-03-20", 15.199), ("JUN26", "2026-06-18", 35.317)]),
    ("2026-02-13", [("MAR26", "2026-03-20", 10.223), ("JUN26", "2026-06-18", 30.404)]),
    ("2026-03-11", [("MAR26", "2026-03-20", 2.708), ("JUN26", "2026-06-18", 22.857)]),
    ("2026-04-13", [("JUN26", "2026-06-18", 16.002), ("SEP26", "2026-09-18", 36.311)]),
    ("2026-05-29", [("JUN26", "2026-06-18", 5.923), ("SEP26", "2026-09-18", 26.206)]),
]


def main() -> int:
    pp = YahooPriceProvider()
    # one fetch covering all sessions' prior-year windows + the growth lookback
    lo = D(SESSIONS[0][0]).replace(year=D(SESSIONS[0][0]).year - 2) - dt.timedelta(days=15)
    hi = D(SESSIONS[-1][0])
    divs = daily_dividend_points(pp.history(SPX, lo, hi), pp.history(SPX_TOTAL_RETURN, lo, hi))

    print(f"{'session':11} {'ct':6} {'g%':>5} {'estimate':>8} {'indexarb':>8} {'diff':>6}")
    print("-" * 50)
    errs = []
    for s, rows in SESSIONS:
        a = D(s)
        g = estimate_yoy_growth(divs, a)
        for lbl, exp, idx in rows:
            est = seasonal_forward_dividends(divs, a, D(exp), years_back=1, growth=g)
            errs.append(est - idx)
            print(f"{s:11} {lbl:6} {(g-1)*100:4.1f} {est:8.3f} {idx:8.3f} {est-idx:+6.2f}")
    print("-" * 50)
    print(f"mean diff {st.mean(errs):+.2f}   stdev {st.pstdev(errs):.2f}   "
          f"maxAbs {max(abs(x) for x in errs):.2f}   (vs indexarb's forecast)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
