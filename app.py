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
    get_usd_yield_curve,
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

hd_c1, hd_c2 = st.columns([6, 1])
hd_c1.title("Spot Forward Swap Pricer")
if hd_c2.button("Refresh", use_container_width=True):
    st.cache_data.clear()

# -- Results container placed first so it renders above the inputs --
results_container = st.container()

st.markdown("#### Contract")

if "sw_reset_counter" not in st.session_state:
    st.session_state.sw_reset_counter = 0
sw_rc = st.session_state.sw_reset_counter

if st.button("Reset to Defaults", key="sw_reset"):
    st.session_state.sw_reset_counter = sw_rc + 1
    st.rerun()

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

mk_c1, mk_c2, mk_c3, mk_c4, mk_c5 = st.columns(5)

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

# Rate tenor selector — picks which Treasury CMT rate seeds the USD Rate input
yc_df = get_usd_yield_curve()
yc_tenors = yc_df["Tenor"].tolist() if not yc_df.empty else ["3M"]
default_tenor_idx = yc_tenors.index("3M") if "3M" in yc_tenors else 0
rate_tenor = mk_c2.selectbox(
    "Rate Tenor", yc_tenors,
    index=default_tenor_idx, key=f"sw_rate_tenor_{sw_rc}",
    help="Selects which US Treasury CMT tenor seeds the USD Rate below",
)

sw_rate_default = 4.5
try:
    r = get_rate_for_tenor(rate_tenor)
    if r:
        sw_rate_default = float(r)
except Exception:
    pass

sw_r_pct = mk_c3.number_input(
    f"USD Rate ({rate_tenor}) %", value=sw_rate_default, format="%.4f", key=f"sw_rate_{sw_rc}_{rate_tenor}",
)
sw_lease_pct = mk_c4.number_input(
    "Lease Rate (%)", value=0.5, format="%.4f", key=f"sw_lease_{sw_rc}",
)

mat_options = list(MATURITIES.keys())

if swap_type == "forward-forward":
    far_idx = min(4, len(mat_options) - 1)
    far_mat = mk_c5.selectbox(
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
    far_mat = mk_c5.selectbox(
        "Far Leg Maturity", mat_options,
        index=min(far_idx, len(mat_options) - 1), key=f"sw_far_{sw_rc}",
    )
    T_far = MATURITIES[far_mat]
    T_near = 0.0

# -- Show live FX rate + yield curve expander --
if currency != "USD":
    fx = get_fx_rates()
    rate_val = fx.get(currency)
    if rate_val:
        st.caption(f"FX: 1 {currency} = {rate_val:.4f} USD  |  1 USD = {1/rate_val:.4f} {currency}")

if not yc_df.empty:
    with st.expander("US Treasury Yield Curve (live CMT rates)", expanded=False):
        fig_yc = go.Figure(go.Bar(
            x=yc_df["Tenor"],
            y=yc_df["Rate (%)"],
            marker_color="#4A90D9",
            text=[f"{v:.2f}%" for v in yc_df["Rate (%)"]],
            textposition="outside",
        ))
        # Highlight selected tenor
        if rate_tenor in yc_df["Tenor"].values:
            hi_idx = yc_df["Tenor"].tolist().index(rate_tenor)
            fig_yc.add_trace(go.Scatter(
                x=[rate_tenor], y=[yc_df["Rate (%)"].iloc[hi_idx]],
                mode="markers",
                marker=dict(size=14, color="white", line=dict(color="#FFD700", width=2)),
                name="Selected tenor",
            ))
        fig_yc.update_layout(
            height=260,
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Rate (%)",
            showlegend=False,
        )
        st.plotly_chart(fig_yc, use_container_width=True)
        st.dataframe(
            yc_df.rename(columns={"Rate (%)": "Rate (%)"}),
            use_container_width=True, hide_index=True,
        )

# -- Compute --

if sw_spot > 0:
    res = price_swap(
        sw_spot, sw_r_pct, sw_lease_pct,
        T_near, T_far, notional, direction, swap_type,
    )

    ccy_sym = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}.get(currency, "")

    # Fill results container at the top
    with results_container:
        m_c1, m_c2, m_c3 = st.columns(3)
        m_c1.metric("Swap Points", f"{res['Swap Points']:+,.4f}")
        m_c2.metric("Cost of Carry (annualized)", f"{res['Cost of Carry (% ann.)']:+.4f}%")
        m_c3.metric("Net Cash Flow", f"{ccy_sym}{res['Net CF (USD)']:+,.2f}")

    # -- Charts --
    st.markdown("**Swap Points Term Structure**")

    mat_labels = list(MATURITIES.keys())
    mat_years = list(MATURITIES.values())
    swap_pts_term = [
        sw_spot * (np.exp((sw_r_pct / 100 - sw_lease_pct / 100) * t) - 1)
        for t in mat_years
    ]

    fig_term = go.Figure()
    fig_term.add_trace(go.Bar(
        x=mat_labels, y=swap_pts_term,
        marker_color=["#4CAF50" if v >= 0 else "#F44336" for v in swap_pts_term],
        text=[f"{v:+.2f}" for v in swap_pts_term],
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
    fig_term.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1))
    fig_term.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis=dict(
            title=f"Swap Points ({currency}/oz)",
            range=[
                min(0, min(swap_pts_term)) * 1.2,
                max(swap_pts_term) * 1.18,
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
