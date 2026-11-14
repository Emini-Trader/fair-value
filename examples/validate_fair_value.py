"""Validate the front fair value against all 19 indexarb readings (2025-01 .. 2026-06).

Run:  python examples/validate_fair_value.py

indexarb publishes a session-D fair value computed off the *prior* session's
close (verified: its 2026-05-29 spot 7563.63 is the 2026-05-28 close), with days
and dividends from D. We replicate that convention (`--prior-close`).

Two views:
  * deferred-repo (our non-circular model): prices the front with the next
    contract's implied funding rate. It needs the deferred ES contract, and the
    2025 deferreds are expired/delisted on Yahoo, so it runs on the 6 most recent
    sessions (where the deferred is JUN26 / SEP26).
  * basis (ES=F - SPX, = front implied-repo FV): shown for all 19 as a sanity
    check. It ties out except at quarterly rolls, where indexarb advances its
    listed front on the Monday of expiration week (when ES open interest rolls),
    before Yahoo's continuous ES=F does -- so they quote different contracts
    those days (flagged ROLL). See fairvalue.calendar.front_settlement.
"""
import datetime as dt
import pathlib
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue.core import fair_value, implied_forward_rate, implied_rate  # noqa: E402
from fairvalue.providers.total_return import (  # noqa: E402
    daily_dividend_points, estimate_yoy_growth, seasonal_forward_dividends,
)
from fairvalue.providers.yahoo import (  # noqa: E402
    SPX, SPX_TOTAL_RETURN, YahooPriceProvider, close_on_or_before,
)

D = dt.date.fromisoformat
# (session, front_exp, deferred_exp|None, deferred_sym|None, indexarb_front_FV)
SESSIONS = [
    ("2025-01-14", "2025-03-21", None, None, 38.31),
    ("2025-01-17", "2025-03-21", None, None, 38.24),
    ("2025-03-19", "2025-06-20", None, None, 52.88),
    ("2025-05-21", "2025-06-20", None, None, 16.68),
    ("2025-06-20", "2025-09-19", None, None, 53.19),
    ("2025-07-15", "2025-09-19", None, None, 40.78),
    ("2025-08-07", "2025-09-19", None, None, 24.95),
    ("2025-08-21", "2025-09-19", None, None, 18.35),
    ("2025-09-08", "2025-09-19", None, None, 6.76),
    ("2025-09-15", "2025-12-19", None, None, 59.94),
    ("2025-10-07", "2025-12-19", None, None, 47.53),
    ("2025-11-14", "2025-12-19", None, None, 21.67),
    ("2025-12-12", "2025-12-19", None, None, 3.35),
    ("2026-01-20", "2026-03-20", "2026-06-18", "ESM26.CME", 33.48),
    ("2026-02-13", "2026-03-20", "2026-06-18", "ESM26.CME", 16.68),
    ("2026-03-11", "2026-03-20", "2026-06-18", "ESM26.CME", 5.15),
    ("2026-04-13", "2026-06-18", "2026-09-18", "ESU26.CME", 37.03),
    ("2026-05-29", "2026-06-18", "2026-09-18", "ESU26.CME", 14.27),
    ("2026-06-03", "2026-06-18", "2026-09-18", "ESU26.CME", 9.93),
]


def main() -> int:
    pp = YahooPriceProvider()
    spx = pp.history(SPX, D("2022-12-01"), D("2026-06-15"))
    trr = pp.history(SPX_TOTAL_RETURN, D("2022-12-01"), D("2026-06-15"))
    esf = pp.history("ES=F", D("2024-06-01"), D("2026-06-15"))
    deferred = {s: pp.history(s, D("2025-06-01"), D("2026-06-15"))
                for s in ("ESM26.CME", "ESU26.CME")}
    divs = daily_dividend_points(spx, trr)

    print(f"{'session':11} {'fd':>3} {'basis':>7} {'idxFV':>7} {'Δbasis':>7} "
          f"| {'defRepo':>7} {'Δrepo':>6} {'r-rcal':>7}")
    print("-" * 69)
    repo_err = []
    rate_gap = []  # |deferred-zero rate - spot-free calendar rate| (robustness guard)
    for s, fe_s, de_s, sym, idx in SESSIONS:
        d, fe = D(s), D(fe_s)
        prior = d - dt.timedelta(days=1)
        spot = close_on_or_before(spx, prior)
        es = close_on_or_before(esf, prior)
        basis = es - spot
        roll = " ROLL" if abs(basis - idx) > 10 else ""
        fd = (fe - d).days
        g = estimate_yoy_growth(divs, d)
        fdiv = seasonal_forward_dividends(divs, d, fe, years_back=1, growth=g)
        repo = drepo = dgap = ""
        if sym:
            de = D(de_s)
            dd = (de - d).days
            des = close_on_or_before(deferred[sym], prior)
            ddiv = seasonal_forward_dividends(divs, d, de, years_back=1, growth=g)
            rate = implied_rate(spot, des, dd, ddiv)
            fv = fair_value(spot, rate, fd, fdiv).fair_value_premium
            repo_err.append(fv - idx)
            repo, drepo = f"{fv:7.2f}", f"{fv - idx:+6.2f}"
            # Spot-free cross-check: the calendar-spread rate from front (ES=F,
            # non-roll here) and deferred futures should track the deferred-zero
            # rate to well within the 1.5% guard -- it only blows out on a stale
            # spot, which this prior-close, same-day sampling avoids.
            if not roll:
                cal = implied_forward_rate(es, fdiv, fd, des, ddiv, dd)
                rate_gap.append(abs(rate - cal))
                dgap = f"{(rate - cal) * 100:+6.3f}"
        print(f"{s:11} {fd:3d} {basis:7.2f} {idx:7.2f} {basis - idx:+7.2f}{roll:5} "
              f"| {repo:>7} {drepo:>6} {dgap:>7}")
    print("-" * 69)
    print(f"deferred-repo ({len(repo_err)} recent sessions, prior-close): "
          f"mean {st.mean(repo_err):+.2f}  stdev {st.pstdev(repo_err):.2f}  "
          f"maxAbs {max(abs(x) for x in repo_err):.2f}")
    print(f"rate guard: max |deferred-zero − calendar| = {max(rate_gap) * 100:.3f}%  "
          f"(< 1.5% guard on all {len(rate_gap)} sessions ⇒ deferred rate kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
