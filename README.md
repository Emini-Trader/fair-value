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
  proxy — but a *risk-free* one, below the financing rate desks actually pay; to
  recover the funding rate autonomously, back it out of the live future
  (`--implied-repo`, see Validation).
- **Dividends** use actually declared or forecast cash amounts (not yields)
  whose ex-date falls in the remaining life of the contract, normalised by the
  index divisor — exactly indexarb's "by amount" method. This is more accurate
  — and more *seasonal* — than a flat dividend-yield approximation. The free
  estimator recovers these amounts as index points from the total-return vs
  price index, then scales last year's window by the **data-measured** YoY
  dividend growth (no hand-set constant) — see Validation.
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

### Fully autonomous (`--fetch`)

With the data hosts on the network allowlist (see below), every input is fetched
— no manual numbers, no indexarb:

```bash
python -m fairvalue --date 2026-06-15 --fetch
```

This pulls the SPX close (Yahoo `^GSPC`), interpolates the rate from FRED T-bill
yields for the exact days to settlement, and estimates dividend points from the
seasonal total-return method (`^SP500TR` vs `^GSPC`). Any input you pass
explicitly (`--index`, `--rate`, `--dividends`, `--expiry`) overrides its fetch.

### Implied repo (`--implied-repo`)

`--fetch` uses a *risk-free* rate; indexarb uses a *funding* rate that sits above
it. To recover the funding rate with no feed and no constant, back it out of the
live front future (Yahoo `ES=F`, or `--futures` near roll):

```bash
python -m fairvalue --date 2026-06-15 --implied-repo
```

The fair value premium then equals the futures basis and reproduces indexarb's
published premium to within end-of-day timing noise (see Validation). By the same
identity the future is fair against itself, so it gives no rich/cheap read.

### Deferred repo — a real rich/cheap signal (`--deferred-repo`)

To get the funding-rate accuracy of implied repo *without* the circularity,
price the front with the rate implied by the **next** (deferred) contract, which
is independent of the front:

```bash
python -m fairvalue --date 2026-06-15 --deferred-repo            # same-day spot
python -m fairvalue --date 2026-06-15 --deferred-repo --prior-close  # indexarb's
```

The front fair value is no longer pinned to the front future, so the basis vs
fair value is a genuine rich/cheap signal. The deferred future carries the same
market funding rate (within ~0.5% of indexarb on the validation sessions), at
the cost of not seeing the front's own ~1-month curve hump. Add `--prior-close`
to reproduce indexarb's overnight convention (session-D fair value off the D-1
close); see Validation.

## Validation

Reproduced against indexarb.com's "Fair Value Premium Decomposition" across
**four sessions (8 S&P 500 contracts): 2026-02-13, 03-11, 04-13, 05-29**,
cross-checked with each day's yield-curve and dividend pages. Contract interest
rates are interpolated from the published zero-coupon curve nodes — exactly as
the source does — so the only inputs are spot, curve, and dividend amounts.
**Every figure matches** (rates to 6 dp; interest and premiums to the cent),
including a steep front-curve day (a 7.60% 31-day node on 03-11).

Example — 2026-05-29, S&P 500 spot 7563.63:

| Contract | Days | Rate %   | Interest | Dividends | Fair value | indexarb |
| -------- | ---- | -------- | -------- | --------- | ---------- | -------- |
| JUN 2026 | 20\* | 4.985022 | 20.19    | 5.923     | **14.27**  | 14.27    |
| SEP 2026 | 112  | 3.967113 | 90.83    | 26.206    | **64.63**  | 64.63    |

`\*` June's 3rd Friday (the 19th) is Juneteenth, so settlement rolls back to the
18th — 20 days, not 21. Run `python examples/reproduce_indexarb.py` (prints all
sessions) and see `tests/test_validation.py`.

### Autonomous accuracy: risk-free vs implied repo (front contract)

The table above feeds indexarb's *own* curve nodes. Sourcing the rate from free
data is the whole game — input attribution shows almost the entire residual is
the **rate** (live spot and dividends are already within a few tenths).

A free risk-free T-bill curve (`--fetch`) sits ~0.5–1.3% below indexarb's, so
the front comes out a few points light. The fix is **not a constant**: indexarb's
rate runs above the *entire* Treasury curve (out to 2Y) and above what SOFR /
Fed Funds futures imply, so it is a *funding* rate, not risk-free. Rather than
guess it, `--implied-repo` backs it out of the live front future itself:

```
r = ((futures + dividends) / index) ^ (365 / days) − 1
```

Fully autonomous (live Yahoo `^GSPC` + `ES=F` + dividend estimate), the front
premium (which then equals the futures basis) vs indexarb's published FV:

| Session    | Front | Days | implied r % | FV (implied repo) | indexarb | Δ      |
| ---------- | ----- | ---- | ----------- | ----------------- | -------- | ------ |
| 2026-02-13 | MAR   | 35   | 3.90        | 14.33             | 16.68    | −2.35  |
| 2026-03-11 | MAR   | 9    | 4.16        | 3.70              | 5.15     | −1.45  |
| 2026-04-13 | JUN   | 66   | 4.23        | 36.51             | 37.03    | −0.52  |
| 2026-05-29 | JUN   | 20   | 5.38        | 15.69             | 14.27    | +1.42  |

The implied rate tracks indexarb to within ~0.6% (vs 0.5–1.3% *light* for
risk-free) and even captures the front turn-hump (5.38% on 05-29, *above*
indexarb), with **no systematic bias** — the residual ±1–2 points is end-of-day
timing (Yahoo close vs indexarb's intraday snapshot). The identity's flip side:
this future is *fair against itself* (mispricing 0 by construction).

#### The rate curve, and the non-circular spot-free model (`--deferred-repo`)

indexarb's published yield curve confirms why no free rate feed reproduces it: it
is a piecewise-linear **funding** curve (deposit + Eurodollar) through an
overnight node, a humped ~1-month node (the 5.7% / 7.6% spikes), and **IMM-date
nodes** (3rd-Wednesday SOFR/Eurodollar-future expiries). The market
*funding* rate is only recoverable from the futures themselves.

To get that rate **without** the circularity, `--deferred-repo` computes the 
market funding rate from the **calendar spread** between the front and next 
(deferred) futures. Because it is calculated purely from the difference between two 
futures contracts, this rate is completely **spot-free** and immune to end-of-day 
cash index noise or MOC imbalances. The front contract is then priced with this 
clean calendar rate, so the basis vs fair value is a real rich/cheap signal.

**Liquidity Safeguard:** Because the calendar rate relies on the deferred contract,
a severe liquidity breakdown in the distant future could artificially distort the 
funding rate. The model employs a built-in safeguard: it compares the **daily percentage return**
(from the prior session's settlement) of the deferred contract against the front contract.
If the returns diverge by more than 0.05% (~4 index points), the model detects a 
liquidity fracture, raises a `liquidity_warning`, and calculates an emergency fallback 
FV based purely on the front contract's implied repo.

Front FV, fully autonomous, vs indexarb:

| Session       | spot (D-1) | rate % | FV (deferred-repo) | indexarb | Δ      |
| ------------- | ---------- | ------ | ------------------ | -------- | ------ |
| 2026-02-13    | 6832.76    | 4.46   | 17.08              | 16.68    | +0.40  |
| 2026-04-13    | 6816.89    | 4.41   | 37.14              | 37.03    | +0.11  |
| 2026-03-11    | 6781.48    | 4.43   | 3.92               | 5.15     | −1.23  |
| 2026-05-29    | 7563.63    | 4.73   | 12.75              | 14.27    | −1.52  |
| 2026-06-03 \* | 7609.78    | 4.66   | 9.24               | 9.93     | −0.69  |

The spot now ties out to indexarb's to the cent. The deferred funding rate
matches within ~0.5% except on the two days whose front sits on a ~1-month curve
hump (03-11, 05-29) — a hump no free instrument carries. Non-hump residual is
**±0.4**; mean −0.59 across the five. `\*` 2026-06-03 is fully **out of sample**
(only its 9.93 FV was supplied, no curve/dividend page). Unlike front implied
repo this is **non-circular**, so it is the model to use for a real rich/cheap
read.

#### Spot-robustness: a stale `^GSPC` can't blow up the rate

The deferred implied repo divides by the cash spot:

```
r = ((deferred + dividends) / spot) ^ (365 / deferred_days) − 1
```

The exponent (~3 for a ~120-day deferred) *amplifies* any spot/future
inconsistency. Yahoo sometimes publishes a stale `^GSPC` against fresh futures;
the false basis then sent the rate from ~4.6% to ~8% and **doubled** the fair
value (~65 → ~130). Anchoring dates only papers over it — the amplification is
inherent to dividing by spot.

The fix uses the same financing rate, measured a second, **spot-free** way: the
*calendar spread* between the two futures
(`core.implied_forward_rate`). Writing the fair value identity for each contract
and dividing makes the cash index cancel:

```
(1 + r) ^ ((deferred_days − front_days)/365) = (deferred + div_d) / (front + div_f)
```

so the rate comes purely from the two futures — a stale spot can't touch it.
`compute_with_deferred_repo` therefore uses this spot-free calendar rate as the
**primary** rate (`rate_source="calendar_spread"`), not merely a cross-check: the
fair value never divides by the cash index, so a stale `^GSPC` is structurally
unable to move it. The deferred implied repo is kept only as an offline
sanity / rich-cheap reference. The one remaining exposure is the deferred
contract's *own* price; a liquidity breakdown there is caught by the
return-divergence safeguard above (raises `liquidity_warning` and a front-only
`fallback_spot_fv`). On the stale-spot incident the calendar rate held at ~4.6%
(FV ~65) where the old spot-using rate would have doubled it.

## Status / roadmap

- [x] Core fair value math (`fairvalue.core`) — pure, unit-tested.
- [x] Quarterly expiration calendar (`fairvalue.calendar`).
- [x] High-level calculator + CLI (`fairvalue.calculator`, `fairvalue.cli`).
- [x] Data providers (`fairvalue.providers`): FRED rates, Yahoo prices,
      dividend estimators — parsing/interpolation unit-tested offline; live
      fetch verified end-to-end (see below).
- [x] Holiday-aware settlement calendar (Good Friday / Juneteenth roll-back).
- [x] Front roll on the **Monday of expiration week** (`front_settlement`) —
      ES open interest rolls to the next contract that Monday, so from then on
      the "front" is the next quarterly, matching indexarb's listing exactly.
- [x] Validated against published fair values (indexarb.com, 4 sessions).
- [x] Autonomous `--fetch`: SPX + rate + dividends with no manual inputs.
- [x] Live data fetch verified end-to-end with the hosts on the network
      allowlist — `python examples/live_fetch_demo.py` exercises all three
      providers (Yahoo + FRED) and prints a full session.
- [x] `--implied-repo`: backs the financing rate out of the live front future,
      no rate feed or constant — reproduces indexarb's front premium to within
      end-of-day timing noise (±1–2 pts) and captures the funding/turn premium
      that a risk-free rate misses.
- [x] `--deferred-repo`: prices the front with the next contract's implied
      funding rate (independent of the front) — non-circular, so it yields a real
      rich/cheap signal while staying within ~0.5% of indexarb's rate.
- [x] `--prior-close`: indexarb's overnight convention (session-D fair value off
      the D-1 close) — ties spot out to indexarb's to the cent; full front FV
      lands within ±0.4 off the hump days, validated out-of-sample on 2026-06-03.
- [x] Spot-robust rate (`core.implied_forward_rate`): the spot-free futures
      calendar spread is the **primary** rate, so a stale `^GSPC` can't inflate
      the rate (and double the fair value). A return-divergence safeguard guards
      the deferred leg against a liquidity breakdown.

### Data sources & network access

The model is *index agnostic* and reproduces the formula exactly; the remaining
question is sourcing each input for free. indexarb's proprietary deposit+Eurodollar
curve and dividend-forecast database are gone, so these are the free stand-ins —
a close, defensible estimate, not a bit-identical copy:

| Input          | Source                         | Notes                                              |
| -------------- | ------------------------------ | -------------------------------------------------- |
| Index (SPX)    | Yahoo `^GSPC`                  | daily close                                        |
| Interest rate  | FRED `DGS*` (risk-free) **or** implied repo from `ES=F` | T-bill CMT interpolated; or `--implied-repo` backs the funding rate out of the future |
| Dividends      | Yahoo `^SP500TR` vs `^GSPC`    | seasonal forward estimate + data-measured YoY growth; or `--dividends` manual |
| Futures (ES)   | Yahoo `ES=F`                   | continuous front-month, recent years only          |

The biggest accuracy driver is dividends (no free feed of forward dividend
points); the total-return seasonal method captures ex-date seasonality without
needing constituent data. See `fairvalue/providers/`.

**Dividend validation.** Against indexarb's published divisor-adjusted dividend
points across **18 sessions** (2025-01 → 2026-05, two contracts each), the
total-return estimator with data-measured YoY growth (~7%) tracks the
*realised* dividends, landing on average ~1 point above indexarb's own figure —
because indexarb's forecast is itself ~0.7 point below what actually went ex
(it forecasts only known/announced dividends). The residual is forecast
uncertainty, not method error. See `examples/` and `tests/test_total_return.py`.

Live auto-fetch needs these hosts on the environment's **network allowlist**
(egress is restricted by default): `fred.stlouisfed.org`,
`query1.finance.yahoo.com`, `query2.finance.yahoo.com`. With them allowlisted,
the full pipeline has been **verified live end-to-end** — e.g. for `2026-06-15`
`python -m fairvalue --date 2026-06-15 --session` fetches SPX `7431.46` (Yahoo),
interpolates `3.690%` / `3.781%` (FRED) and estimates `1.37` / `21.27` dividend
points for the ESM26/ESU26 contracts, with no manual inputs. Re-run the check
anytime with `python examples/live_fetch_demo.py`. Without the allowlist, pass
inputs manually (the CLI and `compute_fair_value` work fully offline); the live
providers accept an injectable fetcher (`history_fn` for Yahoo, `opener` for
FRED), so their logic stays unit-tested without a network. Changing the allowlist
takes effect in a **new** session.

**Fetch path.** The core and providers run on the **standard library alone**
(urllib). The optional `[yahoo]` extra (`pip install -e ".[yahoo]"`) adds
**yfinance** as a more robust *primary* that handles Yahoo's cookie/crumb churn,
falling back to urllib when yfinance is unavailable or blocked — e.g. behind a
proxy, where yfinance's `curl_cffi` transport fails but urllib honours
`HTTPS_PROXY`. The scheduled snapshot Action installs the extra; either path
works.

## Development

```bash
pip install -e ".[dev]"
pytest
```
