"""Build the fair-value snapshot the web dashboard reads (web/data.json).

Run by the GitHub Action after the US close, once the day's futures candle has
settled on Yahoo: fair value is an end-of-day figure, so it prices the *front*
ES contract for the NEXT session off the close that just settled (the last
completed trading session -- indexarb's overnight convention), never an intraday
value, and writes a small JSON the static page renders.

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

from fairvalue.calendar import (  # noqa: E402
    contract_code,
    funding_turn_in_window,
    next_quarterly_settlement,
)
from fairvalue.session import compute_with_deferred_repo  # noqa: E402
from fairvalue.providers.total_return import TotalReturnDividendProvider  # noqa: E402
from fairvalue.providers.fred import FredRateProvider  # noqa: E402
from fairvalue.providers.yahoo import ES_FRONT, SPX, YahooPriceProvider  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "data.json"
#: Rolling self-diagnostic log: one record per session of the model offset vs the
#: observed front basis, so a systematic near-expiry / turn drift can be measured
#: from data over time (aggregate with examples/diagnose_offset.py).
LOG = pathlib.Path(__file__).resolve().parent / "offset_history.jsonl"


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
          price: YahooPriceProvider, divs: TotalReturnDividendProvider,
          shape: FredRateProvider) -> dict:
    rep = compute_with_deferred_repo(session, price, divs, price_date=price_date, shape_provider=shape)
    deferred = next_quarterly_settlement(rep.expiry, on_or_after=False)
    mp = rep.mispricing or 0.0
    result = {
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
    if rep.curve_shape_adjustment is not None:
        result["curve_shape_adjustment"] = round(rep.curve_shape_adjustment * 100, 3)
    result["liquidity_warning"] = rep.liquidity_warning
    result["fallback_spot_fv"] = round(rep.fallback_spot_fv, 2) if rep.fallback_spot_fv is not None else None
    # Funding-turn flag: pure-calendar detection of a quarter-/year-end the front
    # horizon spans, where the carry model can run a touch light (unmodelled
    # turn-of-quarter repo tightening). Detection only -- no market data.
    turn = funding_turn_in_window(session, rep.expiry)
    result["turn_session"] = turn is not None
    if turn is not None:
        result["turn_kind"] = turn["kind"]
        result["turn_date"] = turn["date"].isoformat()
    return result


def _append_offset_record(data: dict, path: pathlib.Path = LOG) -> None:
    """Upsert one session's model-vs-observed offset record into the JSONL log.

    Idempotent by date (the backup evening run just overwrites the day's record).
    Records the raw pieces -- the consumer derives gap = model_offset -
    observed_basis. Skipped when the snapshot failed or has no observed future.
    """
    if not data.get("ok") or data.get("observed_basis") is None:
        return
    record = {
        "date": data["price_date"],
        "dte": data["days_to_expiry"],
        "turn": data.get("turn_session", False),
        "turn_kind": data.get("turn_kind"),
        "model_offset": data["fair_value_premium"],
        "observed_basis": data["observed_basis"],
        "rate_pct": data["rate_pct"],
        "spot": data["spot"],
    }
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("date") != record["date"]:
                rows.append(row)
    rows.append(record)
    rows.sort(key=lambda r: r.get("date", ""))
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build web/data.json fair-value snapshot.")
    p.add_argument("--session", type=dt.date.fromisoformat,
                   help="target session date (default: today in New York)")
    p.add_argument("--price-date", type=dt.date.fromisoformat,
                   help="close used as spot (default: last completed session)")
    ns = p.parse_args(argv)

    price = YahooPriceProvider()
    divs = TotalReturnDividendProvider()
    shape = FredRateProvider()
    # End-of-day rule: anchor to New York time and price the next session off the
    # last completed session's close (never today's intraday value). See
    # resolve_dates.
    now_et = _now_et()
    price_date, session = resolve_dates(
        now_et, _latest_common_close(price, now_et.date()),
        price_date=ns.price_date, session=ns.session,
    )

    try:
        data = build(session, price_date, price, divs, shape)
        if (now_et.date() - price_date).days > 4:
            data["warning"] = (
                f"Cash index data lags the futures; pricing off the latest "
                f"consistent close ({price_date})."
            )
        if data.get("ok") and not (0.5 <= data["rate_pct"] <= 7.0):
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
    _append_offset_record(data)
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
