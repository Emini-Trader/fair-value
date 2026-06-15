# fairvalue — SPX vs ES futures fair value

Reproduces the **fair value** of S&P 500 futures: the difference, on a given
date, between the cash index (SPX) and its futures contract (the CME E-mini,
ES). Built as a small, dependency-free Python core plus (optional) data
providers.

## What "fair value" means

There is no regulatory definition, but consensus usage is:

- **Fair value** — the price of the futures contract when it is correctly
  priced relative to the underlying index. If SPX were `1000`, a plausible
  fair value for the future would be `1003.46`.
- **Fair value premium** — the *difference* between that fair value and the
  index: `1003.46 − 1000 = 3.46`.
- Colloquially (CNBC, the financial press, etc.) "fair value premium" is
  shortened to just **"fair value"**, i.e. the `3.46`, not the `1003.46`.

This project follows the colloquial usage: `fair_value_premium` is the
`3.46`-style number, and `fair_value_price` is the full `1003.46`-style
number. Both are always returned, so there is no ambiguity.

## The equation

Fair value = the interest that could be earned on the index over the life of
the future (the *cost of carry*) **minus** the stock dividends paid during that
period (divisor-adjusted):

```
FV_premium = Index × [ (1 + r) ^ (days / 365) − 1 ]  −  (Σ dividends) / divisor
FV_price   = Index + FV_premium
```

| Symbol            | Meaning                                                                 |
| ----------------- | ----------------------------------------------------------------------- |
| `Index`           | current index level (e.g. SPX close)                                    |
| `r`               | annualised interest rate for the exact days remaining (from a yield curve) |
| `days`            | calendar days from the valuation date to futures settlement (3rd Friday) |
| `Σ dividends`     | dividends with ex-date during the remaining life of the contract        |
| `divisor`         | the S&P 500 index divisor (converts cash dividends to index points)     |

Notes that match the reference methodology:

- **Interest / cost of carry** is based on a zero-coupon yield curve (built
  from deposit rates and short-term-rate futures), interpolated to the exact
  number of days remaining. A short T-bill / SOFR rate is a practical modern
  proxy.
- **Dividends** use actually declared or forecast cash amounts (not yields)
  whose ex-date falls in the remaining life of the contract, normalised by the
  index divisor. This is more accurate — and more *seasonal* — than a flat
  dividend-yield approximation.
- **Slippage and friction are intentionally omitted** (arbitrage desks
  minimise both).

### Modeling conventions used here

- Day count is **ACT/365 fixed**, exactly as written in the reference equation
  (`days / 365`). Configurable via `days_per_year`.
- Interest uses **annual compounding** `(1 + r) ^ (days/365)`. For a sub-year
  horizon this sits slightly *below* simple interest `r · days/365` (the curve
  is convex in time) and below continuous compounding `e^(r·days/365)`.
- Settlement date is the **third Friday** of Mar/Jun/Sep/Dec (the SOQ date).

## Usage

```python
from fairvalue import fair_value, dividend_points_from_cash, mispricing
from fairvalue.calendar import next_quarterly_expiration, days_to_expiry
import datetime as dt

as_of  = dt.date(2024, 4, 15)
expiry = next_quarterly_expiration(as_of)          # 2024-06-21
days   = days_to_expiry(as_of, expiry)             # 67

result = fair_value(
    index_value=5061.82,        # SPX close
    annual_rate=0.0533,         # ~ interpolated short rate
    days_to_expiry=days,
    dividend_points=8.1,        # divisor-adjusted dividends over the period
)

print(result.fair_value_premium)   # the colloquial "fair value"
print(result.fair_value_price)     # full theoretical futures price
print(mispricing(5071.0, result.fair_value_price))  # observed future rich/cheap
```

Convert a raw cash-dividend sum to index points with
`dividend_points_from_cash(cash_sum, divisor)`. Back out market-implied inputs
with `implied_rate(...)` and `implied_dividend_points(...)`.

## Status / roadmap

- [x] Core fair value math (`fairvalue.core`) — pure, unit-tested.
- [x] Quarterly expiration calendar (`fairvalue.calendar`).
- [ ] Data providers (SPX / ES prices, interest rates, dividends) — see below.
- [ ] Historical-session validation against published fair value numbers.

### Data sources & network access

Live "auto-fetch" of market data needs outbound access to data hosts. In a
restricted environment only an allow-listed set of hosts is reachable; the
common free sources (Yahoo Finance, FRED, Stooq, CBOE) may be blocked and need
to be added to the environment's network egress settings. Providers are written
behind a small interface so they can fall back to local CSV files when live
fetch is unavailable.

## Development

```bash
pip install -e ".[dev]"
pytest
```
