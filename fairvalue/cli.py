"""Command-line interface: compute fair value for a date.

Works offline with manual inputs:

    python -m fairvalue --date 2024-04-15 --index 5061.82 \
        --rate-percent 5.33 --dividends 8.1 --futures 5071.00

Or, once the data hosts are on the network allowlist, fill index/rate
automatically with ``--fetch`` (FRED rates + Yahoo prices).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from .calculator import FairValueReport, compute_fair_value
from .core import DEFAULT_DAYS_PER_YEAR


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fairvalue",
        description="Compute SPX vs ES futures fair value for a date.",
    )
    p.add_argument("--date", type=_date, default=dt.date.today(),
                   help="valuation date YYYY-MM-DD (default: today)")
    p.add_argument("--index", type=float, help="index level (e.g. SPX close)")
    rate = p.add_mutually_exclusive_group()
    rate.add_argument("--rate", type=float, help="annual interest rate as a decimal, e.g. 0.0533")
    rate.add_argument("--rate-percent", type=float, help="annual interest rate in percent, e.g. 5.33")
    p.add_argument("--dividends", type=float, default=None,
                   help="dividend points over the contract life "
                        "(default: 0, or fetched when --fetch is set)")
    p.add_argument("--expiry", type=_date,
                   help="override contract expiry YYYY-MM-DD (default: nearest 3rd Friday)")
    p.add_argument("--futures", type=float, help="observed futures price, for basis/mispricing")
    p.add_argument("--days-per-year", type=float, default=DEFAULT_DAYS_PER_YEAR,
                   help="day-count basis (default: 365)")
    p.add_argument("--root", default="ES", help="contract root for the symbol label (default: ES)")
    p.add_argument("--fetch", action="store_true",
                   help="auto-fill missing index/rate/dividends from FRED + Yahoo "
                        "(needs network allowlist)")
    p.add_argument("--session", action="store_true",
                   help="print both active quarterly contracts (front + next), "
                        "fetching all inputs (needs network allowlist)")
    p.add_argument("--implied-repo", action="store_true",
                   help="back the financing rate out of the live front future "
                        "(ES=F, or --futures) instead of sourcing a rate; the "
                        "fair value premium then equals the futures basis "
                        "(needs network allowlist)")
    p.add_argument("--deferred-repo", action="store_true",
                   help="price the FRONT using the funding rate implied by the "
                        "next (deferred) contract -- independent of the front, so "
                        "the basis vs fair value is a real rich/cheap signal "
                        "(needs network allowlist)")
    p.add_argument("--funding-spread-bps", type=float, default=0.0,
                   help="optional financing spread in basis points added to the "
                        "fetched risk-free T-bill rate (default: 0). Only affects "
                        "--fetch / --session; --implied-repo sources the funding "
                        "rate from the future itself.")
    p.add_argument("--prior-close", action="store_true",
                   help="price off the PRIOR session's close (indexarb's overnight "
                        "convention: the session-D fair value uses the D-1 close as "
                        "spot, days/dividends still from D). Affects --implied-repo "
                        "/ --deferred-repo.")
    return p


def _resolve_rate(ns: argparse.Namespace) -> float | None:
    if ns.rate is not None:
        return ns.rate
    if ns.rate_percent is not None:
        return ns.rate_percent / 100.0
    return None


def _prior_close_date(ns: argparse.Namespace) -> dt.date | None:
    """Prior-calendar-day for --prior-close (close_on_or_before handles weekends)."""
    return ns.date - dt.timedelta(days=1) if ns.prior_close else None


def compute_from_namespace(ns: argparse.Namespace) -> FairValueReport:
    """Build a report from parsed args, fetching only if ``--fetch`` is set."""
    index = ns.index
    rate = _resolve_rate(ns)
    dividends = ns.dividends

    if ns.fetch:
        index, rate, dividends = _autofill(ns, index, rate, dividends)

    if index is None:
        raise SystemExit("error: --index is required (or use --fetch)")
    if rate is None:
        raise SystemExit("error: provide --rate or --rate-percent (or use --fetch)")

    return compute_fair_value(
        as_of=ns.date,
        index_value=index,
        annual_rate=rate,
        dividend_points=0.0 if dividends is None else dividends,
        expiry=ns.expiry,
        futures_price=ns.futures,
        days_per_year=ns.days_per_year,
        root=ns.root,
    )


def _autofill(ns, index, rate, dividends):  # pragma: no cover - needs network
    from .calendar import days_to_expiry, next_quarterly_settlement
    from .providers.fred import FredRateProvider
    from .providers.total_return import TotalReturnDividendProvider
    from .providers.yahoo import SPX, YahooPriceProvider

    try:
        expiry = ns.expiry or next_quarterly_settlement(ns.date, on_or_after=True)
        days = days_to_expiry(ns.date, expiry)
        if index is None:
            index = YahooPriceProvider().close(SPX, ns.date)
        if rate is None:
            rate = FredRateProvider(
                funding_spread=ns.funding_spread_bps / 10000.0
            ).zero_rate(ns.date, days)
        if dividends is None:
            dividends = TotalReturnDividendProvider().dividend_points(
                ns.date, expiry, index
            )
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        raise SystemExit(
            f"error: --fetch failed ({exc}). Are the data hosts on the network "
            "allowlist (fred.stlouisfed.org, query1/2.finance.yahoo.com)?"
        ) from exc
    return index, rate, dividends


def _run_session(ns):  # pragma: no cover - needs network
    from .providers.fred import FredRateProvider
    from .providers.total_return import TotalReturnDividendProvider
    from .providers.yahoo import YahooPriceProvider
    from .session import compute_session

    try:
        return compute_session(
            ns.date, YahooPriceProvider(),
            FredRateProvider(funding_spread=ns.funding_spread_bps / 10000.0),
            TotalReturnDividendProvider(), days_per_year=ns.days_per_year, root=ns.root,
        )
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        raise SystemExit(
            f"error: --session failed ({exc}). Are the data hosts on the network "
            "allowlist (fred.stlouisfed.org, query1/2.finance.yahoo.com)?"
        ) from exc


def _run_implied_repo(ns):  # pragma: no cover - needs network
    from .providers.total_return import TotalReturnDividendProvider
    from .providers.yahoo import YahooPriceProvider
    from .session import compute_implied_repo

    try:
        return compute_implied_repo(
            ns.date, YahooPriceProvider(), TotalReturnDividendProvider(),
            futures_price=ns.futures, expiry=ns.expiry,
            price_date=_prior_close_date(ns),
            days_per_year=ns.days_per_year, root=ns.root,
        )
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        raise SystemExit(
            f"error: --implied-repo failed ({exc}). Are the data hosts on the "
            "network allowlist (query1/2.finance.yahoo.com)?"
        ) from exc


def _run_deferred_repo(ns):  # pragma: no cover - needs network
    from .providers.total_return import TotalReturnDividendProvider
    from .providers.yahoo import YahooPriceProvider
    from .session import compute_with_deferred_repo

    try:
        return compute_with_deferred_repo(
            ns.date, YahooPriceProvider(), TotalReturnDividendProvider(),
            front_futures=ns.futures, price_date=_prior_close_date(ns),
            days_per_year=ns.days_per_year, root=ns.root,
        )
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        raise SystemExit(
            f"error: --deferred-repo failed ({exc}). Are the data hosts on the "
            "network allowlist (query1/2.finance.yahoo.com)?"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.session:
        for report in _run_session(ns):
            print(report)
            print()
        return 0
    if ns.implied_repo:
        print("Implied-repo fair value (rate backed out of the front future; "
              "premium = basis, so the future is fair against itself):\n")
        print(_run_implied_repo(ns))
        return 0
    if ns.deferred_repo:
        print("Front fair value priced with the next contract's implied funding "
              "rate (independent of the front -> basis vs fair value is a real "
              "rich/cheap signal):\n")
        print(_run_deferred_repo(ns))
        return 0
    report = compute_from_namespace(ns)
    print(report)
    if ns.dividends is None and not ns.fetch:
        print("\nnote: dividend points defaulted to 0 -- pass --dividends or use "
              "--fetch for an accurate premium.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
