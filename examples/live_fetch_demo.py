"""Exercise the autonomous live data fetch end-to-end (no manual inputs).

Run:  python examples/live_fetch_demo.py [YYYY-MM-DD]

Unlike ``reproduce_indexarb.py`` (which feeds fixed historical inputs), this
script fetches *every* input live and prints the full session, so it doubles as
a smoke test that the network allowlist is in place:

  * index level   -- Yahoo ``^GSPC``
  * interest rate  -- FRED T-bill CMT, interpolated to each contract's horizon
  * dividends      -- seasonal total-return estimate (``^SP500TR`` vs ``^GSPC``)

The free stand-ins are a close, defensible estimate -- not a bit-identical copy
of indexarb's proprietary curve + dividend database (see README). Needs these
hosts on the network allowlist: ``fred.stlouisfed.org``,
``query1.finance.yahoo.com``, ``query2.finance.yahoo.com``. Exit code is 0 on a
successful fetch, 1 if the network/allowlist is unavailable.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue import compute_session  # noqa: E402
from fairvalue.calendar import days_to_expiry, next_quarterly_settlement  # noqa: E402
from fairvalue.providers.fred import FredRateProvider  # noqa: E402
from fairvalue.providers.total_return import TotalReturnDividendProvider  # noqa: E402
from fairvalue.providers.yahoo import SPX, YahooPriceProvider  # noqa: E402

ALLOWLIST_HINT = (
    "Could not fetch live data. Are these hosts on the environment's network "
    "allowlist?\n  - fred.stlouisfed.org\n  - query1.finance.yahoo.com\n"
    "  - query2.finance.yahoo.com\n(Allowlist changes take effect in a NEW session.)"
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    as_of = dt.date.fromisoformat(argv[0]) if argv else dt.date.today()

    price = YahooPriceProvider()
    rate = FredRateProvider()
    divs = TotalReturnDividendProvider()

    try:
        # Show each input source explicitly before the orchestrated session.
        front_expiry = next_quarterly_settlement(as_of, on_or_after=True)
        front_days = days_to_expiry(as_of, front_expiry)
        spot = price.close(SPX, as_of)
        front_rate = rate.zero_rate(as_of, front_days)

        print(f"Live autonomous fetch for {as_of}")
        print(f"  Yahoo  ^GSPC close          : {spot:.2f}")
        print(f"  FRED   {front_days}d interpolated rate : {front_rate * 100:.4f}%")
        print(f"  next settlement              : {front_expiry} ({front_days} days)\n")

        reports = compute_session(as_of, price, rate, divs)
    except Exception as exc:  # noqa: BLE001 - this script *is* the network check
        print(f"FETCH FAILED: {exc}\n", file=sys.stderr)
        print(ALLOWLIST_HINT, file=sys.stderr)
        return 1

    for report in reports:
        print(report)
        print()
    print("LIVE FETCH OK -- all inputs sourced from the network.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
