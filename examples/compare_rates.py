import datetime as dt
import sys
import pathlib

# Ensure we can import fairvalue
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fairvalue.providers.yahoo import YahooPriceProvider, ES_FRONT
from fairvalue.providers.total_return import TotalReturnDividendProvider
from fairvalue.providers.fred import FredSOFRProvider, FredRateProvider
from fairvalue.session import compute_with_deferred_repo, compute_fair_value
from fairvalue.calendar import next_quarterly_settlement, front_settlement
from web.build_fairvalue import _now_et, _latest_common_close, resolve_dates

def main():
    price_provider = YahooPriceProvider()
    div_provider = TotalReturnDividendProvider()
    sofr_provider = FredSOFRProvider() # No funding spread for pure SOFR
    shape_provider = FredRateProvider()

    now_et = _now_et()
    price_date, session = resolve_dates(
        now_et, _latest_common_close(price_provider, now_et.date())
    )

    # 1. Implied Repo without shaping
    implied_report = compute_with_deferred_repo(session, price_provider, div_provider, price_date=price_date)
    
    # 1b. Implied Repo with shaping
    shaped_report = compute_with_deferred_repo(session, price_provider, div_provider, price_date=price_date, shape_provider=shape_provider)
    
    # 2. SOFR
    # We need to get the index value and front futures price
    index_val = price_provider.close("^GSPC", price_date)
    front_expiry = front_settlement(session)
    
    # Calculate SOFR rate for the days to expiry
    days = implied_report.days_to_expiry
    # FredRateProvider zero_rate takes as_of and days_to_expiry
    sofr_rate = sofr_provider.zero_rate(session, days)

    # Compute Fair Value using SOFR
    # To do this, we need the dividend points for the front contract
    front_div = div_provider.dividend_points(session, front_expiry, index_val)
    
    sofr_report = compute_fair_value(
        session, index_val, sofr_rate, front_div, expiry=front_expiry,
        futures_price=implied_report.futures_price, # passing the observed futures
    )

    print(f"--- Porównanie Stóp Procentowych (Sesja: {session}) ---")
    print(f"Implied Repo Rate (Płaska krzywa): {implied_report.annual_rate * 100:.3f}%")
    print(f"Implied Repo Rate (Kształtowana):  {shaped_report.annual_rate * 100:.3f}%  (Korekta: {shaped_report.curve_shape_adjustment * 100:.3f} p.p.)")
    print(f"SOFR Rate (z Fed):                 {sofr_rate * 100:.3f}%")
    print(f"Różnica (Kształtowana vs SOFR):    {abs(shaped_report.annual_rate - sofr_rate) * 100:.3f} p.p.\n")
    
    print(f"--- Porównanie Fair Value ---")
    print(f"Fair Value (Płaska krzywa) : {implied_report.fair_value_price:.2f}")
    print(f"Fair Value (Kształtowana)  : {shaped_report.fair_value_price:.2f}")
    print(f"Fair Value (SOFR)          : {sofr_report.fair_value_price:.2f}")
    print(f"Różnica w wycenie (Płaska vs Kształtowana): {implied_report.fair_value_price - shaped_report.fair_value_price:.2f} punktów")

if __name__ == "__main__":
    main()
