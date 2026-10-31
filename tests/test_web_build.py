"""Tests for the web snapshot's evening end-of-day date selection.

The script (web/build_fairvalue.py) lives outside the package, so it is loaded
by path. Only the pure date logic (resolve_dates) is exercised here -- no network.
resolve_dates takes the current New York time and the latest date both feeds
carry, and returns (price_date, session) for the *next* trading session priced
off the last completed close.
"""

import datetime as dt
import importlib.util
import json
import pathlib

_BUILD = pathlib.Path(__file__).resolve().parent.parent / "web" / "build_fairvalue.py"
_spec = importlib.util.spec_from_file_location("build_fairvalue", _BUILD)
build_fairvalue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_fairvalue)

resolve_dates = build_fairvalue.resolve_dates
D = dt.date


def _et(y, m, d, h):
    return dt.datetime(y, m, d, h)  # naive ET datetime (resolve_dates uses .date()/.hour)


def test_evening_after_close_prices_next_session_off_today():
    # Tue 18:30 ET, feeds carry today's (Tue) close -> price Tue, session = Wed.
    pd, s = resolve_dates(_et(2026, 6, 16, 18), D(2026, 6, 16))
    assert pd == D(2026, 6, 16)
    assert s == D(2026, 6, 17)


def test_delayed_run_after_midnight_yields_the_same_snapshot():
    # The same job, delayed past midnight into Wed 01:30 ET: today's (Wed) close
    # is not in yet, so it still prices Tue -> session Wed. Identical to the
    # evening result, so GitHub's delay never changes the answer.
    pd, s = resolve_dates(_et(2026, 6, 17, 1), D(2026, 6, 16))
    assert pd == D(2026, 6, 16)
    assert s == D(2026, 6, 17)


def test_never_uses_an_intraday_same_day_close_before_the_close():
    # Wed 14:00 ET (before the close): even if a feed posts a provisional "today"
    # candle, price_date stays the prior completed session, session = today.
    pd, s = resolve_dates(_et(2026, 6, 17, 14), D(2026, 6, 17))  # provisional Wed
    assert pd == D(2026, 6, 16)  # Tue, not the intraday Wed
    assert s == D(2026, 6, 17)


def test_evening_degrades_when_todays_close_not_posted_yet():
    # Tue 18:30 ET but the feed has not posted Tue's close yet (only Mon): don't
    # invent it -- price Mon, session Tue (advances next run once Tue posts).
    pd, s = resolve_dates(_et(2026, 6, 16, 18), D(2026, 6, 15))
    assert pd == D(2026, 6, 15)
    assert s == D(2026, 6, 16)


def test_friday_evening_builds_monday_off_friday():
    pd, s = resolve_dates(_et(2026, 6, 19, 18), D(2026, 6, 19))  # Fri evening
    assert pd == D(2026, 6, 19)
    assert s == D(2026, 6, 22)  # Monday


def test_saturday_run_builds_monday_off_friday():
    # Not the 6/19-6/20 weekend: 2026-06-19 is Juneteenth (an exchange
    # holiday), which would make Thursday 6/18 the actual last close.
    pd, s = resolve_dates(_et(2026, 6, 13, 10), D(2026, 6, 12))  # Sat
    assert pd == D(2026, 6, 12)
    assert s == D(2026, 6, 15)


def test_explicit_price_date_backfill_derives_session():
    pd, s = resolve_dates(_et(2026, 6, 18, 22), D(2026, 6, 17), price_date=D(2026, 6, 3))
    assert pd == D(2026, 6, 3)
    assert s == D(2026, 6, 4)  # next weekday after the backfilled close


def test_explicit_session_override_is_honoured():
    _, s = resolve_dates(_et(2026, 6, 18, 22), D(2026, 6, 17), session=D(2026, 7, 1))
    assert s == D(2026, 7, 1)


def test_offset_log_upserts_by_date(tmp_path):
    log = tmp_path / "offset_history.jsonl"
    base = {"ok": True, "price_date": "2026-06-16", "days_to_expiry": 94,
            "turn_session": False, "fair_value_premium": 68.6, "observed_basis": 72.2,
            "rate_pct": 4.77, "spot": 7554.3}
    build_fairvalue._append_offset_record(base, log)
    # same date again (e.g. the backup evening run) -> overwrite, not duplicate
    build_fairvalue._append_offset_record(dict(base, fair_value_premium=68.9), log)
    # a later date -> appended, kept sorted
    build_fairvalue._append_offset_record(
        dict(base, price_date="2026-06-17", fair_value_premium=70.8), log)
    rows = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert [r["date"] for r in rows] == ["2026-06-16", "2026-06-17"]
    assert rows[0]["model_offset"] == 68.9  # overwritten, not duplicated

    # a failed snapshot, or one with no observed future, is skipped
    build_fairvalue._append_offset_record({"ok": False}, log)
    build_fairvalue._append_offset_record({"ok": True, "observed_basis": None}, log)
    rows2 = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    assert len(rows2) == 2
