"""Powertracker Streamlit app.

Public, shareable map of US AI / hyperscaler data centers overlaid on
balancing-authority demand growth, utility residential rate changes, and
county per-capita GDP growth.

Deploy: push this repo to GitHub, point Streamlit Cloud at `app.py`.
The app reads pre-computed YoY aggregates from `data/cache/` (no EIA API
key needed at runtime).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.mapbuild import (  # noqa: E402
    _DIST_OWNERSHIP,
    MapFilters,
    build_folium_map,
    load_data,
)

st.set_page_config(
    page_title="powertracker - AI data centers + grid demand",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def _cached_data():
    # MapData isn't hashable across reruns, so we materialize via load_data
    # under the cache_data decorator. The GeoJSONs and DataFrames are loaded
    # once per session.
    return load_data(use_cache=True)


def _format_pct(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def main() -> None:
    data = _cached_data()

    with st.sidebar:
        st.title("powertracker")
        st.caption(
            "AI data centers vs. grid demand, retail electricity rates, "
            "and per-capita GDP growth."
        )
        st.markdown("---")

        st.subheader("Filters")
        focus_options = sorted(data.sites["ai_focus"].dropna().unique().tolist())
        selected_focus = st.multiselect("AI focus", focus_options, default=focus_options)

        status_options = sorted(data.sites["status"].dropna().unique().tolist())
        selected_status = st.multiselect("Status", status_options, default=status_options)

        states_in_use = sorted(data.sites["state"].dropna().unique().tolist())
        state_choice = st.selectbox(
            "Zoom to state",
            options=["(all of US)"] + states_in_use,
            help="Centers the map on sites in this state.",
        )
        selected_states = None if state_choice == "(all of US)" else {state_choice}

        st.markdown("---")
        st.subheader("Layers")
        st.caption("Toggle in the layer control on the top right of the map.")

        with st.expander("About the data", expanded=False):
            st.markdown(
                "- **BA demand YoY**: trailing 12mo vs prior 12mo hourly load "
                "(EIA-930, 20 BAs covering sites in our list)\n"
                "- **Utility resi rate YoY**: 2023 vs 2024 residential ¢/kWh "
                "(EIA-861 raw, joined to HIFLD utility service territories)\n"
                "- **County GDP YoY**: 2023 vs 2024 real per-capita GDP "
                "(BEA CAGDP1 + CAINC1)\n"
                "- **Sites**: 144 US AI / hyperscaler data centers (108 operational / "
                "under construction / announced + 36 proposed and pending local-gov approval, "
                "including celebrity-fronted megacampuses by Kevin O'Leary, Rick Perry, "
                "Chamath Palihapitiya, David Rubenstein, Larry Fink and Eric Schmidt), "
                "researched from operator press releases + primary news sources\n\n"
                "None of the YoY metrics are weather-normalized; AZPS +8% "
                "includes whatever the year's cooling-degree delta was."
            )

    filters = MapFilters(
        focus=set(selected_focus) if selected_focus else None,
        status=set(selected_status) if selected_status else None,
        states=selected_states,
    )

    sites_f = data.sites
    if filters.focus:
        sites_f = sites_f[sites_f["ai_focus"].isin(filters.focus)]
    if filters.status:
        sites_f = sites_f[sites_f["status"].isin(filters.status)]
    if filters.states:
        sites_f = sites_f[sites_f["state"].isin(filters.states)]

    # ---- summary row ----
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Sites shown", f"{len(sites_f)} / {len(data.sites)}")
    if not data.ba_yoy.empty:
        top_ba = data.ba_yoy.loc[data.ba_yoy["growth_pct"].idxmax()]
        col_b.metric(f"Hottest BA ({top_ba.ba})", _format_pct(top_ba.growth_pct))
    if not data.util_yoy.empty:
        dist = data.util_yoy[data.util_yoy["ownership"].isin(_DIST_OWNERSHIP)]
        weighted = (dist["price_change_pct"] * dist["sales_mwh"]).sum() / dist["sales_mwh"].sum()
        col_c.metric("Resi rate YoY (sales-weighted)", _format_pct(weighted))
    if not data.gdp_yoy.empty:
        weighted_gdp = (
            data.gdp_yoy["growth_pct"] * data.gdp_yoy["population_2024"]
        ).sum() / data.gdp_yoy["population_2024"].sum()
        col_d.metric("County GDP YoY (pop-weighted)", _format_pct(weighted_gdp))

    # ---- map ----
    m, summary = build_folium_map(data, filters)
    st_folium(m, width=None, height=720, returned_objects=[])

    # ---- leaderboards under the map ----
    st.markdown("---")
    tab_ba, tab_util, tab_gdp, tab_sites = st.tabs([
        "BA demand growth", "Utility rate changes", "County GDP growth", "Sites"
    ])

    with tab_ba:
        if data.ba_yoy.empty:
            st.info("No BA demand data available.")
        else:
            df = data.ba_yoy.copy()
            df["growth_pct"] = df["growth_pct"].round(2)
            df["trailing_mw"] = df["trailing_mw"].round(0).astype(int)
            df["prior_mw"] = df["prior_mw"].round(0).astype(int)
            st.dataframe(
                df[["ba", "growth_pct", "trailing_mw", "prior_mw"]]
                .sort_values("growth_pct", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    with tab_util:
        if data.util_yoy.empty:
            st.info("No utility rate data available.")
        else:
            df = data.util_yoy[data.util_yoy["ownership"].isin(_DIST_OWNERSHIP)].copy()
            df = df[df["customers"] >= 5000]
            df["price_change_pct"] = df["price_change_pct"].round(2)
            df["price_2023"] = df["price_2023"].round(2)
            df["price_2024"] = df["price_2024"].round(2)
            df["customers"] = df["customers"].astype(int)
            st.caption(
                "Distribution utilities (IOU/Coop/Muni/Federal/State) with at "
                "least 5,000 residential customers. Sortable."
            )
            st.dataframe(
                df[["utility_name", "state", "ownership", "price_2023", "price_2024",
                    "price_change_pct", "customers"]]
                .sort_values("price_change_pct", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    with tab_gdp:
        if data.gdp_yoy.empty:
            st.info("No county GDP data available.")
        else:
            df = data.gdp_yoy.copy()
            df = df[df["population_2024"] >= 10_000]
            df["growth_pct"] = df["growth_pct"].round(2)
            df["gdp_per_capita_2023"] = df["gdp_per_capita_2023"].round(0).astype(int)
            df["gdp_per_capita_2024"] = df["gdp_per_capita_2024"].round(0).astype(int)
            df["population_2024"] = df["population_2024"].astype(int)
            st.caption("Counties with population >= 10,000. Sortable.")
            st.dataframe(
                df[["geoname", "growth_pct", "gdp_per_capita_2023",
                    "gdp_per_capita_2024", "population_2024"]]
                .sort_values("growth_pct", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

    with tab_sites:
        st.dataframe(
            sites_f[["name", "operator", "city", "state", "ba_code",
                     "announced_mw", "status", "ai_focus", "online_year"]]
            .sort_values(["ai_focus", "announced_mw"], ascending=[True, False]),
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Download data", expanded=False):
            st.download_button(
                "data_centers.csv",
                sites_f.to_csv(index=False).encode("utf-8"),
                file_name="data_centers.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
