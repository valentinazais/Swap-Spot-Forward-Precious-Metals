# Spot Forward Swap Pricer — run with: streamlit run app.py

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from data import (
    get_spot_prices,
    get_fx_rates,
    get_spot_in_currency,
    get_rate_for_tenor,
    MATURITIES,
    CURRENCIES,
)
from pricing import price_swap

# -- Page setup --

st.set_page_config(
    page_title="Spot Forward Swap Pricer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("Spot Forward Swap Pricer")

# -- Results container placed first so it renders above the inputs --
results_container = st.container()

if "sw_reset_counter" not in st.session_state:
    st.session_state.sw_reset_counter = 0
sw_rc = st.session_state.sw_reset_counter


st.markdown("#### Inputs")
sw_c1, sw_c2, sw_c3, sw_c4, sw_c5 = st.columns(5)
sw_metal = sw_c1.selectbox("Metal", ["XAU", "XAG", "XPT", "XPD"], key=f"sw_metal_{sw_rc}")
currency = sw_c2.selectbox("Currency", CURRENCIES, index=0, key=f"sw_ccy_{sw_rc}")
swap_type = sw_c3.selectbox("Type", ["spot-forward", "forward-forward"], key=f"sw_type_{sw_rc}")
direction = sw_c4.selectbox(
    "Direction", ["buy-sell", "sell-buy"],
    help="buy-sell: buy near leg, sell far leg", key=f"sw_dir_{sw_rc}",
)
notional = sw_c5.number_input(
    "Notional (oz)", value=100.0, min_value=0.1, format="%.2f", key=f"sw_notional_{sw_rc}",
)

mk_c1, mk_c2, mk_c3, mk_c4 = st.columns(4)

# Auto-fill spot in selected currency
sw_spot_default = 0.0
try:
    val = get_spot_in_currency(sw_metal, currency)
    if val:
        sw_spot_default = val
except Exception:
    pass

sw_spot = mk_c1.number_input(
    f"Spot ({currency})", value=sw_spot_default, format="%.2f", key=f"sw_spot_{sw_rc}_{sw_metal}_{currency}",
)

sw_rate_default = 4.5
try:
    r = get_rate_for_tenor("3M")
    if r:
        sw_rate_default = float(r)
except Exception:
    pass

sw_r_pct = mk_c2.number_input(
    "USD Rate (%)", value=sw_rate_default, format="%.4f", key=f"sw_rate_{sw_rc}",
)
sw_lease_pct = mk_c3.number_input(
    "Lease Rate (%)", value=0.5, format="%.4f", key=f"sw_lease_{sw_rc}",
)

mat_options = list(MATURITIES.keys())

if swap_type == "forward-forward":
    far_idx = min(4, len(mat_options) - 1)
    far_mat = mk_c4.selectbox(
        "Far Leg Maturity", mat_options,
        index=far_idx, key=f"sw_far_{sw_rc}",
    )
    T_far = MATURITIES[far_mat]

    # Near leg options: only maturities strictly shorter than the far leg
    near_options = [m for m in mat_options if MATURITIES[m] < T_far]
    if near_options:
        near_mat = st.selectbox(
            "Near Leg Maturity", near_options,
            index=len(near_options) - 1, key=f"sw_near_{sw_rc}",
            help="Near leg of the forward-forward swap (must settle before far leg)",
        )
        T_near = MATURITIES[near_mat]
    else:
        st.warning("No valid near leg — select a longer far leg maturity.")
        T_near = 0.0
else:
    far_idx = 3
    far_mat = mk_c4.selectbox(
        "Far Leg Maturity", mat_options,
        index=min(far_idx, len(mat_options) - 1), key=f"sw_far_{sw_rc}",
    )
    T_far = MATURITIES[far_mat]
    T_near = 0.0

# -- Show live FX rate for reference --
if currency != "USD":
    fx = get_fx_rates()
    rate_val = fx.get(currency)
    if rate_val:
        st.caption(f"FX: 1 {currency} = {rate_val:.4f} USD  |  1 USD = {1/rate_val:.4f} {currency}")

# -- Compute --

if sw_spot > 0:
    res = price_swap(
        sw_spot, sw_r_pct, sw_lease_pct,
        T_near, T_far, notional, direction, swap_type,
    )

    ccy_sym = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}.get(currency, "")

    # Fill results container at the top
    with results_container:
        m_c1, m_c2, m_c3, m_c4, m_c5 = st.columns([3, 3, 3, 1, 1])
        m_c1.metric("Swap Points", f"{res['Swap Points']:+,.4f}")
        m_c2.metric("Cost of Carry (annualized)", f"{res['Cost of Carry (% ann.)']:+.4f}%")
        m_c3.metric("Net Cash Flow", f"{ccy_sym}{res['Net CF (USD)']:+,.2f}")
        m_c4.markdown("&nbsp;")  # vertical spacer to align buttons with metrics
        if m_c4.button("Refresh", use_container_width=True):
            st.cache_data.clear()
        if m_c5.button("Reset Inputs", key="sw_reset", use_container_width=True):
            st.session_state.sw_reset_counter = sw_rc + 1
            st.rerun()

    # -- Charts --
    st.markdown("**Swap Points Term Structure**")

    mat_labels = list(MATURITIES.keys())
    mat_years = list(MATURITIES.values())

    if swap_type == "forward-forward":
        # Near leg forward price (fixed anchor)
        near_fwd = sw_spot * np.exp((sw_r_pct / 100 - sw_lease_pct / 100) * T_near)
        # Swap pts = F(bucket) - F(T_near) ; zero for buckets <= T_near
        swap_pts_term = [
            sw_spot * np.exp((sw_r_pct / 100 - sw_lease_pct / 100) * t) - near_fwd
            if t > T_near else 0.0
            for t in mat_years
        ]
        bar_colors = [
            ("#4CAF50" if v > 0 else "#F44336") if mat_years[i] > T_near else "rgba(120,120,120,0.35)"
            for i, v in enumerate(swap_pts_term)
        ]
        bar_title = f"Swap Points from {near_mat} ({currency}/oz)"
    else:
        swap_pts_term = [
            sw_spot * (np.exp((sw_r_pct / 100 - sw_lease_pct / 100) * t) - 1)
            for t in mat_years
        ]
        bar_colors = ["#4CAF50" if v >= 0 else "#F44336" for v in swap_pts_term]
        bar_title = f"Swap Points from Spot ({currency}/oz)"

    fig_term = go.Figure()
    fig_term.add_trace(go.Bar(
        x=mat_labels, y=swap_pts_term,
        marker_color=bar_colors,
        text=[f"{v:+.2f}" if abs(v) > 0 else "" for v in swap_pts_term],
        textposition="outside",
        name="Swap Points",
    ))
    if far_mat in mat_labels:
        idx = mat_labels.index(far_mat)
        fig_term.add_trace(go.Scatter(
            x=[far_mat], y=[swap_pts_term[idx]],
            mode="markers",
            marker=dict(size=14, color="white", line=dict(color="#FFD700", width=2)),
            name="Selected",
        ))
    # For forward-forward: mark the near leg with a dashed line
    if swap_type == "forward-forward" and near_mat in mat_labels:
        fig_term.add_vline(
            x=mat_labels.index(near_mat),
            line=dict(color="rgba(255,215,0,0.5)", dash="dash", width=1),
            annotation_text=f"Near: {near_mat}",
            annotation_position="top",
        )
    fig_term.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1))
    fig_term.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis=dict(
            title=bar_title,
            range=[
                min(0, min(swap_pts_term)) * 1.2,
                max(swap_pts_term) * 1.18 if max(swap_pts_term) > 0 else 1,
            ],
        ),
        showlegend=True,
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig_term, use_container_width=True)

    st.markdown("#### Sensitivity")

    st.markdown("**Swap Points surface regarding USD and Lease Rates**")

    r_range = np.linspace(max(0.01, sw_r_pct - 3), sw_r_pct + 3, 40)
    l_range = np.linspace(max(0.01, sw_lease_pct - 2), sw_lease_pct + 3, 40)
    R, L = np.meshgrid(r_range, l_range)

    if swap_type == "spot-forward":
        Z = sw_spot * (np.exp((R / 100 - L / 100) * T_far) - 1)
    else:
        near_prices = sw_spot * np.exp((R / 100 - L / 100) * T_near)
        far_prices = sw_spot * np.exp((R / 100 - L / 100) * T_far)
        Z = far_prices - near_prices

    fig_surf = go.Figure(go.Surface(
        x=r_range, y=l_range, z=Z,
        colorscale="RdYlGn",
        colorbar=dict(title=f"Swap pts ({currency})", len=0.7),
        contours=dict(
            z=dict(show=True, usecolormap=True, project=dict(z=True)),
        ),
    ))
    current_z = float(res["Swap Points"])
    fig_surf.add_trace(go.Scatter3d(
        x=[sw_r_pct], y=[sw_lease_pct], z=[current_z],
        mode="markers",
        marker=dict(size=6, color="white", symbol="circle"),
        name="Current",
    ))
    fig_surf.update_layout(
        height=500,
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            xaxis_title="USD Rate (%)",
            yaxis_title="Lease Rate (%)",
            zaxis_title=f"Swap Points ({currency})",
            camera=dict(eye=dict(x=1.6, y=-1.6, z=0.8)),
        ),
        showlegend=False,
    )
    st.plotly_chart(fig_surf, use_container_width=True)



else:
    st.warning("Enter a valid spot price.")
