"""Tests for the command-line interface (manual / offline path)."""

import datetime as dt

import pytest

from fairvalue import cli


def _ns(args):
    return cli.build_parser().parse_args(args)


def test_manual_rate_decimal():
    ns = _ns(["--date", "2024-04-15", "--index", "5061.82", "--rate", "0.0533",
              "--dividends", "8.1"])
    report = cli.compute_from_namespace(ns)
    assert report.as_of == dt.date(2024, 4, 15)
    assert report.contract == "ESM24"
    assert report.fair_value_premium == pytest.approx(40.38, abs=0.1)


def test_rate_percent_is_converted():
    ns = _ns(["--index", "5000", "--rate-percent", "5.33"])
    report = cli.compute_from_namespace(ns)
    assert report.annual_rate == pytest.approx(0.0533)


def test_missing_index_errors():
    ns = _ns(["--rate", "0.05"])
    with pytest.raises(SystemExit):
        cli.compute_from_namespace(ns)


def test_missing_rate_errors():
    ns = _ns(["--index", "5000"])
    with pytest.raises(SystemExit):
        cli.compute_from_namespace(ns)


def test_main_prints_report(capsys):
    rc = cli.main(["--index", "5061.82", "--rate-percent", "5.33",
                   "--dividends", "8.1", "--date", "2024-04-15",
                   "--futures", "5101.0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FAIR VALUE (premium)" in out
    assert "ESM24" in out
