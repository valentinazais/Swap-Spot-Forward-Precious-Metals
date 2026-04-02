"""
data.py — Market data fetching for precious metals dashboard.
Sources: yfinance for spots/FX/yields, LBMA scraping for fixings.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import streamlit as st


# ── Ticker maps ──────────────────────────────────────────────────────────────

METAL_TICKERS = {
    "XAU": "GC=F",
    "XAG": "SI=F",
    "XPT": "PL=F",
    "XPD": "PA=F",
}

METAL_NAMES = {
    "XAU": "Gold",
    "XAG": "Silver",
    "XPT": "Platinum",
    "XPD": "Palladium",
}

CURRENCIES = ["USD", "EUR", "GBP", "CHF", "JPY"]

# Each ticker gives: how many USD per 1 unit of that currency
# price_in_CCY = price_USD / rate
FX_TICKERS = {
    "EUR": "EURUSD=X",   # USD per 1 EUR
    "GBP": "GBPUSD=X",   # USD per 1 GBP
    "CHF": "USDCHF=X",   # CHF per 1 USD  → invert
    "JPY": "USDJPY=X",   # JPY per 1 USD  → invert
}

# Tickers that are quoted as USD per foreign (need NO inversion)
FX_NO_INVERT = {"EUR", "GBP"}
# Tickers quoted as foreign per USD (need inversion)
FX_INVERT = {"CHF", "JPY"}

# Standard maturities for forward pricing
MATURITIES = {
    "1W": 7 / 365,
    "1M": 30 / 365,
    "2M": 60 / 365,
    "3M": 90 / 365,
    "6M": 180 / 365,
    "1Y": 1.0,
}

# US Treasury CMT column names → (tenor label, years fraction)
# Source: https://home.treasury.gov (no API key required)
TREASURY_COL_MAP = {
    "1 Mo":  ("1M",  1 / 12),
    "2 Mo":  ("2M",  2 / 12),
    "3 Mo":  ("3M",  3 / 12),
    "4 Mo":  ("4M",  4 / 12),
    "6 Mo":  ("6M",  6 / 12),
    "1 Yr":  ("1Y",  1.0),
    "2 Yr":  ("2Y",  2.0),
    "3 Yr":  ("3Y",  3.0),
    "5 Yr":  ("5Y",  5.0),
    "7 Yr":  ("7Y",  7.0),
    "10 Yr": ("10Y", 10.0),
    "20 Yr": ("20Y", 20.0),
    "30 Yr": ("30Y", 30.0),
}


# ── Spot prices ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_spot_prices() -> pd.DataFrame:
    """Fetch current spot prices for all metals in USD."""
    rows = []
    for metal, ticker in METAL_TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.get("lastPrice", None) or info.get("previousClose", None)
            prev = info.get("previousClose", None)
            change = price - prev if (price and prev) else None
            pct = (change / prev * 100) if (change and prev) else None
            rows.append({
                "Metal": metal,
                "Name": METAL_NAMES[metal],
                "Spot (USD)": round(price, 2) if price else None,
                "Chg": round(change, 2) if change else None,
                "Chg %": round(pct, 2) if pct else None,
            })
        except Exception:
            rows.append({
                "Metal": metal,
                "Name": METAL_NAMES[metal],
                "Spot (USD)": None,
                "Chg": None,
                "Chg %": None,
            })
    return pd.DataFrame(rows)


# ── FX rates ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_fx_rates() -> dict:
    """
    Returns dict {ccy: usd_per_ccy} where usd_per_ccy = how many USD for 1 unit of ccy.
    price_in_ccy = price_usd / usd_per_ccy
    USD = 1.0 (trivially).
    """
    rates: dict[str, float | None] = {"USD": 1.0}
    for ccy, ticker in FX_TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            raw = info.get("lastPrice", None) or info.get("previousClose", None)
            if raw and raw > 0:
                if ccy in FX_INVERT:
                    # ticker is foreignPerUSD → usd_per_ccy = 1/raw
                    rates[ccy] = 1.0 / raw
                else:
                    # ticker is usdPerForeign → usd_per_ccy = raw
                    rates[ccy] = raw
            else:
                rates[ccy] = None
        except Exception:
            rates[ccy] = None
    return rates


def get_spot_in_currency(metal: str, currency: str) -> float | None:
    """
    Return the spot price of a metal in the requested currency.
    Applies FX conversion: price_ccy = price_usd / usd_per_ccy.
    """
    spots = get_spot_prices()
    try:
        usd_price = float(spots.loc[spots["Metal"] == metal, "Spot (USD)"].values[0])
    except Exception:
        return None
    if currency == "USD":
        return usd_price
    fx = get_fx_rates()
    rate = fx.get(currency)
    if rate and rate > 0:
        return round(usd_price / rate, 2)
    return usd_price  # fallback to USD if FX unavailable



# ── USD Yield Curve (US Treasury CMT) ───────────────────────────────────────

# Years fractions for all known tenors (used for interpolation)
_TENOR_YEARS: dict[str, float] = {
    "1W": 7 / 365,
    "1M": 1 / 12,  "2M": 2 / 12,  "3M": 3 / 12,  "4M": 4 / 12,
    "6M": 6 / 12,
    "1Y": 1.0,  "2Y": 2.0,  "3Y": 3.0,  "5Y": 5.0,
    "7Y": 7.0,  "10Y": 10.0,  "20Y": 20.0,  "30Y": 30.0,
}


@st.cache_data(ttl=300)
def get_usd_yield_curve() -> pd.DataFrame:
    """
    Fetch US Treasury Constant Maturity (CMT) yield curve directly from
    treasury.gov — 13 real tenors, no API key required.
    Returns DataFrame with columns: Tenor, Years, Rate (%).
    """
    year = datetime.now().year
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/"
        f"interest-rates/daily-treasury-rates.csv/{year}/all"
        f"?type=daily_treasury_yield_curve&field_tdr_date_value={year}&download=true"
    )
    try:
        df_raw = pd.read_csv(url)
        # Most recent non-empty row
        latest = df_raw.dropna(how="all").iloc[-1]
        rows = []
        for col, (tenor, years) in TREASURY_COL_MAP.items():
            if col in df_raw.columns:
                val = latest[col]
                if pd.notna(val):
                    rows.append({
                        "Tenor": tenor,
                        "Years": round(years, 6),
                        "Rate (%)": round(float(val), 4),
                    })
        if rows:
            return pd.DataFrame(rows).sort_values("Years").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame(columns=["Tenor", "Years", "Rate (%)"])


def get_rate_for_tenor(tenor: str) -> float | None:
    """
    Return the CMT rate for a tenor string.
    If the tenor is not directly available (e.g. 1W), interpolate from the curve.
    """
    curve = get_usd_yield_curve()
    if curve.empty:
        return None
    # Direct match
    match = curve.loc[curve["Tenor"] == tenor, "Rate (%)"]
    if not match.empty:
        return float(match.values[0])
    # Interpolate using known years fraction
    if tenor in _TENOR_YEARS:
        years = _TENOR_YEARS[tenor]
        rate = np.interp(years, curve["Years"].values, curve["Rate (%)"].values)
        return round(float(rate), 4)
    return None
