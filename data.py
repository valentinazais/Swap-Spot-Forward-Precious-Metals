"""
data.py — Market data fetching for precious metals dashboard.
Sources: yfinance for spots/FX/yields, LBMA scraping for fixings.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
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

# US Treasury tickers on yfinance for yield curve
YIELD_TICKERS = {
    "1M": "^IRX",   # 13-week T-bill (proxy)
    "3M": "^IRX",   # 13-week T-bill
    "6M": "^IRX",   # proxy
    "1Y": "^FVX",   # proxy
    "2Y": "^FVX",   # 5-year note (proxy)
    "5Y": "^FVX",
    "10Y": "^TNX",
    "30Y": "^TYX",
}

YIELD_TENORS = {
    "1M": 1 / 12,
    "3M": 3 / 12,
    "6M": 6 / 12,
    "1Y": 1.0,
    "2Y": 2.0,
    "5Y": 5.0,
    "10Y": 10.0,
    "30Y": 30.0,
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


# ── Ratios & spreads ─────────────────────────────────────────────────────────

def get_gold_silver_ratio(spots_df: pd.DataFrame) -> float | None:
    """Calculate XAU/XAG ratio."""
    try:
        xau = spots_df.loc[spots_df["Metal"] == "XAU", "Spot (USD)"].values[0]
        xag = spots_df.loc[spots_df["Metal"] == "XAG", "Spot (USD)"].values[0]
        if xau and xag:
            return round(xau / xag, 2)
    except Exception:
        pass
    return None


def get_pgm_spread(spots_df: pd.DataFrame) -> float | None:
    """Calculate XPT - XPD spread."""
    try:
        xpt = spots_df.loc[spots_df["Metal"] == "XPT", "Spot (USD)"].values[0]
        xpd = spots_df.loc[spots_df["Metal"] == "XPD", "Spot (USD)"].values[0]
        if xpt and xpd:
            return round(xpt - xpd, 2)
    except Exception:
        pass
    return None


# ── Gold/Silver ratio history ────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def get_ratio_history(period: str = "1y") -> pd.DataFrame:
    """Historical Gold/Silver ratio."""
    try:
        gold = yf.download("GC=F", period=period, interval="1d", progress=False)["Close"]
        silver = yf.download("SI=F", period=period, interval="1d", progress=False)["Close"]
        # Flatten if MultiIndex
        if isinstance(gold.columns, pd.MultiIndex):
            gold = gold.droplevel(level=1, axis=1)
        if isinstance(silver.columns, pd.MultiIndex):
            silver = silver.droplevel(level=1, axis=1)
        # Align
        df = pd.DataFrame({"Gold": gold.squeeze(), "Silver": silver.squeeze()}).dropna()
        df["Ratio"] = df["Gold"] / df["Silver"]
        return df[["Ratio"]]
    except Exception:
        return pd.DataFrame()


# ── LBMA Fixings ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def get_lbma_fixings() -> dict:
    """
    Fetch latest LBMA fixings.
    Falls back to placeholder if scraping fails.
    """
    fixings = {
        "Gold AM (USD)": None,
        "Gold PM (USD)": None,
        "Silver (USD)": None,
    }
    
    try:
        # Try LBMA gold price
        url = "https://www.lbma.org.uk/prices-and-data/precious-metal-prices#/table"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # LBMA uses JS-rendered tables, so scraping may not work
            # Fall through to yfinance fallback
    except Exception:
        pass
    
    # Fallback: use yfinance previous close as proxy
    try:
        t = yf.Ticker("GC=F")
        info = t.fast_info
        prev = info.get("previousClose", None)
        if prev:
            fixings["Gold AM (USD)"] = round(prev, 2)
            fixings["Gold PM (USD)"] = round(prev, 2)
    except Exception:
        pass
    
    try:
        t = yf.Ticker("SI=F")
        info = t.fast_info
        prev = info.get("previousClose", None)
        if prev:
            fixings["Silver (USD)"] = round(prev, 2)
    except Exception:
        pass
    
    return fixings


# ── USD Yield Curve ──────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_usd_yield_curve() -> pd.DataFrame:
    """
    Fetch USD yield curve from Treasury yields.
    Returns DataFrame with columns: Tenor, Years, Rate (%).
    """
    rows = []
    seen_tickers = set()
    
    for tenor, ticker in YIELD_TICKERS.items():
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            rate = info.get("lastPrice", None) or info.get("previousClose", None)
            if rate:
                rows.append({
                    "Ticker": ticker,
                    "Rate": rate,
                })
        except Exception:
            pass
    
    # Build a simple curve from what we have
    # Map actual tickers to approximate tenors
    curve_map = {
        "^IRX": [("3M", 0.25)],
        "^FVX": [("5Y", 5.0)],
        "^TNX": [("10Y", 10.0)],
        "^TYX": [("30Y", 30.0)],
    }
    
    curve_rows = []
    for r in rows:
        ticker = r["Ticker"]
        rate = r["Rate"]
        if ticker in curve_map:
            for tenor, years in curve_map[ticker]:
                curve_rows.append({
                    "Tenor": tenor,
                    "Years": years,
                    "Rate (%)": round(rate, 4),
                })
    
    # Interpolate missing standard tenors
    if curve_rows:
        df = pd.DataFrame(curve_rows).sort_values("Years").reset_index(drop=True)
        # Interpolate for standard maturities used in forward pricing
        standard_tenors = [
            ("1W", 7/365), ("1M", 1/12), ("2M", 2/12),
            ("3M", 3/12), ("6M", 6/12), ("1Y", 1.0),
        ]
        interp_rows = []
        for tenor, years in standard_tenors:
            rate = np.interp(years, df["Years"].values, df["Rate (%)"].values)
            interp_rows.append({
                "Tenor": tenor,
                "Years": round(years, 4),
                "Rate (%)": round(rate, 4),
            })
        return pd.DataFrame(interp_rows)
    
    return pd.DataFrame(columns=["Tenor", "Years", "Rate (%)"])


def get_rate_for_tenor(tenor: str) -> float | None:
    """Get interpolated USD rate for a given tenor string."""
    curve = get_usd_yield_curve()
    if curve.empty:
        return None
    match = curve.loc[curve["Tenor"] == tenor, "Rate (%)"]
    if not match.empty:
        return match.values[0]
    return None
