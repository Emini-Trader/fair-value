"""Build the fair-value snapshot the web dashboard reads (web/data.json).

Run by the GitHub Action just after midnight in New York: fair value is an
end-of-day figure, so it always prices the *front* ES contract off the LAST
COMPLETED trading session (the prior trading day -- indexarb's overnight
convention), never an intraday / same-day value, and writes a small JSON the
static page renders.

    python web/build_fairvalue.py                 # auto: prior completed close
    python web/build_fairvalue.py --session 2026-06-04 --price-date 2026-06-03
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue.calendar import contract_code, next_quarterly_settlement  # noqa: E402
from fairvalue.session import compute_with_deferred_repo  # noqa: E402
from fairvalue.providers.total_return import TotalReturnDividendProvider  # noqa: E402
from fairvalue.providers.yahoo import ES_FRONT, SPX, YahooPriceProvider  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "data.json"


def _next_weekday(day: dt.date) -> dt.date:
    nxt = day + dt.timedelta(days=1)
    while nxt.weekday() >= 5:  # Sat/Sun -> Monday
        nxt += dt.timedelta(days=1)
    return nxt


def _latest_weekday(day: dt.date) -> dt.date:
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def _latest_common_close(price: YahooPriceProvider, today: dt.date) -> dt.date:
    """Latest date for which BOTH the cash index and the front future have a
    close, so spot and futures are sampled on the *same* day.

    A feed can publish the futures' close a day before the cash index's; pricing
    a stale spot against a fresh future inflates the basis (and the implied
    rate). Anchoring to the latest common date avoids that. Falls back to the
    latest weekday if either history is missing.
    """
    lo = today - dt.timedelta(days=20)
    try:
        spot = price.history(SPX, lo, today)
        fut = price.history(ES_FRONT, lo, today)
        return min(max(d for d, _ in spot), max(d for d, _ in fut))
    except Exception:  # noqa: BLE001 - degrade gracefully
        return _latest_weekday(today)


def _now_et_date() -> dt.date:
    """Today's calendar date in New York (EST/EDT-aware).

    Fair value is computed just after midnight NY, so the New York date -- not
    the UTC date -- decides which session is "today". Falls back to a UTC-5
    approximation only if the tz database is unavailable (it is present on the
    CI runner and any normal install).
    """
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:  # noqa: BLE001 - no tzdata: approximate ET as UTC-5 (EST)
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).date()


def resolve_dates(
    today_et: dt.date,
    latest_common_close: dt.date,
    *,
    price_date: dt.date | None = None,
    session: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    """Pick (price_date, session) under the end-of-day / midnight-NY rule.

    ``price_date`` is the LAST COMPLETED trading session: strictly before today
    in New York (so it is fully closed -- never an intraday value), and no later
    than the most recent date both feeds actually carry (which skips weekends,
    holidays and feed lag). ``session`` is the day being priced -- "today" in New
    York for the scheduled post-midnight run, else the next weekday after the
    close. Explicit ``price_date`` / ``session`` (manual backfills) win.
    """
    prior = _latest_weekday(today_et - dt.timedelta(days=1))
    pd = price_date or min(latest_common_close, prior)
    if session is not None:
        s = session
    elif price_date is None and today_et.weekday() < 5:
        s = today_et  # the scheduled run fires at ~00:01 ET on the session day
    else:
        s = _next_weekday(pd)
    return pd, s


def build(session: dt.date, price_date: dt.date,
          price: YahooPriceProvider, divs: TotalReturnDividendProvider) -> dict:
    rep = compute_with_deferred_repo(session, price, divs, price_date=price_date)
    deferred = next_quarterly_settlement(rep.expiry, on_or_after=False)
    mp = rep.mispricing or 0.0
    return {
        "ok": True,
        "computed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session.isoformat(),
        "price_date": price_date.isoformat(),
        "contract": rep.contract,
        "deferred_contract": contract_code(deferred),
        "expiry": rep.expiry.isoformat(),
        "days_to_expiry": rep.days_to_expiry,
        "spot": round(rep.index_value, 2),
        "rate_pct": round(rep.annual_rate * 100, 3),
        "rate_source": rep.rate_source,
        "dividend_points": round(rep.dividend_points, 2),
        "interest_component": round(rep.interest_component, 2),
        "dividend_component": round(rep.dividend_component, 2),
        "fair_value_premium": round(rep.fair_value_premium, 2),
        "fair_value_price": round(rep.fair_value_price, 2),
        "observed_future": round(rep.futures_price, 2) if rep.futures_price else None,
        "observed_basis": round(rep.observed_basis, 2) if rep.observed_basis is not None else None,
        "mispricing": round(mp, 2),
        "verdict": "fair" if abs(mp) < 0.5 else ("rich" if mp > 0 else "cheap"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build web/data.json fair-value snapshot.")
    p.add_argument("--session", type=dt.date.fromisoformat,
                   help="target session date (default: today in New York)")
    p.add_argument("--price-date", type=dt.date.fromisoformat,
                   help="close used as spot (default: last completed session)")
    ns = p.parse_args(argv)

    price = YahooPriceProvider()
    divs = TotalReturnDividendProvider()
    # End-of-day rule: anchor to New York time and price off the last completed
    # trading session (never today's intraday value). See resolve_dates.
    today_et = _now_et_date()
    price_date, session = resolve_dates(
        today_et, _latest_common_close(price, today_et),
        price_date=ns.price_date, session=ns.session,
    )

    try:
        data = build(session, price_date, price, divs)
        if (today_et - price_date).days > 4:
            data["warning"] = (
                f"Cash index data lags the futures; pricing off the latest "
                f"consistent close ({price_date})."
            )
        # When the cash spot is stale/inconsistent with the futures, the
        # deferred implied repo blows up; compute_with_deferred_repo detects this
        # (deferred-zero vs spot-free calendar rate diverge) and falls back to the
        # spot-free rate. Surface that so the fair value is trusted but the spot
        # caveat is visible. A residual band check stays as a final backstop.
        if data.get("ok") and data.get("rate_source") == "calendar_spread":
            data["warning"] = (
                "Cash index looked stale/inconsistent with the futures, so the "
                "financing rate was taken from the futures calendar spread "
                "(spot-free) instead of the deferred implied repo."
            )
        elif data.get("ok") and not (0.5 <= data["rate_pct"] <= 7.0):
            data["warning"] = (
                f"Implied funding rate {data['rate_pct']:.2f}% is outside the "
                f"normal range — likely a stale or inconsistent spot/futures quote."
            )
    except Exception as exc:  # noqa: BLE001 - record the failure for the page
        data = {
            "ok": False,
            "computed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": session.isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
