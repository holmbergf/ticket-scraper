"""FIFA World Cup 2026 — Ticket Tracker (Streamlit).

Presents resale ticket prices from the semantic layer for users to make
their own decisions. Reads only published Parquet exports (data.py).

Run with:  streamlit run dashboard/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import altair as alt
import pandas as pd
import streamlit as st

import data as wh

try:
    VERSION = wh.warehouse_version()
    _ = wh.sources()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

st.set_page_config(page_title="FIFA 2026 Ticket Tracker", page_icon="⚽", layout="wide")

CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1180px; }
  h1 { font-size: 2rem; letter-spacing: -0.02em; }
  h2, h3 { letter-spacing: -0.01em; }
  .team-name { font-size: 1.55rem; font-weight: 750; line-height: 1.1; }
  .team-sub { color: #9db2c3; font-size: 0.9rem; margin-top: 0.15rem; }
  .vs { font-size: 1.1rem; color: #7e93a6; text-align: center; padding-top: 0.7rem; }
  .pill { display: inline-block; padding: 0.18rem 0.6rem; border-radius: 999px;
          background: #1d2f22; color: #7bd79e; font-size: 0.82rem; font-weight: 650; }
  .pill-amber { background: #33290f; color: #e8c468; }
  .duel { display: flex; height: 18px; border-radius: 6px; overflow: hidden; margin: 0.35rem 0 0.2rem; }
  .duel > div { height: 100%; }
  .cmp-row { display: grid; grid-template-columns: 1fr 130px 1fr; align-items: center; gap: 10px; margin: 0.3rem 0; }
  .cmp-label { text-align: center; color: #9db2c3; font-size: 0.82rem; }
  .bar-track { background: #22303f; height: 10px; border-radius: 5px; position: relative; }
  .bar-fill { height: 100%; border-radius: 5px; }
  .bar-val { font-size: 0.85rem; font-weight: 650; white-space: nowrap; }
  .src-row { display: grid; grid-template-columns: 150px 1fr 86px 110px; align-items: center; gap: 10px; margin: 0.32rem 0; }
  .src-name { font-size: 0.9rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .src-delta { color: #9db2c3; font-size: 0.82rem; text-align: right; }
  .small { color: #9db2c3; font-size: 0.85rem; }
  div[data-testid="stMetric"] { background: #151f2a; border: 1px solid #22303f;
    border-radius: 10px; padding: 0.7rem 0.9rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

SOURCE_COLORS = {
    "vivid": "#9a7fc9", "gametime": "#2ba8a0", "stubhub": "#e14b5a",
    "viagogo": "#4a7fc9", "fifacollect": "#e08a3c",
}
SOURCE_DISPLAY_NAMES = {
    "vivid": "Vivid Seats", "stubhub": "StubHub", "viagogo": "Viagogo",
    "gametime": "Gametime", "fifacollect": "FIFA Collect",
}
_PALETTE = ["#4a7fc9", "#2ba8a0", "#e08a3c", "#9a7fc9", "#e14b5a", "#69BE28",
            "#c9a227", "#5a86d6", "#d06a6a", "#4f9e79", "#8fa9c9", "#FB4F14"]
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


def color(team: str) -> str:
    """Stable per-team color for national teams (hash into the palette)."""
    return _PALETTE[sum(ord(c) for c in str(team)) % len(_PALETTE)]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def pair_colors(a_name: str, b_name: str, a_color: str, b_color: str) -> tuple[str, str]:
    """Two colors guaranteed distinguishable: near-identical hues get one
    side lightened/darkened until a human can tell them apart."""
    if sum((a - b) ** 2 for a, b in zip(_rgb(a_color), _rgb(b_color))) ** 0.5 < 85:
        r, g, b = _rgb(b_color)
        mix = 255 if (0.299 * r + 0.587 * g + 0.114 * b) < 190 else 0
        b_color = "#{:02x}{:02x}{:02x}".format(*(round(c + (mix - c) * 0.8) for c in (r, g, b)))
    return a_color, b_color


def usd(x) -> str:
    return "—" if x is None or pd.isna(x) else f"${float(x):,.0f}"


def cdelta(pct_change) -> str:
    """Price-change % colored for buyers: drops green (strong <= -10%),
    flat amber, rises red. Always read alongside the crawl count."""
    if pct_change is None or pd.isna(pct_change):
        return "—"
    v = float(pct_change)
    c = "#3fb950" if v <= -10 else "#7bd79e" if v < 0 else "#d8a13a" if v <= 5 else "#e05d5d"
    return f'<span style="color:{c};font-weight:650">{v:+.1f}%</span>'


def chart_stage(stage) -> str:
    if not stage or pd.isna(stage):
        return "Unknown"
    return "Group Stage" if str(stage).startswith("Group") else str(stage)


@st.cache_data(ttl=3600, show_spinner="Loading warehouse data…")
def _match_prices(sources_tuple, stage, city, team, version: str):
    return wh.match_prices(list(sources_tuple), stage, city, team)


@st.cache_data(ttl=3600, show_spinner="Loading warehouse data…")
def _source_prices(sources_tuple, version: str):
    return wh.source_prices(list(sources_tuple))


@st.cache_data(ttl=3600, show_spinner="Loading price history…")
def _price_trends_table(version: str):
    return wh.load("price_trends")


@st.cache_data(ttl=3600, show_spinner="Loading market trends…")
def _market_trends(sources_tuple, version: str):
    return wh.market_trends(list(sources_tuple))


@st.cache_data(ttl=3600, show_spinner="Loading price changes…")
def _price_changes(sources_tuple, version: str):
    return wh.price_changes(list(sources_tuple))


@st.cache_data(ttl=3600, show_spinner="Loading sparklines…")
def _sparklines(sources_tuple, version: str):
    return wh.match_sparklines(list(sources_tuple))


def team_block(team: str, sub: str, align: str = "left") -> None:
    st.markdown(
        f'<div style="text-align:{align}"><div class="team-name">'
        f'<span style="color:{color(team)}">●</span> {team}</div>'
        f'<div class="team-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def inventory_bar(sp: pd.DataFrame) -> None:
    """Stacked share bar: where the listings for this match sit, by source."""
    d = sp.dropna(subset=["inventory_count"])
    d = d[d["inventory_count"] > 0]
    if d.empty:
        st.caption("No inventory data for this match yet.")
        return
    total = float(d["inventory_count"].sum())
    segments, labels = [], []
    for _, r in d.sort_values("inventory_count", ascending=False).iterrows():
        share = float(r["inventory_count"]) / total * 100
        share_text = "<1%" if 0 < share < 1 else ">99%" if share >= 99.5 else f"{share:.0f}%"
        segments.append(
            f'<div style="width:{share}%;background:{SOURCE_COLORS.get(r["source"], "#6b7280")}"></div>')
        labels.append(
            f'<span><span style="color:{SOURCE_COLORS.get(r["source"], "#6b7280")}">●</span> '
            f'{SOURCE_DISPLAY_NAMES.get(r["source"], r["source"])} {share_text}</span>')
    st.markdown(
        f'<div class="duel">{"".join(segments)}</div>'
        f'<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px 14px" class="small">'
        f'{"".join(labels)}<span>inventory by source</span></div>',
        unsafe_allow_html=True,
    )


def source_price_rows(sp: pd.DataFrame) -> None:
    """Per-source lowest-price bars, cheapest first; bar length = price."""
    d = sp.dropna(subset=["lowest_price"]).sort_values("lowest_price")
    if d.empty:
        st.caption("No priced sources for this match yet.")
        return
    best = float(d["lowest_price"].min())
    worst = float(d["lowest_price"].max())
    rows = []
    for _, r in d.iterrows():
        w = int(round(float(r["lowest_price"]) / worst * 100)) if worst else 0
        delta = "best price" if float(r["lowest_price"]) == best else f"+${float(r['lowest_price']) - best:,.0f} vs best"
        c = SOURCE_COLORS.get(r["source"], "#6b7280")
        rows.append(
            f'<div class="src-row"><div class="src-name"><span style="color:{c}">●</span> '
            f'{SOURCE_DISPLAY_NAMES.get(r["source"], r["source"])}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{w}%;background:{c}"></div></div>'
            f'<div class="bar-val">{usd(r["lowest_price"])}</div>'
            f'<div class="src-delta">{delta}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


def compare_row(label: str, left_val, right_val, left_name: str, right_name: str,
                left_color: str, right_color: str) -> None:
    """Mirrored bars around a center label (this match vs a benchmark)."""
    lc, rc = pair_colors(left_name, right_name, left_color, right_color)
    scale = max([v for v in (left_val, right_val) if v is not None and not pd.isna(v)], default=0) or 1

    def side(val, c, flip: bool) -> str:
        if val is None or pd.isna(val):
            return '<div class="bar-val">—</div>'
        w = int(round(float(val) / scale * 100))
        style = f"width:{w}%;background:{c};" + ("margin-left:auto;" if flip else "")
        return (f'<div style="display:flex;align-items:center;gap:8px;'
                f'{"flex-direction:row-reverse;" if flip else ""}">'
                f'<div class="bar-track" style="flex:1"><div class="bar-fill" style="{style}"></div></div>'
                f'<div class="bar-val">{usd(val)}</div></div>')

    st.markdown(
        f'<div class="cmp-row"><div>{side(left_val, lc, True)}</div>'
        f'<div class="cmp-label">{label}</div><div>{side(right_val, rc, False)}</div></div>',
        unsafe_allow_html=True,
    )


def price_context_panel(m, sp: pd.DataFrame, changes: pd.DataFrame,
                        priced: pd.DataFrame, sources: list[str]) -> str:
    """Markdown context for a match: change, rank, cheapest-source record."""
    lines = ["**Where this match sits, and how it got here**", ""]
    ch = changes[changes["match_number"] == m.match_number] if len(changes) else changes
    if len(ch):
        ch = ch.iloc[0]
        lines.append(
            f"- **Since first crawl** — best price {usd(ch.first_price)} → {usd(ch.latest_price)} "
            f"({cdelta(ch.change_pct)}, {usd(abs(ch.change_dollars))} "
            f"{'cheaper' if ch.change_dollars < 0 else 'more expensive'}).")
    if len(priced):
        rank = int((priced["best_price"] < m.best_price).sum()) + 1 if pd.notna(m.best_price) else None
        stage_med = priced[priced["stage"] == m.stage]["best_price"].median()
        if rank:
            lines.append(f"- **Cheapest rank** — #{rank} of {len(priced)} priced matches "
                         f"under the current filters.")
        if pd.notna(stage_med) and pd.notna(m.best_price) and stage_med:
            rel = (float(m.best_price) - float(stage_med)) / float(stage_med) * 100
            lines.append(f"- **Vs {chart_stage(m.stage)} median** ({usd(stage_med)}) — "
                         f"this match is {cdelta(rel)}.")
    daily = wh.daily_best(int(m.match_number), sources)
    if len(daily):
        counts = daily["best_source"].value_counts()
        detail = ", ".join(
            f"{SOURCE_DISPLAY_NAMES.get(s, s)} on {n} of {len(daily)} crawl days"
            for s, n in counts.items())
        lines.append(f"- **Cheapest source over time** — {detail}.")
        inv = daily.dropna(subset=["total_inventory"])
        if len(inv) > 1:
            lines.append(f"- **Inventory (all sources)** — {int(inv.iloc[0].total_inventory):,} "
                         f"on {inv.iloc[0].crawl_date:%b %-d} → {int(inv.iloc[-1].total_inventory):,} "
                         f"on {inv.iloc[-1].crawl_date:%b %-d}.")
    lines.append("")
    lines.append('<span class="small">Percentages are colored for buyers: green = cheaper. '
                 "Daily best uses canonical event-page snapshots only; small crawl counts "
                 "are weak evidence — always check the dates.</span>")
    return "\n".join(lines)


def render_match_card(m, sp_all: pd.DataFrame, changes: pd.DataFrame,
                      priced: pd.DataFrame, sources: list[str]) -> None:
    sp = sp_all[sp_all["match_number"] == m.match_number]
    kickoff = pd.to_datetime(m.event_start_local) if pd.notna(m.event_start_local) else None
    date_text = f"{kickoff:%a, %b %-d · %-I:%M %p}" if kickoff is not None else "Date TBD"
    with st.container(border=True):
        known_teams = (
            pd.notna(m.team_1) and pd.notna(m.team_2)
            and m.team_1 != "TBD" and m.team_2 != "TBD"
        )
        if known_teams:
            a, mid, h = st.columns([2, 1, 2])
            with a:
                team_block(str(m.team_1), date_text)
            with mid:
                st.markdown('<div class="vs">vs</div>', unsafe_allow_html=True)
                pill_cls = "pill" if chart_stage(m.stage) in ("Final", "Semi-Final") else "pill pill-amber"
                st.markdown(
                    f'<div style="text-align:center;margin-top:0.45rem">'
                    f'<span class="{pill_cls}">{m.stage or "Stage TBD"}</span></div>',
                    unsafe_allow_html=True)
            with h:
                team_block(str(m.team_2), f"{m.venue_name or '—'} · {m.city or '—'}", align="right")
        else:
            # Knockout fixture listed before its teams were known: name the
            # card by round + location instead of showing "TBD vs TBD".
            st.markdown(
                f'<div class="team-name">{m.display_name}</div>'
                f'<div class="team-sub">{date_text} · {m.venue_name or "—"}</div>',
                unsafe_allow_html=True,
            )
        st.caption(f"Match {int(m.match_number)} · {m.city or '—'}, {m.country or '—'} · "
                   f"{int(m.sources_tracking) if pd.notna(m.sources_tracking) else 0} sources tracking")

        c1, c2, c3, c4 = st.columns(4)
        ch = changes[changes["match_number"] == m.match_number] if len(changes) else changes
        delta = f"{float(ch.iloc[0].change_pct):+.1f}% since first crawl" if len(ch) else None
        c1.metric("Best price", usd(m.best_price), delta, delta_color="inverse")
        c2.metric("Cheapest at", SOURCE_DISPLAY_NAMES.get(m.best_source, m.best_source or "—"))
        med = sp["lowest_price"].median() if len(sp.dropna(subset=["lowest_price"])) else None
        c3.metric("Median across sources", usd(med))
        c4.metric("Listings (all sources)",
                  f"{int(m.total_inventory):,}" if pd.notna(m.total_inventory) else "—")

        inventory_bar(sp)
        st.divider()
        st.markdown("**Lowest price by source**")
        source_price_rows(sp)
        stage_med_all = priced[priced["stage"] == m.stage]["best_price"].median() if len(priced) else None
        tourn_med = priced["best_price"].median() if len(priced) else None
        if pd.notna(m.best_price):
            compare_row(f"vs {chart_stage(m.stage)} median", float(m.best_price),
                        float(stage_med_all) if pd.notna(stage_med_all) else None,
                        "this match", "stage median", "#3aa76d", "#5a86d6")
            compare_row("vs tournament median", float(m.best_price),
                        float(tourn_med) if pd.notna(tourn_med) else None,
                        "this match", "tournament median", "#3aa76d", "#c9a227")
        with st.expander("Price context — history & benchmarks for this match"):
            st.markdown(price_context_panel(m, sp, changes, priced, sources), unsafe_allow_html=True)
            daily = wh.daily_best(int(m.match_number), sources)
            if len(daily):
                chart = (
                    alt.Chart(daily.assign(crawl_date=pd.to_datetime(daily["crawl_date"])))
                    .mark_line(point=True, color="#3aa76d")
                    .encode(x=alt.X("crawl_date:T", title=None),
                            y=alt.Y("best_price:Q", title="Daily best (USD)", scale=alt.Scale(zero=False)),
                            tooltip=[alt.Tooltip("crawl_date:T", title="Crawl date"),
                                     alt.Tooltip("best_price:Q", title="Best", format="$,.0f"),
                                     alt.Tooltip("best_source:N", title="At")])
                    .properties(height=220)
                )
                st.altair_chart(chart, width="stretch")
    st.caption("Prices are the lowest listing per source at the latest crawl, "
               "including fees where the source indicates. Verify at the source before buying.")


def games_table(priced: pd.DataFrame, changes: pd.DataFrame, spark: pd.DataFrame) -> int | None:
    """All-games table with sparklines; click a row to load that match."""
    g = priced.merge(changes[["match_number", "change_pct"]], on="match_number", how="left") \
        if len(changes) else priced.assign(change_pct=None)
    g = g.merge(spark, on="match_number", how="left") if len(spark) else g.assign(trend=None)
    g = g.assign(chart_stage=g["stage"].map(chart_stage),
                 best_source_name=g["best_source"].map(lambda s: SOURCE_DISPLAY_NAMES.get(s, s)))
    show = g[["display_name", "chart_stage", "match_date", "city", "best_price",
              "best_source_name", "trend", "change_pct", "sources_with_price", "total_inventory"]]
    event = st.dataframe(
        show, hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row",
        column_config={
            "display_name": st.column_config.TextColumn("Game", width="large"),
            "chart_stage": st.column_config.TextColumn("Stage"),
            "match_date": st.column_config.DateColumn("Date", format="MMM D"),
            "city": st.column_config.TextColumn("City"),
            "best_price": st.column_config.NumberColumn("Best price", format="$%,.0f"),
            "best_source_name": st.column_config.TextColumn("At"),
            "trend": st.column_config.LineChartColumn("Trend", width="medium"),
            "change_pct": st.column_config.NumberColumn("Since first crawl", format="%+.1f%%"),
            "sources_with_price": st.column_config.NumberColumn("Sources"),
            "total_inventory": st.column_config.NumberColumn("Listings", format="%,d"),
        },
    )
    rows = event.selection.rows if event and event.selection else []
    return int(g.iloc[rows[0]]["match_number"]) if rows else None


def page_matches(ctx: dict) -> None:
    st.header("Matches")
    matches, priced = ctx["matches"], ctx["priced"]
    if matches.empty:
        st.info("No matches under the current filters. Widen the source, stage, city, or team filters in the sidebar.")
        return
    sort = st.segmented_control("Sort games", ["Kickoff", "Cheapest", "Biggest drop"], default="Kickoff")
    work = priced if len(priced) else matches
    if sort == "Cheapest" and "best_price" in work:
        work = work.sort_values("best_price", na_position="last")
    elif sort == "Biggest drop" and len(ctx["changes"]):
        work = work.merge(ctx["changes"][["match_number", "change_pct"]], on="match_number",
                          how="left", suffixes=("", "_c")).sort_values("change_pct", na_position="last")
    labels = work["display_name"].fillna("Match").tolist()
    label_to_match = dict(zip(labels, work["match_number"]))

    if st.session_state.get("_pending_match") in label_to_match.values():
        pending = [k for k, v in label_to_match.items() if v == st.session_state["_pending_match"]][0]
        st.session_state["match_picker"] = pending
        st.session_state["_pending_match"] = None
    if st.session_state.get("match_picker") not in label_to_match:
        st.session_state["match_picker"] = labels[0]
    picked = st.selectbox("Game", labels, key="match_picker")
    m = matches[matches["match_number"] == label_to_match[picked]].iloc[0]
    render_match_card(m, ctx["source_prices"], ctx["changes"], priced, ctx["sources"])

    st.subheader("All games")
    st.caption("Tick a row's checkbox to load that match above. Trend = daily best price across sources.")
    sort_frame = work if sort in ("Cheapest", "Biggest drop") else priced
    picked_from_table = games_table(sort_frame if len(sort_frame) else matches,
                                    ctx["changes"], ctx["sparklines"]) if len(priced) else None
    if picked_from_table and picked_from_table != int(m.match_number):
        st.session_state["_pending_match"] = picked_from_table
        st.rerun()


def page_market(ctx: dict) -> None:
    st.header("Market")
    priced, trends = ctx["priced"], ctx["market_trends"]
    if priced.empty:
        st.info("No priced matches under the current filters.")
        return
    cheapest = priced.loc[priced["best_price"].idxmin()]
    median_now = priced["best_price"].median()
    median_first = trends.iloc[0]["median_price"] if len(trends) else None
    delta = (f"{(median_now - median_first) / median_first * 100:+.1f}% since {trends.iloc[0]['crawl_date']:%b %-d}"
             if median_first else None)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cheapest game", usd(cheapest["best_price"]))
    c2.metric("Median game price", usd(median_now), delta, delta_color="inverse")
    c3.metric("Games tracked", f"{len(priced)}")
    multi = int((priced["sources_with_price"] >= 2).sum())
    c4.metric("Multi-source coverage", f"{multi}/{len(priced)}")
    st.caption(f"Cheapest: **{cheapest['display_name']}** at "
               f"{SOURCE_DISPLAY_NAMES.get(cheapest['best_source'], cheapest['best_source'])} "
               f"({usd(cheapest['best_price'])}). Median delta counts from the first crawl day.")

    st.subheader("Market price trend")
    st.caption("Solid = median game each crawl day, dashed = average, dotted = cheapest game. "
               "The most expensive game (the Final, ~$9k) is in the tooltip only — plotting it "
               "would flatten everything else. Drag to zoom.")
    if len(trends):
        t = trends.assign(crawl_date=pd.to_datetime(trends["crawl_date"]))
        med = (alt.Chart(t).mark_line(point=True, color="#3aa76d")
               .encode(x=alt.X("crawl_date:T", title=None), y=alt.Y("median_price:Q", title="Price (USD)", scale=alt.Scale(zero=False)),
                       tooltip=[alt.Tooltip("crawl_date:T", title="Crawl date"),
                                alt.Tooltip("median_price:Q", title="Median", format="$,.0f"),
                                alt.Tooltip("avg_price:Q", title="Average", format="$,.0f"),
                                alt.Tooltip("min_price:Q", title="Cheapest", format="$,.0f"),
                                alt.Tooltip("max_price:Q", title="Most expensive", format="$,.0f")]))
        avg = (alt.Chart(t).mark_line(strokeDash=[5, 4], color="#9db2c3")
               .encode(x="crawl_date:T", y=alt.Y("avg_price:Q", title="Price (USD)")))
        lo = (alt.Chart(t).mark_line(strokeDash=[2, 3], color="#7bd79e", opacity=0.8)
              .encode(x="crawl_date:T", y=alt.Y("min_price:Q", title="Price (USD)")))
        st.altair_chart((med + avg + lo).properties(height=280).interactive(), width="stretch")

    st.subheader("Price by source")
    overview = wh.source_overview(ctx["sources"])
    if len(overview):
        chart = (alt.Chart(overview.assign(name=overview["source"].map(
                    lambda s: SOURCE_DISPLAY_NAMES.get(s, s))))
                 .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                 .encode(x=alt.X("name:N", sort="y", title=None),
                         y=alt.Y("median_price:Q", title="Median lowest price (USD)"),
                         color=alt.Color("name:N", legend=None,
                                         scale=alt.Scale(domain=[SOURCE_DISPLAY_NAMES.get(s, s) for s in SOURCE_COLORS],
                                                         range=list(SOURCE_COLORS.values()))),
                         tooltip=[alt.Tooltip("name:N", title="Source"),
                                  alt.Tooltip("median_price:Q", title="Median", format="$,.0f"),
                                  alt.Tooltip("min_price:Q", title="Cheapest", format="$,.0f"),
                                  alt.Tooltip("events_with_price:Q", title="Events priced")])
                 .properties(height=250))
        st.altair_chart(chart, width="stretch")
        st.dataframe(
            overview[["source", "events_with_price", "total_events", "min_price",
                      "median_price", "avg_price", "max_price", "total_inventory"]],
            hide_index=True, width="stretch",
            column_config={
                "source": st.column_config.TextColumn("Source"),
                "min_price": st.column_config.NumberColumn("Cheapest", format="$%,.0f"),
                "median_price": st.column_config.NumberColumn("Median", format="$%,.0f"),
                "avg_price": st.column_config.NumberColumn("Average", format="$%,.0f"),
                "max_price": st.column_config.NumberColumn("Most expensive", format="$%,.0f"),
                "total_inventory": st.column_config.ProgressColumn(
                    "Listings", min_value=0,
                    max_value=float(overview["total_inventory"].max() or 1), format="%d"),
            })

    st.subheader("Price by stage")
    stage_df = priced.assign(chart_stage=priced["stage"].map(chart_stage)).groupby(
        "chart_stage", as_index=False).agg(avg_price=("best_price", "mean"), games=("best_price", "size"))
    st.altair_chart(
        (alt.Chart(stage_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
         .encode(x=alt.X("chart_stage:N", sort=STAGE_CHART_ORDER, title=None),
                 y=alt.Y("avg_price:Q", title="Avg best price (USD)"),
                 color=alt.Color("chart_stage:N", legend=None, scale=alt.Scale(scheme="greens")),
                 tooltip=["chart_stage", alt.Tooltip("avg_price:Q", format="$,.0f"), "games"])
         .properties(height=240)),
        width="stretch")

    st.subheader("Price by city")
    city_df = priced.dropna(subset=["city"]).groupby("city", as_index=False).agg(
        avg_price=("best_price", "mean"), min_price=("best_price", "min"),
        games=("best_price", "size")).sort_values("avg_price")
    st.altair_chart(
        (alt.Chart(city_df).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
         .encode(y=alt.Y("city:N", sort="x", title=None),
                 x=alt.X("avg_price:Q", title="Avg best price (USD)"),
                 color=alt.Color("avg_price:Q", legend=None, scale=alt.Scale(scheme="redyellowgreen", reverse=True)),
                 tooltip=["city", alt.Tooltip("avg_price:Q", title="Avg", format="$,.0f"),
                          alt.Tooltip("min_price:Q", title="Cheapest", format="$,.0f"), "games"])
         .properties(height=520)),
        width="stretch")
    with st.expander("Map view — average price by host city"):
        import plotly.express as px
        mdf = city_df[city_df["city"].isin(_VENUE_COORDS)].copy()
        if len(mdf):
            mdf["lat"] = mdf["city"].map(lambda c: _VENUE_COORDS[c][0])
            mdf["lon"] = mdf["city"].map(lambda c: _VENUE_COORDS[c][1])
            scatter_map = getattr(px, "scatter_map", None) or px.scatter_mapbox
            map_kwargs = {} if hasattr(px, "scatter_map") else {"mapbox_style": "open-street-map"}
            fig = scatter_map(mdf, lat="lat", lon="lon", size="games", color="avg_price",
                              hover_name="city", color_continuous_scale="RdYlGn_r",
                              size_max=28, zoom=2.5, center={"lat": 37, "lon": -98}, **map_kwargs)
            fig.update_layout(height=460, margin=dict(t=10, b=10, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)


def page_deals(ctx: dict) -> None:
    st.header("Deals — where is each match cheapest?")
    st.caption("Savings compare the cheapest and most expensive source for the same match "
               "at the latest crawl. Drops compare the daily best price, first crawl vs latest.")
    priced, changes = ctx["priced"], ctx["changes"]
    view = st.segmented_control("View", ["Cross-source savings", "Biggest drops", "Price distribution"],
                                default="Cross-source savings") or "Cross-source savings"
    if view == "Cross-source savings":
        deals = priced[priced["sources_with_price"] >= 2].sort_values("savings_vs_worst", ascending=False)
        if deals.empty:
            st.info("Need 2+ sources with overlapping events for comparison.")
            return
        deals = deals.assign(
            best_source_name=deals["best_source"].map(lambda s: SOURCE_DISPLAY_NAMES.get(s, s)),
            short_name=deals["display_name"].astype(str).str.replace(r"\s*\(.*\)$", "", regex=True))
        top = deals.head(15)
        st.altair_chart(
            (alt.Chart(top).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
             .encode(y=alt.Y("short_name:N", sort="-x", title=None,
                             axis=alt.Axis(labelLimit=260)),
                     x=alt.X("savings_vs_worst:Q", title="Savings vs most expensive source (USD)"),
                     color=alt.Color("best_source_name:N", title="Cheapest at",
                                     scale=alt.Scale(domain=[SOURCE_DISPLAY_NAMES.get(s, s) for s in SOURCE_COLORS],
                                                      range=list(SOURCE_COLORS.values()))),
                     tooltip=["display_name", alt.Tooltip("best_price:Q", title="Best", format="$,.0f"),
                              alt.Tooltip("worst_price:Q", title="Worst", format="$,.0f"),
                              alt.Tooltip("savings_vs_worst:Q", title="Save", format="$,.0f")])
             .properties(height=420)),
            width="stretch")
        st.dataframe(
            deals[["display_name", "stage", "match_date", "city", "best_price", "best_source_name",
                   "worst_price", "savings_vs_worst"]],
            hide_index=True, width="stretch",
            column_config={
                "display_name": st.column_config.TextColumn("Game", width="large"),
                "stage": st.column_config.TextColumn("Stage"),
                "match_date": st.column_config.DateColumn("Date", format="MMM D"),
                "city": st.column_config.TextColumn("City"),
                "best_price": st.column_config.NumberColumn("Best", format="$%,.0f"),
                "best_source_name": st.column_config.TextColumn("At"),
                "worst_price": st.column_config.NumberColumn("Worst", format="$%,.0f"),
                "savings_vs_worst": st.column_config.ProgressColumn(
                    "Save", min_value=0, max_value=float(deals["savings_vs_worst"].max() or 1),
                    format="$%,.0f"),
            })
    elif view == "Biggest drops":
        if changes.empty:
            st.info("No price-change data under the current filters.")
            return
        d = changes.merge(priced[["match_number", "display_name", "stage", "city"]],
                          on="match_number", how="inner").sort_values("change_pct")
        show = pd.concat([d.head(12), d.tail(6)]).sort_values("change_pct").assign(
            short_name=lambda x: x["display_name"].astype(str).str.replace(r"\s*\(.*\)$", "", regex=True))
        st.altair_chart(
            (alt.Chart(show).mark_bar(cornerRadius=3)
             .encode(y=alt.Y("short_name:N", sort="x", title=None, axis=alt.Axis(labelLimit=280)),
                     x=alt.X("change_pct:Q", title="Change since first crawl (%)"),
                     color=alt.condition(alt.datum.change_pct < 0, alt.value("#3fb950"), alt.value("#e05d5d")),
                     tooltip=["display_name",
                              alt.Tooltip("first_price:Q", title="First", format="$,.0f"),
                              alt.Tooltip("latest_price:Q", title="Latest", format="$,.0f"),
                              alt.Tooltip("change_pct:Q", title="Change", format="+.1f")])
             .properties(height=460)),
            width="stretch")
        st.caption("Green = cheaper for buyers. Daily best price, first crawl date vs latest.")
        st.dataframe(
            d[["display_name", "stage", "city", "first_price", "latest_price", "change_dollars", "change_pct"]],
            hide_index=True, width="stretch",
            column_config={
                "display_name": st.column_config.TextColumn("Game", width="large"),
                "first_price": st.column_config.NumberColumn("First crawl", format="$%,.0f"),
                "latest_price": st.column_config.NumberColumn("Latest", format="$%,.0f"),
                "change_dollars": st.column_config.NumberColumn("Change $", format="$%+.0f"),
                "change_pct": st.column_config.NumberColumn("Change %", format="%+.1f%%"),
            })
    else:
        sp = ctx["source_prices"].dropna(subset=["lowest_price"]).copy()
        sp["name"] = sp["source"].map(lambda s: SOURCE_DISPLAY_NAMES.get(s, s))
        if sp.empty:
            st.info("No priced events under the current filters.")
            return
        cap = float(sp["lowest_price"].quantile(0.98))
        st.caption(f"Distribution of current lowest prices per source (capped at the 98th percentile, {usd(cap)}).")
        st.altair_chart(
            (alt.Chart(sp[sp["lowest_price"] <= cap]).mark_bar(opacity=0.75)
             .encode(x=alt.X("lowest_price:Q", bin=alt.Bin(maxbins=28), title="Lowest price (USD)"),
                     y=alt.Y("count()", title="Events"),
                     color=alt.Color("name:N", title="Source",
                                     scale=alt.Scale(domain=[SOURCE_DISPLAY_NAMES.get(s, s) for s in SOURCE_COLORS],
                                                      range=list(SOURCE_COLORS.values()))),
                     tooltip=["name", "count()"])
             .properties(height=300).interactive()),
            width="stretch")


def page_history(ctx: dict) -> None:
    st.header("History")
    matches = ctx["matches"]
    if matches.empty:
        st.info("No matches under the current filters.")
        return
    hist_all = ctx["price_trends_table"]
    label_to_match = dict(zip(matches["display_name"].fillna("Match"), matches["match_number"]))
    picked = st.selectbox("Game", list(label_to_match.keys()), key="history_picker")
    match_no = int(label_to_match[picked])
    m = matches[matches["match_number"] == match_no].iloc[0]
    gran = st.segmented_control("Group by", ["Day", "Hour"], default="Day")
    hist = hist_all[(hist_all["match_number"] == match_no)
                    & hist_all["source"].isin(ctx["sources"])].copy()
    if hist.empty:
        st.info("No price history for this game under the current source filter.")
        return
    hist["crawl_ts_utc"] = pd.to_datetime(hist["crawl_ts_utc"])
    hist["bucket"] = hist["crawl_ts_utc"].dt.floor("h" if gran == "Hour" else "D")
    grouped = (hist.sort_values("crawl_ts_utc")
               .groupby(["source", "bucket"], as_index=False).last(numeric_only=False))
    daily = wh.daily_best(match_no, ctx["sources"])
    x, y, z, w = st.columns(4)
    x.metric("Crawl days observed", f"{hist['crawl_date'].nunique()}")
    y.metric("Lowest ever", usd(hist["lowest_price"].min()))
    z.metric("Latest best", usd(daily.iloc[-1]["best_price"]) if len(daily) else "—")
    ch = ctx["changes"][ctx["changes"]["match_number"] == match_no] if len(ctx["changes"]) else ctx["changes"]
    w.metric("Since first crawl", f"{float(ch.iloc[0].change_pct):+.1f}%" if len(ch) else "—")

    st.caption("Lowest price per source over time (solid, colored) with the tournament-wide "
               "daily median game price (dashed) for scale. Drag to zoom.")
    g2 = grouped.assign(name=grouped["source"].map(lambda s: SOURCE_DISPLAY_NAMES.get(s, s)))
    lines = (alt.Chart(g2).mark_line(point=True)
             .encode(x=alt.X("bucket:T", title=None),
                     y=alt.Y("lowest_price:Q", title="Lowest price (USD)", scale=alt.Scale(zero=False)),
                     color=alt.Color("name:N", title="Source",
                                     scale=alt.Scale(domain=[SOURCE_DISPLAY_NAMES.get(s, s) for s in SOURCE_COLORS],
                                                      range=list(SOURCE_COLORS.values()))),
                     tooltip=[alt.Tooltip("bucket:T", title="Crawl"),
                              alt.Tooltip("name:N", title="Source"),
                              alt.Tooltip("lowest_price:Q", title="Lowest", format="$,.0f"),
                              alt.Tooltip("inventory_count:Q", title="Listings")])
             .properties(height=300))
    med = ctx["market_trends"]
    if len(med):
        ref = (alt.Chart(med.assign(crawl_date=pd.to_datetime(med["crawl_date"])))
               .mark_line(strokeDash=[5, 4], color="#9db2c3")
               .encode(x="crawl_date:T", y="median_price:Q"))
        lines = lines + ref
    st.altair_chart(lines.interactive(), width="stretch")

    st.subheader("Days to kickoff vs price")
    st.caption("Daily best price as kickoff approaches. Use the picker to compare a few games.")
    priced = ctx["priced"].dropna(subset=["event_start_local"])
    default_labels = priced.nsmallest(6, "best_price")["display_name"].tolist()
    chosen = st.multiselect("Games to compare", priced["display_name"].tolist(),
                            default=[x for x in default_labels if x in set(priced["display_name"])][:6])
    if chosen:
        want = priced[priced["display_name"].isin(chosen)]
        d = hist_all[hist_all["match_number"].isin(want["match_number"])
                     & hist_all["source"].isin(ctx["sources"])].copy()
        d = d.dropna(subset=["lowest_price"])
        starts = want.set_index("match_number")["event_start_local"]
        d["game_date"] = pd.to_datetime(d["match_number"].map(starts)).dt.date
        d["days_out"] = [(g - pd.to_datetime(c).date()).days for g, c in zip(d["game_date"], d["crawl_ts_utc"])]
        d = d[d["days_out"] >= 0].groupby(["display_name", "days_out"], as_index=False)["lowest_price"].min()
        if len(d):
            st.altair_chart(
                (alt.Chart(d).mark_line(point=True)
                 .encode(x=alt.X("days_out:Q", title="Days until kickoff", scale=alt.Scale(reverse=True)),
                         y=alt.Y("lowest_price:Q", title="Daily best (USD)", scale=alt.Scale(zero=False)),
                         color=alt.Color("display_name:N", title="Game"),
                         tooltip=["display_name", "days_out",
                                  alt.Tooltip("lowest_price:Q", title="Best", format="$,.0f")])
                 .properties(height=300).interactive()),
                width="stretch")

    st.subheader(f"Individual listings — {picked}")
    st.caption(
        f"Tickets most recently listed for **{picked}** (the game selected at the top "
        "of this page). This section does not use the multi-game comparison above."
    )
    candidates = ctx["source_prices"][ctx["source_prices"]["match_number"] == match_no]
    if candidates.empty:
        st.info(f"No source prices for {picked} under the current filters.")
        return
    src = st.segmented_control(
        f"Marketplace for {picked}", candidates["source"].tolist(),
        default=candidates.iloc[0]["source"],
        format_func=lambda s: SOURCE_DISPLAY_NAMES.get(s, s), key="listing_source_seg")
    if src is None:
        st.info(f"Pick a marketplace to see its listings for {picked}.")
        return
    row = candidates[candidates["source"] == src].iloc[0]
    listings = wh.listing_distribution(row["source"], row["event_id_external"])
    source_name = SOURCE_DISPLAY_NAMES.get(src, src)
    if listings.empty:
        st.info(f"No individual listings found for {picked} on {source_name}.")
        return
    latest_crawl = pd.to_datetime(listings["crawl_ts_utc"].max())
    st.markdown(
        f"**Showing {len(listings):,} listings for {picked} on {source_name}** · "
        f"latest crawl {latest_crawl:%b %-d, %Y, %-I:%M %p} UTC · "
        f"cheapest {usd(listings['price'].min())}."
    )
    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.dataframe(
            listings[["section", "row", "price", "deal_score", "deal_label"]],
            hide_index=True, width="stretch", height=360,
            column_config={
                "price": st.column_config.NumberColumn("Price", format="$%,.0f"),
                "deal_score": st.column_config.ProgressColumn("Deal score", min_value=0, max_value=10, format="%.1f"),
            })
    with col_r:
        hist_chart = (alt.Chart(listings).mark_bar(color=SOURCE_COLORS.get(src, "#3aa76d"),
                                                   cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                      .encode(x=alt.X("price:Q", bin=alt.Bin(maxbins=18), title="Listing price (USD)"),
                              y=alt.Y("count()", title="Listings"), tooltip=["count()"])
                      .properties(height=170))
        st.altair_chart(hist_chart, width="stretch")
        sec = listings.dropna(subset=["section"]).groupby("section", as_index=False).agg(
            median_price=("price", "median"), listings=("price", "size")).sort_values("median_price")
        if len(sec) > 1:
            st.altair_chart(
                (alt.Chart(sec.head(12)).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4,
                                                  color=SOURCE_COLORS.get(src, "#3aa76d"))
                 .encode(y=alt.Y("section:N", sort="x", title=None),
                         x=alt.X("median_price:Q", title="Median by section (USD)"),
                         tooltip=["section", alt.Tooltip("median_price:Q", format="$,.0f"), "listings"])
                 .properties(height=190)),
                width="stretch")


# ── Shell: title, sidebar filters, page dispatch ─────────────────────────
sources_all = wh.sources()
st.title("⚽ FIFA 2026 Ticket Tracker")
trend_dates = _market_trends(tuple(sources_all), VERSION)
first_crawl = f"{pd.to_datetime(trend_dates.iloc[0]['crawl_date']):%b %-d, %Y}" if len(trend_dates) else "—"
last_crawl = f"{pd.to_datetime(trend_dates.iloc[-1]['crawl_date']):%b %-d, %Y}" if len(trend_dates) else "—"
st.caption(
    f"Data: five resale marketplaces via the ticket-scraper semantic layer, "
    f"crawled {first_crawl} → {last_crawl} ({len(trend_dates)} crawl days). "
    "Resale prices for your own decision — lines move; verify at the source before buying."
)

page = st.sidebar.radio("Page", ["Matches", "Market", "Deals", "History"])
st.sidebar.markdown("---")
st.sidebar.markdown("### Filters")
selected_sources = st.sidebar.multiselect(
    "Ticket sources", sources_all, default=sources_all,
    format_func=lambda s: SOURCE_DISPLAY_NAMES.get(s, s),
    help="Which marketplace(s) to include — best prices recompute over the selected sources.")
stage_options = ["All Stages"] + [s for s in STAGE_ORDER
                                  if s in set(wh.load("match_prices")["stage"].dropna().unique())]
selected_stage = st.sidebar.selectbox("Tournament stage", stage_options)
stage_filter = None if selected_stage == "All Stages" else selected_stage
selected_city = st.sidebar.selectbox("Host city", ["All Cities"] + wh.cities())
city_filter = None if selected_city == "All Cities" else selected_city
selected_team = st.sidebar.selectbox("Team", ["All Teams"] + wh.teams())
team_filter = None if selected_team == "All Teams" else selected_team
st.sidebar.markdown("---")
st.sidebar.caption(f"Warehouse: published Parquet in `{wh.warehouse_dir().name}/`")
st.sidebar.caption(f"Crawl days: {len(trend_dates)} · Sources: {len(sources_all)}")

if not selected_sources:
    st.info("Select at least one ticket source in the sidebar.")
    st.stop()

src_key = tuple(sorted(selected_sources))
ctx = {
    "sources": list(src_key),
    "matches": _match_prices(src_key, stage_filter, city_filter, team_filter, VERSION),
    "source_prices": _source_prices(src_key, VERSION),
    "price_trends_table": _price_trends_table(VERSION),
    "market_trends": _market_trends(src_key, VERSION),
    "changes": _price_changes(src_key, VERSION),
    "sparklines": _sparklines(src_key, VERSION),
}
ctx["priced"] = ctx["matches"][ctx["matches"]["best_price"].notna()]

{"Matches": page_matches, "Market": page_market,
 "Deals": page_deals, "History": page_history}[page](ctx)

st.markdown("---")
st.caption("Prices are the lowest available listing per event from each source, "
           "including fees where the source indicates. Data refreshes when the "
           "pipeline runs (crawl → dbt → publish).")
