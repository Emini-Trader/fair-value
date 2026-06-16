"""Tests for the web snapshot's end-of-day date selection (web/build_fairvalue.py).

The script lives outside the package, so it is loaded by path. Only the pure
date logic (resolve_dates) is exercised here -- no network.
"""

import datetime as dt
import importlib.util
import pathlib

_BUILD = pathlib.Path(__file__).resolve().parent.parent / "web" / "build_fairvalue.py"
_spec = importlib.util.spec_from_file_location("build_fairvalue", _BUILD)
build_fairvalue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_fairvalue)

resolve_dates = build_fairvalue.resolve_dates
D = dt.date


def test_prices_off_the_prior_session_on_a_normal_weekday():
    # Tue run, feeds carry through Mon -> price Mon, session is today (Tue).
    pd, s = resolve_dates(D(2026, 6, 16), D(2026, 6, 15))
    assert pd == D(2026, 6, 15)
    assert s == D(2026, 6, 16)


def test_monday_prices_off_friday():
    pd, s = resolve_dates(D(2026, 6, 15), D(2026, 6, 12))  # Mon, common close Fri
    assert pd == D(2026, 6, 12)
    assert s == D(2026, 6, 15)


def test_session_after_holiday_is_today_not_the_holiday():
    # Tue after Memorial Day Mon (2026-05-25): the feeds' latest common close is
    # Friday (Monday had none). price_date = Fri, but the session is correctly
    # *today* (Tue) -- not Monday, which _next_weekday(price_date) would wrongly give.
    pd, s = resolve_dates(D(2026, 5, 26), D(2026, 5, 22))
    assert pd == D(2026, 5, 22)
    assert s == D(2026, 5, 26)


def test_never_uses_an_intraday_same_day_close():
    # Even if a feed posts a provisional "today" candle, price_date stays strictly
    # before today (the prior weekday) -- fair value is never intraday.
    pd, s = resolve_dates(D(2026, 6, 17), D(2026, 6, 17))  # Wed, common close Wed(!)
    assert pd == D(2026, 6, 16)  # Tue, not Wed
    assert s == D(2026, 6, 17)


def test_weekend_manual_run_rolls_to_next_weekday():
    pd, s = resolve_dates(D(2026, 6, 20), D(2026, 6, 19))  # Sat, common close Fri
    assert pd == D(2026, 6, 19)
    assert s == D(2026, 6, 22)  # Monday


def test_explicit_price_date_backfill_derives_session():
    pd, s = resolve_dates(D(2026, 6, 16), D(2026, 6, 15), price_date=D(2026, 6, 3))
    assert pd == D(2026, 6, 3)
    assert s == D(2026, 6, 4)  # next weekday after the backfilled close


def test_explicit_session_override_is_honoured():
    _, s = resolve_dates(D(2026, 6, 16), D(2026, 6, 15), session=D(2026, 7, 1))
    assert s == D(2026, 7, 1)
