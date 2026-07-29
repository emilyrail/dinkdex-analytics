"""Individual player profiles."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from services.analytics_service import AnalyticsService
from services.event_service import EventService
from services.player_service import PlayerService
from utils.formatting import format_elo
from analytics.elo import PROVISIONAL_BADGE, PROVISIONAL_DEFINITION, is_provisional
from utils.session import bootstrap_session

bootstrap_session()
init_db(st.session_state.db_path)

GREEN_PRIMARY = "#609078"
GREEN_MID = "#3F8A57"
NEUTRAL_LIGHT = "#EFE9DD"
GREY_MID = "#7A7A7A"
GREY_DARK = "#3D3D3D"
DUSTY_RED = "#8B4A4A"
LOSS_GREY = "#A8A8A8"


def _fmt_date(value) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _fmt_elo_delta(value) -> str:
    v = float(value)
    rounded = int(round(v))
    if abs(v - rounded) < 0.05:
        text = f"{rounded:+d}"
    else:
        text = f"{v:+.1f}"
    if v > 0:
        return f"▲ {text}"
    if v < 0:
        return f"▼ {text}"
    return f"• {text}"


def _style_elo_delta(series: pd.Series) -> list[str]:
    styles = []
    for raw in series:
        text = str(raw)
        if text.startswith("▲"):
            styles.append(f"color: {GREEN_MID}; font-weight: 600;")
        elif text.startswith("▼"):
            styles.append("color: #B85C5C; font-weight: 600;")
        else:
            styles.append(f"color: {GREY_MID};")
    return styles


def _render_recent_games(player_rows: pd.DataFrame) -> None:
    if player_rows.empty:
        st.caption("No completed games yet.")
        return
    recent_view = player_rows.copy()
    recent_view["Date"] = recent_view["event_date"].map(_fmt_date)
    recent_view["Result"] = recent_view["won"].map(lambda w: "W" if bool(w) else "L")
    recent_view["Teams"] = recent_view.apply(
        lambda r: (
            f"{r['player']} / {r['partner_name']} vs {r['opp1_name']} / {r['opp2_name']}"
        ),
        axis=1,
    )
    recent_view["Score"] = (
        recent_view["points_for"].astype(int).astype(str)
        + "-"
        + recent_view["points_against"].astype(int).astype(str)
    )
    recent_view["Point Diff."] = recent_view["point_diff"].astype(int)
    recent_view["Elo Δ"] = recent_view["elo_delta"].map(_fmt_elo_delta)
    display = recent_view[["Date", "Teams", "Result", "Score", "Point Diff.", "Elo Δ"]]
    styled = display.style.apply(_style_elo_delta, subset=["Elo Δ"], axis=0)
    st.dataframe(styled, use_container_width=True, hide_index=True)


st.title("Player Profiles")
analytics = AnalyticsService()
event_service = EventService()
player_service = PlayerService()
players = player_service.list_players(active_only=False)
if not players:
    st.info("Add players first.")
    st.stop()

SHOW_ALL = "__show_all__"
games_by_player = player_service.games_played_counts()
options = {
    p.id: (
        f"{p.label} ({format_elo(p.current_elo)})"
        + (
            f" · {PROVISIONAL_BADGE}"
            if is_provisional(games_by_player.get(p.id, 0))
            else ""
        )
    )
    for p in players
}
selected_profile = st.selectbox(
    "Player",
    options=[SHOW_ALL] + list(options.keys()),
    format_func=lambda i: "Show All (players this week)" if i == SHOW_ALL else options[i],
)

events = event_service.list_events()
event_options = {e.id: f"{e.name} ({e.event_date})" for e in events}

if selected_profile == SHOW_ALL:
    scope = st.radio(
        "Match scope",
        options=["event", "all_time"],
        format_func=lambda v: "This week / selected event" if v == "event" else "All-time",
        horizontal=True,
        key="show_all_scope",
    )

    if scope == "event":
        if not event_options:
            st.warning("No events yet.")
            st.stop()
        default_event = st.session_state.active_event_id
        ids = list(event_options.keys())
        default_idx = ids.index(default_event) if default_event in event_options else 0
        event_id = st.selectbox(
            "Event",
            options=ids,
            index=default_idx,
            format_func=lambda i: event_options[i],
            key="show_all_event",
        )
        event = event_service.get_event(event_id)
        if event is None:
            st.warning("Event not found.")
            st.stop()
        attendee_ids = event_service.get_attendee_ids(event_id)
        if not attendee_ids:
            st.info("No attendees selected for this event yet.")
            st.stop()
        attendee_set = set(attendee_ids)
        wl = analytics.event_attendee_win_loss(event_id)
        if wl.empty:
            wl = pd.DataFrame(
                {
                    "player_id": attendee_ids,
                    "player": [next((p.label for p in players if p.id == pid), str(pid)) for pid in attendee_ids],
                    "wins": [0] * len(attendee_ids),
                    "losses": [0] * len(attendee_ids),
                }
            )
        else:
            wl = wl[wl["player_id"].astype(int).isin(attendee_set)].copy()
        st.subheader(f"Show All · {event.name} ({event.event_date})")
        st.caption("Win/Loss donuts for attendees in the selected event.")
        hm = analytics.event_attendee_point_diff_heatmap(event_id)
        heatmap_title = "Event avg point differential vs opponents"
    else:
        snapshot = analytics.all_time_player_snapshot(min_games=1)
        if snapshot.empty:
            st.info("No completed games yet.")
            st.stop()
        wl = snapshot[["player_id", "player", "wins", "losses"]].copy()
        st.subheader("Show All · All-time")
        st.caption("Win/Loss donuts for players with completed games.")
        hm = analytics.all_time_point_diff_heatmap()
        heatmap_title = "All-time avg point differential vs opponents"

    wl = wl.sort_values("player", key=lambda s: s.str.lower()).reset_index(drop=True)
    n = len(wl)
    cols_per_row = min(6, max(1, n))
    for row_start in range(0, n, cols_per_row):
        row_cols = st.columns(cols_per_row)
        chunk = wl.iloc[row_start : row_start + cols_per_row]
        for idx, (_, r) in enumerate(chunk.iterrows()):
            with row_cols[idx]:
                d = pd.DataFrame(
                    [
                        {"result": "Wins", "count": int(r["wins"])},
                        {"result": "Losses", "count": int(r["losses"])},
                    ]
                )
                d["result"] = pd.Categorical(d["result"], categories=["Wins", "Losses"], ordered=True)
                total = int(r["wins"]) + int(r["losses"])
                if total == 0:
                    d = pd.DataFrame(
                        [
                            {"result": "Wins", "count": 0},
                            {"result": "Losses", "count": 1},
                        ]
                    )
                    d["result"] = pd.Categorical(d["result"], categories=["Wins", "Losses"], ordered=True)
                fig = px.pie(
                    d,
                    names="result",
                    values="count",
                    hole=0.55,
                    color="result",
                    color_discrete_map={"Wins": GREEN_PRIMARY, "Losses": LOSS_GREY},
                    category_orders={"result": ["Wins", "Losses"]},
                )
                fig.update_traces(
                    textinfo="percent" if total > 0 else "none",
                    textfont=dict(color=GREY_DARK, size=12),
                    hovertemplate="%{label}: %{value}<extra></extra>",
                )
                fig.update_layout(
                    title=dict(
                        text=f"{r['player']} ({int(r['wins'])}-{int(r['losses'])})",
                        font=dict(size=12),
                    ),
                    paper_bgcolor=NEUTRAL_LIGHT,
                    plot_bgcolor=NEUTRAL_LIGHT,
                    font_color=GREY_DARK,
                    margin=dict(l=4, r=4, t=28, b=4),
                    showlegend=False,
                    height=220,
                )
                st.plotly_chart(fig, use_container_width=True)

    st.subheader(heatmap_title)
    if hm.empty:
        st.caption("No completed matches yet for heat map.")
    else:
        names = sorted(wl["player"].tolist(), key=str.lower)
        matrix = pd.DataFrame(index=names, columns=names, dtype=float)
        name_by_id = {int(r["player_id"]): str(r["player"]) for _, r in wl.iterrows()}
        for _, r in hm.iterrows():
            if "player" in hm.columns and "opponent" in hm.columns:
                p = str(r["player"])
                o = str(r["opponent"])
            else:
                p = name_by_id.get(int(r["player_id"]))
                o = name_by_id.get(int(r["opponent_id"]))
            if p is None or o is None or p not in matrix.index or o not in matrix.columns:
                continue
            matrix.loc[p, o] = float(r["avg_point_diff"])
        for nm in names:
            matrix.loc[nm, nm] = 0.0

        def _fmt_diff(value: float) -> str:
            if pd.isna(value):
                return ""
            rounded = round(float(value))
            if abs(float(value) - rounded) < 0.05:
                return f"{int(rounded):+d}"
            return f"{float(value):+.1f}"

        text_matrix = matrix.copy()
        for col in text_matrix.columns:
            text_matrix[col] = text_matrix[col].map(_fmt_diff)

        fig_hm = px.imshow(
            matrix,
            labels=dict(x="Opponent", y="Player", color="Avg point diff"),
            color_continuous_scale="RdYlGn",
            zmin=-11,
            zmax=11,
            aspect="auto",
        )
        fig_hm.update_traces(
            text=text_matrix.values,
            texttemplate="%{text}",
            textfont=dict(size=11, color="#1f1f1f"),
            hovertemplate="Player: %{y}<br>Opponent: %{x}<br>Avg diff: %{z:.2f}<extra></extra>",
        )
        fig_hm.update_layout(
            paper_bgcolor=NEUTRAL_LIGHT,
            plot_bgcolor=NEUTRAL_LIGHT,
            font_color=GREY_DARK,
            height=max(520, len(names) * 52),
        )
        st.plotly_chart(fig_hm, use_container_width=True)
    st.stop()

player_id = int(selected_profile)
player = next(p for p in players if p.id == player_id)
st.subheader(player.label)
games_played = games_by_player.get(player_id, 0)
status_badge = "Active" if player.active else "Inactive"
header_cols = st.columns([4, 2])
header_cols[0].caption(f"Elo {format_elo(player.current_elo)} · {status_badge}")
if is_provisional(games_played):
    header_cols[1].badge(
        PROVISIONAL_BADGE,
        icon=":material/new_releases:",
        color="orange",
        help=PROVISIONAL_DEFINITION,
    )

scope = st.radio(
    "Match scope",
    options=["all_time", "event"],
    format_func=lambda v: "All matches (all-time)" if v == "all_time" else "Selected event matches",
    horizontal=True,
    key=f"profile_scope_{player_id}",
)
filter_event_id: int | None = None
if scope == "event":
    if not event_options:
        st.warning("No events yet.")
        st.stop()
    default_event = st.session_state.active_event_id
    default_idx = 0
    ids = list(event_options.keys())
    if default_event in event_options:
        default_idx = ids.index(default_event)
    filter_event_id = st.selectbox(
        "Event",
        options=ids,
        index=default_idx,
        format_func=lambda i: event_options[i],
        key=f"profile_event_{player_id}",
    )
    st.caption(f"Showing stats for {event_options[filter_event_id]} only.")
else:
    st.caption("Showing all-time career stats.")

overview = analytics.player_overview(player_id, event_id=filter_event_id)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Games", overview["games"])
c2.metric("W-L", f"{overview['wins']}-{overview['losses']}")
c3.metric("Win %", f"{overview['win_pct'] * 100:.1f}%")
c4.metric("Point diff", overview["point_diff"])

if filter_event_id is None:
    all_snapshot = analytics.all_time_player_snapshot(min_games=1)
    player_snapshot = all_snapshot[all_snapshot["player_id"] == player_id]
    if not player_snapshot.empty:
        ps = player_snapshot.iloc[0]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Current streak", int(ps["current_streak"]))
        d2.metric("Longest win streak", int(ps["longest_win_streak"]))
        d3.metric("Avg points scored", f"{ps['avg_points_scored']:.1f}")
        d4.metric("Avg points allowed", f"{ps['avg_points_allowed']:.1f}")
else:
    event_rows = analytics.all_time_player_match_rows().query(
        "player_id == @player_id and event_id == @filter_event_id"
    )
    if not event_rows.empty:
        d1, d2, d3, d4 = st.columns(4)
        wins_seq = event_rows.sort_values(["match_order", "match_id"])["won"].astype(bool).tolist()
        streak = 0
        for w in reversed(wins_seq):
            if streak == 0:
                streak = 1 if w else -1
            elif (streak > 0 and w) or (streak < 0 and not w):
                streak += 1 if w else -1
            else:
                break
        longest = 0
        cur = 0
        for w in wins_seq:
            if w:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
        d1.metric("Current streak", streak)
        d2.metric("Longest win streak", longest)
        d3.metric("Avg points scored", f"{event_rows['points_for'].mean():.1f}")
        d4.metric("Avg points allowed", f"{event_rows['points_against'].mean():.1f}")

top_left, top_right = st.columns(2)

with top_left:
    if overview["games"] > 0:
        wl_df = [
            {"result": "Wins", "count": overview["wins"]},
            {"result": "Losses", "count": overview["losses"]},
        ]
        fig_wl = px.pie(
            wl_df,
            names="result",
            values="count",
            title="Win/Loss split",
            hole=0.45,
            color="result",
            color_discrete_map={"Wins": GREEN_PRIMARY, "Losses": LOSS_GREY},
        )
        fig_wl.update_layout(
            paper_bgcolor=NEUTRAL_LIGHT,
            plot_bgcolor=NEUTRAL_LIGHT,
            font_color=GREY_DARK,
        )
        fig_wl.update_traces(textinfo="percent", textfont=dict(size=14, color=GREY_DARK))
        st.plotly_chart(fig_wl, use_container_width=True)
    else:
        st.caption("No games yet for Win/Loss split.")

with top_right:
    elo_df = analytics.elo_timeline(player_id)
    if filter_event_id is not None and not elo_df.empty and "event_id" in elo_df.columns:
        elo_df = elo_df[elo_df["event_id"] == filter_event_id]
    if not elo_df.empty:
        fig = px.line(
            elo_df,
            x="created_at",
            y="elo",
            markers=True,
            title="Elo over time" + (" (event)" if filter_event_id else ""),
            labels={"created_at": "Match time", "elo": "Elo"},
        )
        fig.update_traces(line_color=GREEN_PRIMARY, marker_color=GREEN_MID)
        fig.update_traces(
            text=elo_df["elo"].round(1),
            textposition="top center",
            texttemplate="%{text}",
        )
        fig.update_layout(
            paper_bgcolor=NEUTRAL_LIGHT,
            plot_bgcolor=NEUTRAL_LIGHT,
            font_color=GREY_DARK,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No Elo history yet.")

left, right = st.columns(2)
with left:
    st.subheader("Best Partners")
    partners = analytics.partner_win_rates(player_id, min_games=1, event_id=filter_event_id)
    if partners.empty:
        st.caption("No partner games yet.")
    else:
        p = partners.copy()
        p["win_rate"] = (p["win_rate"] * 100).round(1)
        p["avg_margin"] = p["avg_margin"].round(1)
        p["Record"] = p.apply(lambda r: f"{int(r['wins'])}-{int(r['losses'])}", axis=1)
        st.dataframe(
            p[["partner", "games", "Record", "win_rate", "avg_margin"]].rename(
                columns={
                    "partner": "Partners",
                    "win_rate": "Win Rate %",
                    "avg_margin": "Avg Margin",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        fig_partner = px.bar(
            p.head(8),
            x="partner",
            y="win_rate",
            title="Partner win rate (%)",
            labels={"partner": "Partner", "win_rate": "Win rate %"},
            color_discrete_sequence=[GREEN_PRIMARY],
        )
        fig_partner.update_layout(
            paper_bgcolor=NEUTRAL_LIGHT,
            plot_bgcolor=NEUTRAL_LIGHT,
            font_color=GREY_DARK,
        )
        fig_partner.update_traces(texttemplate="%{y:.1f}", textposition="outside", cliponaxis=False)
        st.plotly_chart(fig_partner, use_container_width=True)

with right:
    st.subheader("Head-to-Head")
    h2h = analytics.head_to_head(player_id, event_id=filter_event_id)
    if h2h.empty:
        st.caption("No opponent data yet.")
    else:
        h = h2h.copy()
        h["win_rate"] = (h["win_rate"] * 100).round(1)
        h["avg_margin"] = h["avg_margin"].round(1)
        h["Record"] = h.apply(lambda r: f"{int(r['wins'])}-{int(r['losses'])}", axis=1)
        st.dataframe(
            h[["opponent", "games", "Record", "win_rate", "avg_margin"]].rename(
                columns={"opponent": "Opponent", "win_rate": "Win Rate %", "avg_margin": "Avg Margin"}
            ),
            use_container_width=True,
            hide_index=True,
        )
        top_opp = h.head(8).copy()
        stacked = top_opp.melt(
            id_vars=["opponent"],
            value_vars=["wins", "losses"],
            var_name="result",
            value_name="count",
        )
        stacked["result"] = stacked["result"].map({"wins": "Wins", "losses": "Losses"})
        fig_h2h = px.bar(
            stacked,
            x="opponent",
            y="count",
            color="result",
            title="Most-played opponents",
            labels={"opponent": "Opponent", "count": "Games", "result": ""},
            color_discrete_map={"Wins": GREEN_PRIMARY, "Losses": LOSS_GREY},
            category_orders={"opponent": top_opp["opponent"].tolist(), "result": ["Wins", "Losses"]},
        )
        fig_h2h.update_layout(
            paper_bgcolor=NEUTRAL_LIGHT,
            plot_bgcolor=NEUTRAL_LIGHT,
            font_color=GREY_DARK,
            barmode="stack",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        fig_h2h.update_traces(texttemplate="%{y}", textposition="inside", cliponaxis=False)
        st.plotly_chart(fig_h2h, use_container_width=True)

h2h_all = analytics.head_to_head(player_id, event_id=filter_event_id)
if h2h_all.empty:
    st.subheader("Toughest Opponents / Easiest Wins")
    st.caption("No opponent data yet.")
else:
    min_games = st.slider("Minimum games vs opponent", min_value=1, max_value=10, value=2)
    filtered = h2h_all[h2h_all["games"] >= min_games].copy()
    if filtered.empty:
        st.subheader("Toughest Opponents / Easiest Wins")
        st.caption("No opponents meet that minimum games threshold.")
    else:
        filtered["win_rate"] = (filtered["win_rate"] * 100).round(1)
        filtered["loss_rate"] = (100 - filtered["win_rate"]).round(1)
        filtered["avg_margin"] = filtered["avg_margin"].round(1)

        tough_col, easy_col = st.columns(2)

        with tough_col:
            st.subheader("Toughest Opponents")
            toughest = filtered.sort_values(["win_rate", "games"], ascending=[True, False]).head(8)
            toughest["Record"] = toughest.apply(
                lambda r: f"{int(r['wins'])}-{int(r['losses'])}",
                axis=1,
            )
            st.dataframe(
                toughest[["opponent", "games", "Record", "win_rate", "loss_rate", "avg_margin"]]
                .rename(
                    columns={
                        "win_rate": "win_rate %",
                        "loss_rate": "loss_rate %",
                        "avg_margin": "avg margin",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            fig_tough = px.bar(
                toughest.sort_values("loss_rate", ascending=False),
                x="opponent",
                y="loss_rate",
                title="Opponents you lose to most (%)",
                labels={"opponent": "Opponent", "loss_rate": "Loss rate %"},
                color_discrete_sequence=[DUSTY_RED],
            )
            fig_tough.update_layout(
                paper_bgcolor=NEUTRAL_LIGHT,
                plot_bgcolor=NEUTRAL_LIGHT,
                font_color=GREY_DARK,
            )
            fig_tough.update_traces(texttemplate="%{y:.1f}", textposition="outside", cliponaxis=False)
            st.plotly_chart(fig_tough, use_container_width=True)

        with easy_col:
            st.subheader("Easiest Wins")
            easiest = filtered.sort_values(["win_rate", "games"], ascending=[False, False]).head(8)
            easiest["Record"] = easiest.apply(
                lambda r: f"{int(r['wins'])}-{int(r['losses'])}",
                axis=1,
            )
            st.dataframe(
                easiest[["opponent", "games", "Record", "win_rate", "loss_rate", "avg_margin"]]
                .rename(
                    columns={
                        "win_rate": "win_rate %",
                        "loss_rate": "loss_rate %",
                        "avg_margin": "avg margin",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            fig_easy = px.bar(
                easiest.sort_values("win_rate", ascending=False),
                x="opponent",
                y="win_rate",
                title="Opponents you beat most (%)",
                labels={"opponent": "Opponent", "win_rate": "Win rate %"},
                color_discrete_sequence=[GREEN_PRIMARY],
            )
            fig_easy.update_layout(
                paper_bgcolor=NEUTRAL_LIGHT,
                plot_bgcolor=NEUTRAL_LIGHT,
                font_color=GREY_DARK,
            )
            fig_easy.update_traces(texttemplate="%{y:.1f}", textposition="outside", cliponaxis=False)
            st.plotly_chart(fig_easy, use_container_width=True)

st.subheader("Recent games")
rows = analytics.all_time_player_match_rows()
player_rows = rows[rows["player_id"] == player_id].copy()
if filter_event_id is not None:
    player_rows = player_rows[player_rows["event_id"] == filter_event_id]
player_rows = player_rows.sort_values(["event_date", "match_id"], ascending=[False, False]).head(10)
_render_recent_games(player_rows)
