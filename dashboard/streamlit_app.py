"""FIFA World Cup 2026 — Ticket Price Tracker (Streamlit).

Reads the published semantic Parquet exports via dashboard/data.py — no
database file, no crawler imports. Port of fifa_tickets' dashboard.py.

Run with:  streamlit run dashboard/streamlit_app.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data as wh

try:
    _ = wh.sources()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()


@st.cache_data(ttl=300)
def _sources():
    return wh.sources()


@st.cache_data(ttl=300)
def _crawl_timestamps():
    return wh.crawl_timestamps()


@st.cache_data(ttl=300)
def _cities():
    return wh.cities()


@st.cache_data(ttl=300)
def _teams():
    return wh.teams()


@st.cache_data(ttl=300)
def _match_prices(sources_tuple, stage, city, team):
    return wh.match_prices(list(sources_tuple), stage, city, team)


@st.cache_data(ttl=300)
def _market_trends(sources_tuple):
    return wh.market_trends(list(sources_tuple))


@st.cache_data(ttl=300)
def _price_changes(sources_tuple):
    return wh.price_changes(list(sources_tuple))


@st.cache_data(ttl=300)
def _source_prices(sources_tuple):
    return wh.source_prices(list(sources_tuple))


SOURCE_COLORS = {
    "vivid": "#7C3AED", "gametime": "#059669", "stubhub": "#DC2626",
    "viagogo": "#2563EB", "fifacollect": "#D97706",
}
SOURCE_DISPLAY_NAMES = {
    "vivid": "Vivid Seats", "stubhub": "StubHub", "viagogo": "Viagogo",
    "gametime": "Gametime", "fifacollect": "FIFA Collect",
}
STAGE_ORDER = [
    "Group A", "Group B", "Group C", "Group D", "Group E", "Group F",
    "Group G", "Group H", "Group I", "Group J", "Group K", "Group L",
    "Group Stage", "Round of 32", "Round of 16", "Quarter-Final",
    "Semi-Final", "Bronze Final", "Final",
]
STAGE_CHART_ORDER = ["Group Stage", "Round of 32", "Round of 16", "Quarter-Final",
                     "Semi-Final", "Bronze Final", "Final"]
_VENUE_COORDS = {
    "Dallas": (32.7473, -97.0945), "Atlanta": (33.7555, -84.4009),
    "Boston": (42.0909, -71.2643), "New York/New Jersey": (40.8128, -74.0742),
    "Guadalajara": (20.7010, -103.3732), "Houston": (29.6847, -95.4107),
    "Los Angeles": (33.9534, -118.3392), "Kansas City": (39.0489, -94.4839),
    "Mexico City": (19.3029, -99.1505), "Miami": (25.9580, -80.2389),
    "Monterrey": (25.6721, -100.3098), "Philadelphia": (39.9008, -75.1674),
    "San Francisco": (37.4033, -121.9694), "Seattle": (47.5952, -122.3316),
    "Toronto": (43.6426, -79.4054), "Vancouver": (49.2768, -123.1120),
}


def _chart_stage(stage) -> str:
    if not stage:
        return "Unknown"
    return "Group Stage" if str(stage).startswith("Group") else str(stage)


st.set_page_config(page_title="FIFA 2026 Ticket Tracker", page_icon="⚽", layout="wide")

# ── Header / countdown ───────────────────────────────────────────────────
WC_START = date(2026, 6, 11)
today = date.today()
days_left = (WC_START - today).days
sources = _sources()
names = [SOURCE_DISPLAY_NAMES.get(s, s.title()) for s in sources]
subtitle = (" & ".join(names) if len(names) <= 2
            else ", ".join(names[:-1]) + " & " + names[-1])

if days_left > 0:
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%);
                border-radius: 16px; padding: 28px 32px; margin-bottom: 24px;
                display: flex; align-items: center; justify-content: space-between;
                flex-wrap: wrap; gap: 16px;">
        <div>
            <h1 style="color: #ffffff; margin: 0; font-size: 1.8rem;">⚽ FIFA World Cup 2026 Ticket Tracker</h1>
            <p style="color: #94a3b8; margin: 4px 0 0 0;">Track prices across {subtitle}</p>
        </div>
        <div style="text-align: center; background: rgba(255,255,255,0.08); border-radius: 12px; padding: 16px 28px;">
            <div style="color: #fbbf24; font-size: 2.8rem; font-weight: 800; line-height: 1;">{days_left}</div>
            <div style="color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px;">days to kickoff</div>
            <div style="color: #64748b; font-size: 0.75rem;">June 11, 2026</div>
        </div>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background: linear-gradient(135deg, #065f46 0%, #064e3b 100%);
                border-radius: 16px; padding: 28px 32px; margin-bottom: 24px;">
        <h1 style="color: #ffffff; margin: 0; font-size: 1.8rem;">⚽ FIFA World Cup 2026 Ticket Tracker</h1>
        <p style="color: #6ee7b7; margin: 4px 0 0 0;">The World Cup is here!</p>
    </div>""", unsafe_allow_html=True)

crawl_ts = _crawl_timestamps()
cities, teams = _cities(), _teams()

# ── Sidebar filters ──────────────────────────────────────────────────────
st.sidebar.markdown("### 🔍 Filters")
selected_sources = st.sidebar.multiselect("Ticket Sources", sources, default=sources)
selected_stage = st.sidebar.selectbox("Tournament Stage", ["All Stages"] + STAGE_ORDER)
stage_filter = None if selected_stage == "All Stages" else selected_stage
selected_city = st.sidebar.selectbox("Host City", ["All Cities"] + cities)
city_filter = None if selected_city == "All Cities" else selected_city
selected_team = st.sidebar.selectbox("Team", ["All Teams"] + teams)
team_filter = None if selected_team == "All Teams" else selected_team
st.sidebar.markdown("---")
st.sidebar.caption(f"Warehouse: `{wh.warehouse_dir().name}/` (published Parquet)")
st.sidebar.caption(f"Crawls: {len(crawl_ts)} | Sources: {len(sources)}")

matches = _match_prices(tuple(sorted(selected_sources)), stage_filter, city_filter, team_filter)
priced = matches[matches["best_price"].notna()]

# ── Scorecards ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
cheapest = priced.loc[priced["best_price"].idxmin()] if len(priced) else None
with c1:
    st.metric("Cheapest Game", f"${cheapest['best_price']:,.0f}" if cheapest is not None else "—",
              cheapest["display_name"] if cheapest is not None else None)
with c2:
    st.metric("Median Game Price", f"${priced['best_price'].median():,.0f}" if len(priced) else "—")
with c3:
    st.metric("Games Tracked", len(priced))
with c4:
    multi = int((priced["sources_with_price"] >= 2).sum())
    st.metric("Multi-Source Coverage", f"{multi}/{len(priced)}" if len(priced) else "—")

# ── Market trend ─────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Market Price Trend")
st.caption("Best available price per game, deduplicated across sources — track how the market moves over time")
trends = _market_trends(tuple(sorted(selected_sources)))
if len(trends):
    fig = go.Figure()
    for col, label in [("median_price", "Median"), ("avg_price", "Average"), ("min_price", "Cheapest game")]:
        fig.add_trace(go.Scatter(x=trends["crawl_date"], y=trends[col], mode="lines+markers", name=label))
    fig.update_layout(yaxis_title="Price (USD)", height=380, margin=dict(t=20, b=40),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trend data for the selected sources.")

# ── Price by source ──────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🏪 Price by Source")
st.caption("How each marketplace stacks up right now")
overview = wh.source_overview(selected_sources)
if len(overview):
    for col, (_, ov) in zip(st.columns(len(overview)), overview.iterrows()):
        with col:
            color = SOURCE_COLORS.get(ov["source"], "#6b7280")
            st.markdown(f"**<span style='color:{color}'>●</span> {SOURCE_DISPLAY_NAMES.get(ov['source'], ov['source'])}**",
                        unsafe_allow_html=True)
            st.metric("Cheapest", f"${ov['min_price']:,.0f}" if pd.notna(ov["min_price"]) else "—")
            st.metric("Median", f"${ov['median_price']:,.0f}" if pd.notna(ov["median_price"]) else "—")
            st.metric("Events w/ price", f"{int(ov['events_with_price'])}/{int(ov['total_events'])}")

# ── Scatter: all games ───────────────────────────────────────────────────
st.markdown("---")
st.subheader("🗺️ Price Map — All Games")
st.caption("Each dot is one game on one source — quickly spot the cheapest options")
sp = _source_prices(tuple(sorted(selected_sources)))
sp = sp[sp["lowest_price"].notna() & sp["match_number"].notna()]
if stage_filter:
    sp = sp[sp["stage"] == stage_filter]
if city_filter:
    sp = sp[sp["city"] == city_filter]
if team_filter:
    sp = sp[(sp["team_1"] == team_filter) | (sp["team_2"] == team_filter)]
if len(sp):
    fig = px.scatter(sp, x="event_start_local", y="lowest_price", color="source",
                     color_discrete_map=SOURCE_COLORS, hover_name="display_name",
                     hover_data={"city": True, "stage": True, "inventory_count": True})
    fig.update_layout(xaxis_title="Match date", yaxis_title="Lowest price (USD)",
                      height=440, margin=dict(t=20, b=40))
    st.plotly_chart(fig, use_container_width=True)

# ── Best deals ───────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("💰 Best Deals — Where to Buy")
st.caption("Events available on multiple sources — see which marketplace has the lowest price")
deals = priced[priced["sources_with_price"] >= 2].copy()
if len(deals):
    show = deals[["display_name", "match_date", "city", "best_price", "best_source",
                  "worst_price", "savings_vs_worst"]].sort_values("savings_vs_worst", ascending=False)
    st.dataframe(
        show.style.format({"best_price": "${:,.0f}", "worst_price": "${:,.0f}",
                           "savings_vs_worst": "${:,.0f}"}, na_rep="—"),
        use_container_width=True, hide_index=True)
else:
    st.info("Need 2+ sources with overlapping events for comparison.")

# ── All games ────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📋 All Games")
changes = _price_changes(tuple(sorted(selected_sources)))
games = priced.merge(changes[["match_number", "change_dollars", "change_pct"]],
                     on="match_number", how="left") if len(changes) else priced
if len(games):
    show = games[["display_name", "stage", "match_date", "city", "best_price", "best_source",
                  "sources_with_price", "total_inventory", "change_pct"]].rename(columns={
        "display_name": "Game", "stage": "Stage", "match_date": "Date", "city": "City",
        "best_price": "Best Price", "best_source": "Best Source",
        "sources_with_price": "Sources", "total_inventory": "Inventory", "change_pct": "Δ since first crawl %"})
    st.dataframe(show.style.format({"Best Price": "${:,.0f}", "Δ since first crawl %": "{:+.1f}%"}, na_rep="—"),
                 use_container_width=True, hide_index=True)
else:
    st.info("No events match the current filters.")

# ── Price by stage / city ────────────────────────────────────────────────
if len(priced):
    st.markdown("---")
    st.subheader("🏟️ Price by Stage")
    st.caption("Average best price grouped by tournament stage — find which rounds offer the cheapest tickets")
    stage_df = priced.assign(chart_stage=priced["stage"].map(_chart_stage)).groupby("chart_stage", as_index=False).agg(
        avg_price=("best_price", "mean"), games=("best_price", "size"))
    fig = px.bar(stage_df, x="chart_stage", y="avg_price", text="games",
                 category_orders={"chart_stage": STAGE_CHART_ORDER})
    fig.update_layout(xaxis_title="", yaxis_title="Avg best price (USD)", height=380, margin=dict(t=20, b=40))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("📍 Price by City")
    st.caption("Average best price per host city — bubble size shows number of games")
    city_df = priced.dropna(subset=["city"]).groupby("city", as_index=False).agg(
        avg_price=("best_price", "mean"), games=("best_price", "size"),
        min_price=("best_price", "min"), max_price=("best_price", "max"))
    city_df = city_df[city_df["city"].isin(_VENUE_COORDS)]
    if len(city_df):
        city_df["lat"] = city_df["city"].map(lambda c: _VENUE_COORDS[c][0])
        city_df["lon"] = city_df["city"].map(lambda c: _VENUE_COORDS[c][1])
        # plotly >=6 renamed scatter_mapbox -> scatter_map; support both.
        scatter_map = getattr(px, "scatter_map", None) or px.scatter_mapbox
        map_kwargs = {} if hasattr(px, "scatter_map") else {"mapbox_style": "open-street-map"}
        fig = scatter_map(city_df, lat="lat", lon="lon", size="games", color="avg_price",
                          hover_name="city", color_continuous_scale="RdYlGn_r",
                          size_max=30, zoom=2.5, center={"lat": 37, "lon": -98}, **map_kwargs)
        fig.update_layout(height=500, margin=dict(t=10, b=10, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

# ── Days to kickoff vs price ─────────────────────────────────────────────
st.markdown("---")
st.subheader("⏳ Days to Kickoff vs Price")
st.caption("How ticket prices moved as each game's kickoff got closer — each line is one game on one source")
if len(priced) and len(crawl_ts) > 1:
    options = priced.dropna(subset=["event_start_local"])
    show_all = st.checkbox("Show all games", value=True, key="dte_all")
    labels = options["display_name"].tolist() if show_all else st.multiselect(
        "Select games to compare", options["display_name"].tolist(),
        default=options["display_name"].tolist()[:5], key="dte_games")
    match_numbers = options[options["display_name"].isin(labels)]["match_number"].tolist()
    hist = wh.load("price_trends")
    hist = hist[hist["match_number"].isin(match_numbers) & hist["lowest_price"].notna()
                & hist["source"].isin(selected_sources)].copy()
    if len(hist):
        starts = options.set_index("match_number")["event_start_local"]
        hist["game_date"] = pd.to_datetime(hist["match_number"].map(starts)).dt.date
        hist["Days Out"] = [
            (g - datetime.fromisoformat(str(c).replace("Z", "+00:00")).date()).days
            for g, c in zip(hist["game_date"], hist["crawl_ts_utc"])]
        hist = hist[hist["Days Out"] >= 0].rename(columns={"lowest_price": "Price", "display_name": "Game"})
        hist["Source"] = hist["source"].str.title()
        fig = px.line(hist.sort_values("Days Out", ascending=False), x="Days Out", y="Price",
                      color="Game", line_dash="Source", markers=True)
        fig.update_traces(marker=dict(size=5))
        fig.update_layout(xaxis_title="Days Until Kickoff", yaxis_title="Lowest Price (USD)",
                          xaxis=dict(autorange="reversed"), height=480,
                          margin=dict(t=20, b=40), showlegend=False, hovermode="closest")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No historical price data available for the selected games.")

# ── Per-game price history ───────────────────────────────────────────────
st.markdown("---")
st.subheader("📊 Price History per Game")
if len(matches) and len(crawl_ts) > 1:
    label_to_match = dict(zip(matches["display_name"], matches["match_number"]))
    ph1, ph2 = st.columns([3, 1])
    with ph1:
        picked = st.selectbox("Pick a game", list(label_to_match.keys()))
    with ph2:
        granularity = st.radio("Group by", ["Day", "Hour"], index=0, horizontal=True, key="ph_gran")
    hist = wh.load("price_trends")
    hist = hist[(hist["match_number"] == label_to_match[picked]) & hist["source"].isin(selected_sources)].copy()
    if len(hist):
        hist["crawl_ts_utc"] = pd.to_datetime(hist["crawl_ts_utc"])
        freq = "h" if granularity == "Hour" else "D"
        hist["bucket"] = hist["crawl_ts_utc"].dt.floor(freq)
        grouped = (hist.sort_values("crawl_ts_utc").groupby(["source", "bucket"], as_index=False)
                   .last(numeric_only=False))
        fig = go.Figure()
        for source, g in grouped.groupby("source"):
            fig.add_trace(go.Scatter(x=g["bucket"], y=g["lowest_price"], mode="lines+markers",
                                     name=SOURCE_DISPLAY_NAMES.get(source, source),
                                     line=dict(color=SOURCE_COLORS.get(source, "#6b7280"), width=2)))
        fig.update_layout(yaxis_title="Price (USD)", height=400, margin=dict(t=20, b=40),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                          hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No price history for this game yet.")
else:
    st.info("No events match the current filters.")

# ── Listing drill-down ───────────────────────────────────────────────────
st.markdown("---")
st.subheader("🎟️ Individual Listings")
st.caption("See actual ticket listings for a specific game and source (latest crawl)")
if len(matches):
    label_to_match = dict(zip(matches["display_name"], matches["match_number"]))
    picked_game = st.selectbox("Game", list(label_to_match.keys()), key="listing_event")
    candidates = sp[sp["match_number"] == label_to_match[picked_game]] if len(sp) else sp
    if len(candidates):
        picked_source_label = st.selectbox(
            "Source", [SOURCE_DISPLAY_NAMES.get(s, s) for s in candidates["source"]], key="listing_source")
        picked_row = candidates[
            candidates["source"].map(lambda s: SOURCE_DISPLAY_NAMES.get(s, s)) == picked_source_label].iloc[0]
        listings = wh.listing_distribution(picked_row["source"], picked_row["event_id_external"])
        if len(listings):
            show = listings[["section", "row", "price", "deal_score", "deal_label"]]
            col_l, col_r = st.columns([2, 1])
            with col_l:
                st.dataframe(show.style.format({"price": "${:,.2f}"}, na_rep="—"),
                             use_container_width=True, hide_index=True)
            with col_r:
                fig = px.histogram(show, x="price", nbins=15, color_discrete_sequence=["#7c3aed"])
                fig.update_layout(xaxis_title="Price (USD)", yaxis_title="Listings",
                                  height=300, margin=dict(t=10, b=40))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"No individual listings found for this game on {picked_source_label}.")
    else:
        st.info("No source prices this game under the current filters.")
else:
    st.info("No events available.")

st.markdown("---")
st.caption("Prices shown are the lowest available ticket price per event from each source. "
           "All prices include fees where indicated by the source. "
           "Data refreshes on the scheduled ingest (crawl → dbt → publish).")
