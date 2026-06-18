"""Build the fair-value snapshot the web dashboard reads (web/data.json).

Run by the GitHub Action in the evening after the US close: fair value is an
end-of-day figure, so it prices the *front* ES contract for the NEXT session off
the close that just settled (the last completed trading session -- indexarb's
overnight convention), never an intraday value, and writes a small JSON the
static page renders.

    python web/build_fairvalue.py                 # auto: next session, prior close
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


#: US cash + equity-index futures settle at 16:00 ET; after this hour the
#: session's end-of-day data is final. The evening build runs past it, so it can
#: treat today's close as the last completed session (see resolve_dates).
SESSION_CLOSE_ET_HOUR = 17


def _now_et() -> dt.datetime:
    """Current time in New York (EST/EDT-aware), tz-aware.

    The build runs in the evening after the US close, so both the New York DATE
    and whether we are past the close decide which session to price. Falls back
    to a fixed UTC-5 (EST) clock only if the tz database is unavailable (it is
    present on the CI runner and any normal install).
    """
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001 - no tzdata: approximate ET as UTC-5 (EST)
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)


def resolve_dates(
    now_et: dt.datetime,
    latest_common_close: dt.date,
    *,
    price_date: dt.date | None = None,
    session: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    """Pick (price_date, session): the NEXT trading session, priced off the last
    COMPLETED session's close.

    Fair value is an end-of-day figure and the Action runs in the evening after
    the US close. Once we are past the close (``SESSION_CLOSE_ET_HOUR``) on a
    trading day -- and the feed actually carries today's close -- today is the
    last completed session, so we price the *next* session off it. Before the
    close (or if today's close is not posted yet) we price off the most recent
    prior session instead -- never an intraday value. The output is therefore
    stable across GitHub's scheduling delay: whether the run lands this evening
    or after midnight, it yields the same next-session snapshot. Explicit
    ``price_date`` / ``session`` (manual backfills) win.
    """
    today = now_et.date()
    past_close = now_et.hour >= SESSION_CLOSE_ET_HOUR
    if past_close and today.weekday() < 5 and latest_common_close >= today:
        last_close = today  # evening of a trading day: today's close is final
    else:
        prior = _latest_weekday(today - dt.timedelta(days=1))
        last_close = min(latest_common_close, prior)  # else the prior session
    pd = price_date or last_close
    s = session or _next_weekday(pd)
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
    # End-of-day rule: anchor to New York time and price the next session off the
    # last completed session's close (never today's intraday value). See
    # resolve_dates.
    now_et = _now_et()
    price_date, session = resolve_dates(
        now_et, _latest_common_close(price, now_et.date()),
        price_date=ns.price_date, session=ns.session,
    )

    try:
        data = build(session, price_date, price, divs)
        if (now_et.date() - price_date).days > 4:
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
