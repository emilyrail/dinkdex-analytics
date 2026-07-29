"""All-time analytics charts and tables."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from services.analytics_service import AnalyticsService
from services.event_service import EventService
from services.player_service import PlayerService
from utils.session import bootstrap_session

bootstrap_session()
init_db(st.session_state.db_path)

st.title("Analytics")
analytics = AnalyticsService()
event_service = EventService()
player_service = PlayerService()

st.caption("All-time analytics across all completed matches.")

players = player_service.list_players(active_only=False)
player_labels = {p.id: p.label for p in players}
all_ids = [p.id for p in players]
games_played = player_service.games_played_counts()


def _default_include_ids() -> list[int]:
    """Default to anyone with at least one recorded completed game."""
    ids = [pid for pid in all_ids if games_played.get(pid, 0) > 0]
    return ids if ids else list(all_ids)


events = event_service.list_events()
event_labels = {
    event.id: f"{event.event_date} — {event.name}"
    for event in events
}


def _event_player_ids(event_id: int) -> list[int]:
    """Players with a recorded game in the event; attendees are the fallback."""
    match_rows = analytics.all_time_player_match_rows()
    if not match_rows.empty:
        played = (
            match_rows[match_rows["event_id"].astype(int) == int(event_id)]["player_id"]
            .astype(int)
            .drop_duplicates()
            .tolist()
        )
        played = [pid for pid in all_ids if pid in set(played)]
        if played:
            return played
    attendees = set(event_service.get_attendee_ids(int(event_id)))
    return [pid for pid in all_ids if pid in attendees]


with st.container(border=True):
    game_col, from_col, to_col = st.columns([2, 1, 1])
    selected_game_night = game_col.selectbox(
        "Start with players from game night",
        options=[None] + [event.id for event in events],
        format_func=lambda event_id: (
            "All players with recorded games"
            if event_id is None
            else event_labels[event_id]
        ),
        key="analytics_game_night_group",
    )
    applied_game_night = st.session_state.get("analytics_game_night_applied", "__unset__")
    if selected_game_night != applied_game_night:
        selected_players = (
            _default_include_ids()
            if selected_game_night is None
            else _event_player_ids(int(selected_game_night))
        )
        st.session_state["analytics_include_players_recorded"] = selected_players
        st.session_state["analytics_game_night_applied"] = selected_game_night

    start_date = from_col.date_input("From", value=None)
    end_date = to_col.date_input("To", value=None)

    min_col, include_col, exclude_col = st.columns([1, 2, 2])
    min_games = int(
        min_col.number_input("Min games played", min_value=1, value=3, step=1)
    )
    include_ids = include_col.multiselect(
        "Include players",
        options=all_ids,
        default=_default_include_ids(),
        format_func=lambda pid: player_labels.get(pid, str(pid)),
        key="analytics_include_players_recorded",
    )
    exclude_ids = exclude_col.multiselect(
        "Exclude players",
        options=all_ids,
        default=[],
        format_func=lambda pid: player_labels.get(pid, str(pid)),
    )

start_str = start_date.isoformat() if start_date else None
end_str = end_date.isoformat() if end_date else None
snapshot = analytics.all_time_player_snapshot(
    start_date=start_str,
    end_date=end_str,
    min_games=min_games,
)
progress = analytics.all_time_player_progress(start_date=start_str, end_date=end_str)
heatmap_df = analytics.all_time_point_diff_heatmap(start_date=start_str, end_date=end_str)

if snapshot.empty:
    st.info("No completed matches found for this filter.")
    st.stop()

visible_ids = [pid for pid in include_ids if pid not in set(exclude_ids)]
if visible_ids:
    snapshot = snapshot[snapshot["player_id"].isin(visible_ids)].copy()
    progress = progress[progress["player_id"].isin(visible_ids)].copy()
    heatmap_df = heatmap_df[
        heatmap_df["player_id"].isin(visible_ids) & heatmap_df["opponent_id"].isin(visible_ids)
    ].copy()

if snapshot.empty:
    st.info("No players left after include/exclude filters.")
    st.stop()

# Apply the same minimum-games eligibility used by Standings to Trends.
eligible_ids = set(snapshot["player_id"].astype(int).tolist())
progress = progress[progress["player_id"].astype(int).isin(eligible_ids)].copy()

# Re-rank within the currently selected player set.
snapshot = snapshot.sort_values(
    ["wins", "win_pct", "point_diff", "current_elo"],
    ascending=[False, False, False, False],
).reset_index(drop=True)
snapshot["rank"] = snapshot.index + 1

tabs = st.tabs(["Standings & Trends", "Scatter", "Heatmaps", "Insights"])

with tabs[0]:
    top1, top2, top3 = st.columns(3)
    top1.metric("Players shown", len(snapshot))
    top2.metric("Total games (sum)", int(snapshot["games"].sum()))
    top3.metric("Avg win %", f"{(snapshot['win_pct'].mean() * 100):.1f}%")
    table = snapshot.copy()
    table["Record"] = table.apply(lambda r: f"{int(r['wins'])}-{int(r['losses'])}", axis=1)
    table["Win %"] = (table["win_pct"] * 100).round(1)
    table["Elo"] = table["current_elo"].round(1)
    table["Elo Δ (last 10)"] = table["elo_delta_last_10"].round(1)
    table["Pt Diff"] = table["point_diff"].apply(lambda v: f"{float(v):+.1f}")
    table["SOS"] = table["strength_of_schedule"].round(1)
    table["SOV"] = table["strength_of_victory"].round(1)
    table["Avg MOV"] = table["avg_margin_victory"].round(1)
    table["Avg MOD"] = table["avg_margin_defeat"].round(1)
    table["Consistency"] = table["consistency_score"].round(1)
    for col in table.columns:
        if pd.api.types.is_float_dtype(table[col]):
            table[col] = table[col].round(1)
    standings_view = table[
        [
            "rank",
            "player",
            "Record",
            "Win %",
            "Elo",
            "Elo Δ (last 10)",
            "Pt Diff",
            "SOS",
            "SOV",
            "Avg MOV",
            "Avg MOD",
            "current_streak",
            "longest_win_streak",
            "upset_wins",
            "upset_losses",
            "close_game_record",
            "close_games",
            "blowout_wins",
            "blowout_losses",
            "Consistency",
        ]
    ].rename(
        columns={
            "rank": "Rank",
            "player": "Player",
            "current_streak": "Current Streak",
            "longest_win_streak": "Longest Win Streak",
            "upset_wins": "Upset Wins",
            "upset_losses": "Upset Losses",
            "close_game_record": "Close Wins",
            "close_games": "Close Games",
            "blowout_wins": "Blowout Wins",
            "blowout_losses": "Blowout Losses",
        }
    )
    column_config = {
        col: st.column_config.Column(col, alignment="center")
        for col in standings_view.columns
    }
    st.dataframe(
        standings_view,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )
    with st.expander("Standings column definitions", expanded=False):
        st.markdown(
            "- `Rank`: position among currently selected players (win %, point differential, Elo)\n"
            "- `Player`: player name\n"
            "- `Record`: wins-losses\n"
            "- `Win %`: win percentage\n"
            "- `Elo`: current Elo rating\n"
            "- `Elo Δ (last 10)`: total Elo change over the most recent 10 games\n"
            "- `Pt Diff`: total point differential (points scored minus points allowed), with `+/-`\n"
            "- `SOS`: strength of schedule (average opponent pre-match Elo)\n"
            "- `SOV`: strength of victory (average pre-match Elo of opponents in wins)\n"
            "- `Avg MOV`: average margin of victory in wins\n"
            "- `Avg MOD`: average margin of defeat in losses\n"
            "- `Current Streak`: current run of wins (`+`) or losses (`-`)\n"
            "- `Longest Win Streak`: longest consecutive win streak\n"
            "- `Upset Wins`: wins as the lower expected team (expected win probability < 50%)\n"
            "- `Upset Losses`: losses as the higher expected team (expected win probability >= 50%)\n"
            "- `Close Wins`: wins in close games (margin <= 2 points)\n"
            "- `Close Games`: total close games (margin <= 2 points)\n"
            "- `Blowout Wins`: wins by 6+ points\n"
            "- `Blowout Losses`: losses by 6+ points\n"
            "- `Consistency`: stability score from game-to-game point differential variance (higher is steadier)"
        )

    st.subheader("Trends")
    if progress.empty:
        st.caption("No trend data in this range.")
    else:
        st.caption(
            "Lines end at different places when players have different game counts. "
            "Use **Career %** so everyone finishes at 100%, or **Last N games** to align recent form."
        )
        mode_col, n_col = st.columns([2.2, 1])
        axis_mode = mode_col.radio(
            "X-axis",
            options=["progress", "games", "last_n"],
            format_func=lambda m: {
                "progress": "Career % (all end together)",
                "games": "Game # (raw career length)",
                "last_n": "Last N games (aligned recent form)",
            }[m],
            horizontal=True,
            key="analytics_trend_axis_mode",
        )
        last_n = int(
            n_col.number_input(
                "N (last games)",
                min_value=5,
                max_value=40,
                value=10,
                step=1,
                disabled=axis_mode != "last_n",
                key="analytics_trend_last_n",
            )
        )

        trend = progress.copy()
        trend["event_date"] = pd.to_datetime(trend["event_date"]).dt.strftime("%Y-%m-%d")
        trend["match_number"] = trend["match_order"].astype(int)
        total_games = trend.groupby("player_id")["games_cum"].transform("max")
        trend["career_pct"] = trend["games_cum"] / total_games.clip(lower=1)

        if axis_mode == "last_n":
            trend = (
                trend.sort_values(["player_id", "games_cum"])
                .groupby("player_id", group_keys=False)
                .tail(last_n)
                .copy()
            )
            trend["x_val"] = trend.groupby("player_id").cumcount() + 1
            x_col = "x_val"
            x_label = f"Game in last {last_n}"
            x_hover = "Recent game #"
        elif axis_mode == "progress":
            x_col = "career_pct"
            x_label = "Career progress"
            x_hover = "Career %"
        else:
            x_col = "games_cum"
            x_label = "Game #"
            x_hover = "Game #"

        def _trend_line(
            df: pd.DataFrame,
            y: str,
            title: str,
            y_label: str,
            *,
            pct_y: bool = False,
        ):
            fig = px.line(
                df,
                x=x_col,
                y=y,
                color="player",
                custom_data=["event_date", "match_number", "games_cum"],
                title=title,
                labels={
                    x_col: x_label,
                    y: y_label,
                    "player": "Player",
                },
            )
            y_fmt = "%{y:.0%}" if pct_y else "%{y:.2f}"
            x_fmt = "%{x:.0%}" if axis_mode == "progress" else "%{x}"
            fig.update_traces(
                mode="lines",
                line_shape="spline",
                line=dict(width=2.5),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Match date: %{customdata[0]}<br>"
                    "Match #: %{customdata[1]}<br>"
                    "Career game #: %{customdata[2]}<br>"
                    f"{x_hover}: {x_fmt}<br>"
                    f"{y_label}: {y_fmt}"
                    "<extra></extra>"
                ),
            )
            fig.update_layout(
                xaxis_title=x_label,
                yaxis_title=y_label,
                hovermode="closest",
                legend_title_text="Player",
            )
            if axis_mode == "progress":
                fig.update_xaxes(tickformat=".0%", range=[0, 1.02])
            if pct_y:
                fig.update_yaxes(tickformat=".0%")
            return fig

        p1, p2 = st.columns(2)
        with p1:
            st.plotly_chart(
                _trend_line(trend, "win_pct_cum", "Win % over time", "Win %", pct_y=True),
                use_container_width=True,
            )
        with p2:
            st.plotly_chart(
                _trend_line(trend, "elo_cum_gain", "Elo gain over time", "Elo gain"),
                use_container_width=True,
            )

        p3, p4 = st.columns(2)
        with p3:
            st.plotly_chart(
                _trend_line(
                    trend,
                    "elo_over_time",
                    "Elo over time",
                    "Elo",
                ),
                use_container_width=True,
            )
        with p4:
            st.plotly_chart(
                _trend_line(
                    trend,
                    "avg_margin_over_time",
                    "Average margin over time",
                    "Avg margin",
                ),
                use_container_width=True,
            )

with tabs[1]:
    scatter_base = snapshot.copy()
    scatter_base["partner_diversity"] = scatter_base["partner_diversity"].fillna(0)
    scatter_base["initial"] = scatter_base["player"].astype(str).str.strip().str[0].str.upper()
    scatter_base["marker_size"] = 11

    def _scatter(df: pd.DataFrame, x: str, y: str, title: str, labels: dict, pct_axes: tuple[str, ...] = ()):
        fig = px.scatter(
            df,
            x=x,
            y=y,
            color="player",
            text="initial",
            size="marker_size",
            size_max=11,
            hover_data=["player", "games", "wins", "losses", "point_diff", "current_elo", "win_pct"],
            title=title,
            labels=labels,
        )
        fig.update_traces(
            textposition="top center",
            textfont=dict(size=11, color="#333333"),
            marker=dict(line=dict(width=1, color="#333333"), opacity=0.85),
        )
        layout_kwargs = {"showlegend": True, "height": 480}
        for axis in pct_axes:
            if axis == "x":
                layout_kwargs["xaxis_tickformat"] = ".0%"
            if axis == "y":
                layout_kwargs["yaxis_tickformat"] = ".0%"
        fig.update_layout(**layout_kwargs)
        return fig

    s1, s2 = st.columns(2)
    with s1:
        st.plotly_chart(
            _scatter(
                scatter_base,
                "strength_of_schedule",
                "win_pct",
                "Win % vs Strength of Schedule",
                {"win_pct": "Win %", "strength_of_schedule": "SOS"},
                pct_axes=("y",),
            ),
            use_container_width=True,
        )
    with s2:
        st.plotly_chart(
            _scatter(
                scatter_base,
                "current_elo",
                "point_diff",
                "Elo vs Point Differential",
                {"current_elo": "Elo", "point_diff": "Point differential"},
            ),
            use_container_width=True,
        )
    s3, s4 = st.columns(2)
    with s3:
        st.plotly_chart(
            _scatter(
                scatter_base,
                "games",
                "win_pct",
                "Games Played vs Win %",
                {"games": "Games", "win_pct": "Win %"},
                pct_axes=("y",),
            ),
            use_container_width=True,
        )
    with s4:
        st.plotly_chart(
            _scatter(
                scatter_base,
                "partner_diversity",
                "win_pct",
                "Partner Diversity vs Win %",
                {"partner_diversity": "Unique partners", "win_pct": "Win %"},
                pct_axes=("y",),
            ),
            use_container_width=True,
        )
    st.plotly_chart(
        _scatter(
            scatter_base,
            "current_elo",
            "avg_margin_victory",
            "Elo vs Average Margin of Victory",
            {"current_elo": "Elo", "avg_margin_victory": "Avg margin of victory"},
        ),
        use_container_width=True,
    )

with tabs[2]:
    st.markdown(
        """
Each cell is **row player vs column opponent**: average point differential across games
where those two faced each other (on opposite teams).

- **Green** = the row player usually outscored that opponent (positive avg point diff)
- **Red** = the row player usually got outscored (negative avg point diff)
- **Yellow / near zero** = roughly even matchups
- Cell label: **avg point diff** on top, **(games)** underneath — how many head-to-head games that avg is based on
- Diagonal is always **0** (a player vs themselves)
        """.strip()
    )
    if heatmap_df.empty:
        st.caption("No heatmap data for current filter.")
    else:
        names = sorted(snapshot["player"].tolist(), key=str.lower)
        matrix = pd.DataFrame(index=names, columns=names, dtype=float)
        games_matrix = pd.DataFrame(index=names, columns=names, dtype=float)
        for _, r in heatmap_df.iterrows():
            p = str(r["player"])
            o = str(r["opponent"])
            if p in matrix.index and o in matrix.columns:
                matrix.loc[p, o] = float(r["avg_point_diff"])
                games_matrix.loc[p, o] = float(r["games"])
        for nm in names:
            matrix.loc[nm, nm] = 0.0
            games_matrix.loc[nm, nm] = 0.0
        text_matrix = matrix.copy()
        for col in text_matrix.columns:
            text_matrix[col] = [
                ""
                if pd.isna(matrix.loc[idx, col])
                else f"{float(matrix.loc[idx, col]):.1f}\n({int(games_matrix.loc[idx, col]) if pd.notna(games_matrix.loc[idx, col]) else 0})"
                for idx in text_matrix.index
            ]
        fig_hm = px.imshow(
            matrix,
            labels=dict(x="Opponent", y="Player", color="Avg point diff"),
            color_continuous_scale="RdYlGn",
            aspect="auto",
        )
        fig_hm.update_traces(
            text=text_matrix.values,
            texttemplate="%{text}",
            textfont=dict(size=15, color="#1f1f1f"),
            hovertemplate="Player: %{y}<br>Opponent: %{x}<br>Avg diff: %{z:.1f}<extra></extra>",
        )
        fig_hm.update_layout(height=max(560, len(names) * 58))
        st.plotly_chart(fig_hm, use_container_width=True)

with tabs[3]:
    st.subheader("Silly scouting notes")
    st.caption("Pure vibes. Not actuarial science. Definitely not betting advice.")
    if snapshot.empty:
        st.caption("No players to roast yet.")
    else:
        fun = snapshot.copy()
        fun["win_pct_100"] = fun["win_pct"] * 100
        notes: list[str] = []
        top = fun.sort_values(["win_pct", "point_diff"], ascending=[False, False]).iloc[0]
        notes.append(
            f"👑 {top['player']} is currently running the group chat — "
            f"{int(top['wins'])}-{int(top['losses'])} and acting like the rest of us are NPCs."
        )
        streaker = fun.sort_values("current_streak", ascending=False).iloc[0]
        if int(streaker["current_streak"]) >= 2:
            notes.append(
                f"🔥 {streaker['player']} is on a {int(streaker['current_streak'])}-game heater. "
                f"Someone please check if they secretly replaced their paddle with a magic wand."
            )
        cold = fun.sort_values("current_streak", ascending=True).iloc[0]
        if int(cold["current_streak"]) <= -2:
            notes.append(
                f"🧊 {cold['player']} is in a {abs(int(cold['current_streak']))}-game freefall. "
                f"Recommended treatment: snacks, vibes, and one extremely soft opponent."
            )
        if fun["upset_wins"].max() > 0:
            giant = fun.sort_values("upset_wins", ascending=False).iloc[0]
            notes.append(
                f"💥 {giant['player']} has {int(giant['upset_wins'])} upset win(s). "
                f"Professional giant-killer energy. Extremely rude. Extremely entertaining."
            )
        drama = fun.sort_values("close_games", ascending=False).iloc[0]
        if int(drama["close_games"]) > 0:
            notes.append(
                f"🎭 {drama['player']} lives for chaos — {int(drama['close_games'])} close games. "
                f"Every match is a telenovela and they refuse to leave the set."
            )
        blowout = fun.sort_values("blowout_wins", ascending=False).iloc[0]
        if int(blowout["blowout_wins"]) > 0:
            notes.append(
                f"🚀 {blowout['player']} has {int(blowout['blowout_wins'])} blowout win(s). "
                f"Mercy rule? Never heard of her."
            )
        consistent = fun.sort_values("consistency_score", ascending=False).iloc[0]
        notes.append(
            f"🎯 {consistent['player']} is weirdly consistent (score {consistent['consistency_score']:.0f}). "
            f"Either elite composure… or they've found a way to make every game feel like Groundhog Day."
        )
        diverse = fun.sort_values("partner_diversity", ascending=False).iloc[0]
        notes.append(
            f"🤝 {diverse['player']} has played with {int(diverse['partner_diversity'])} different partners. "
            f"Social butterfly? Or just impossible to schedule with the same person twice?"
        )
        for note in notes[:7]:
            st.write(f"- {note}")
