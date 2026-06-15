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
print(mispricing(5101.0, result.fair_value_price))  # observed future rich/cheap
```

Convert a raw cash-dividend sum to index points with
`dividend_points_from_cash(cash_sum, divisor)`. Back out market-implied inputs
with `implied_rate(...)` and `implied_dividend_points(...)`.

### Command line

Compute a session from manual inputs (works offline):

```bash
python -m fairvalue --date 2024-04-15 --index 5061.82 \
    --rate-percent 5.33 --dividends 8.1 --futures 5101.00
```

```
Fair value for 2024-04-15  ->  ESM24 (exp 2024-06-21, 67 days)
  index level         : 5061.82
  interest rate        : 5.330%
  interest component   : +48.48
  dividend component   : +8.10  (points: 8.10)
  --------------------------------------------
  FAIR VALUE (premium) : +40.38
  fair value price     : 5102.20
  observed future      : 5101.00
  observed basis       : +39.18
  vs fair value        : -1.20 (cheap)
```

Add `--fetch` to auto-fill the index and rate from Yahoo Finance + FRED (needs
those hosts on the network allowlist; see below).

## Status / roadmap

- [x] Core fair value math (`fairvalue.core`) — pure, unit-tested.
- [x] Quarterly expiration calendar (`fairvalue.calendar`).
- [x] High-level calculator + CLI (`fairvalue.calculator`, `fairvalue.cli`).
- [x] Data providers (`fairvalue.providers`): FRED rates, Yahoo prices,
      dividend estimators — parsing/interpolation unit-tested offline; live
      fetch pending network allowlist.
- [ ] Historical-session validation against published fair value numbers.

### Data sources & network access

Inputs and the free source each uses:

| Input              | Source                          | Notes                                            |
| ------------------ | ------------------------------- | ------------------------------------------------ |
| Index (SPX)        | Yahoo `^GSPC`                   | long daily history                               |
| Futures (ES)       | Yahoo `ES=F`                    | continuous front-month, recent years only        |
| Interest rate      | FRED `DGS1MO/3MO/6MO/1`         | T-bill CMT, interpolated to exact days           |
| Dividends          | manual / yield estimate         | no clean free feed; see `providers.dividends`    |

Live auto-fetch needs these hosts on the environment's **network allowlist**
(egress is restricted by default): `fred.stlouisfed.org`,
`query1.finance.yahoo.com`, `query2.finance.yahoo.com`. Until then, pass inputs
manually (the CLI and `compute_fair_value` work fully offline). The live
providers each accept an injectable `opener`, so their logic stays unit-tested
without a network. Changing the allowlist takes effect in a **new** session.

## Development

```bash
pip install -e ".[dev]"
pytest
```
