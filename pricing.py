"""
pricing.py — Forward and swap pricing for precious metals.
"""

import numpy as np
import pandas as pd


# ── Forward Pricing ──────────────────────────────────────────────────────────

def forward_price(spot: float, r: float, lease_rate: float, T: float) -> float:
    """
    Metal forward price.
    F = Spot × exp((r - lease_rate) × T)
    
    Args:
        spot: current spot price
        r: risk-free rate (annualized, as decimal e.g. 0.05 for 5%)
        lease_rate: metal lease rate (annualized, as decimal)
        T: time to maturity in years
    """
    return spot * np.exp((r - lease_rate) * T)


# ── Swap Pricing ─────────────────────────────────────────────────────────────

def price_swap(spot: float, r_pct: float, lease_pct: float,
               T_near: float, T_far: float,
               notional_oz: float, direction: str,
               swap_type: str = "spot-forward") -> dict:
    """
    Price a metal swap.
    
    Args:
        spot: spot price
        r_pct: USD rate in %
        lease_pct: lease rate in %
        T_near: near leg maturity in years (0 for spot leg)
        T_far: far leg maturity in years
        notional_oz: notional in troy ounces
        direction: "buy-sell" (buy near, sell far) or "sell-buy"
        swap_type: "spot-forward" or "forward-forward"
    
    Returns:
        dict with swap details
    """
    r = r_pct / 100
    lease = lease_pct / 100
    
    if swap_type == "spot-forward":
        near_price = spot
        T_near_actual = 0.0
    else:
        near_price = forward_price(spot, r, lease, T_near)
        T_near_actual = T_near
    
    far_price = forward_price(spot, r, lease, T_far)
    
    swap_pts = far_price - near_price
    carry_days = (T_far - T_near_actual) * 365
    
    # Cost of carry (annualized)
    if near_price > 0 and carry_days > 0:
        cost_of_carry = (swap_pts / near_price) * (365 / carry_days) * 100
    else:
        cost_of_carry = 0.0
    
    # Cash flows depend on direction
    if direction == "buy-sell":
        near_cf = -near_price * notional_oz  # pay near leg
        far_cf = far_price * notional_oz     # receive far leg
    else:  # sell-buy
        near_cf = near_price * notional_oz   # receive near leg
        far_cf = -far_price * notional_oz    # pay far leg
    
    net_cf = near_cf + far_cf
    
    return {
        "Swap Type": swap_type.replace("-", " → ").title(),
        "Direction": direction.upper(),
        "Near Leg Price": round(near_price, 4),
        "Far Leg Price": round(far_price, 4),
        "Swap Points": round(swap_pts, 4),
        "Cost of Carry (% ann.)": round(cost_of_carry, 4),
        "Near Leg CF (USD)": round(near_cf, 2),
        "Far Leg CF (USD)": round(far_cf, 2),
        "Net CF (USD)": round(net_cf, 2),
        "Notional (oz)": notional_oz,
    }
