"""Live event dashboard for tonight's play."""

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
from services.llm_service import LlmService
from services.recompute_service import RecomputeService
from services.schedule_service import ScheduleService
from utils.session import bootstrap_session, set_active_event

bootstrap_session()
init_db(st.session_state.db_path)

st.markdown(
    """
    <style>
    .block-container { padding-top: 0.6rem !important; padding-bottom: 1rem !important; }
    h1 { margin-top: 0 !important; margin-bottom: 0.1rem !important; padding-top: 0 !important; }
    [data-testid="stCaptionContainer"] {
        margin-top: 0 !important;
        margin-bottom: 0.35rem !important;
        line-height: 1.25 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Match Central")

event_service = EventService()
events = event_service.list_events()
if not events:
    st.warning("No events yet. Create one on the Home page.")
    st.stop()

event_ids = [e.id for e in events]
event_labels = {e.id: f"{e.event_date} — {e.name} ({e.status.value})" for e in events}
current = st.session_state.active_event_id
if current not in event_ids:
    current = event_ids[0]
    set_active_event(current)

selected = st.selectbox(
    "Current game",
    options=event_ids,
    index=event_ids.index(current),
    format_func=lambda event_id: event_labels[event_id],
    key="match_central_event_select",
)
if selected != st.session_state.active_event_id:
    set_active_event(int(selected))
    st.rerun()

event_id = int(selected)
event = event_service.get_event(event_id)
if event is None:
    st.error("Active event not found.")
    st.stop()

st.caption(
    f"Tonight's live pulse — rankings, chaos, and glory · **{event.name}** · {event.event_date}"
)

analytics = AnalyticsService()
schedule = ScheduleService()
recompute = RecomputeService()
llm = LlmService()
schedule_df = schedule.schedule_df(event_id)
standings = recompute.standings_df(event_id)
if standings.empty:
    recompute.rebuild_event_standings(event_id)
    standings = recompute.standings_df(event_id)
live = analytics.live_event_player_metrics(event_id)
upset = analytics.live_event_biggest_upset(event_id)
closest = analytics.live_event_closest_match(event_id)
partners = analytics.event_best_partners(event_id)
scatter = analytics.live_event_scatter(event_id)

completed_games = 0 if schedule_df.empty else int((schedule_df["status"] == "completed").sum())
remaining_games = 0 if schedule_df.empty else int((schedule_df["status"] != "completed").sum())

if live.empty:
    st.info("No completed matches yet tonight. Enter a score to start live analytics.")
    st.stop()

leader = live.sort_values(["wins", "point_diff", "elo_delta_tonight"], ascending=[False, False, False]).iloc[0]
hottest = live.sort_values(["current_streak", "win_pct", "point_diff"], ascending=[False, False, False]).iloc[0]
biggest_mover = live.sort_values("elo_delta_tonight", ascending=False).iloc[0]

best_partnership = None
if not partners.empty:
    top_pair = partners.sort_values(
        ["win_rate", "games", "avg_margin"], ascending=[False, False, False]
    ).iloc[0]
    best_partnership = top_pair.to_dict()

recap_key = f"latest_event_recap_{event_id}"
silly_recap = st.session_state.get(recap_key) or llm.get_saved_event_recap(event_id)

upset_label = "None yet"
if upset is not None:
    upset_label = (
        f"{upset['team_a']} vs {upset['team_b']}<br>"
        f"<span style='font-size:0.85em'>{upset['score']} · Elo Gap {upset['upset_gap']:.1f}</span>"
    )

st.markdown(
    """
    <style>
    .kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 8px 0 18px 0; }
    .kpi-card {
        background: #e7f3ea;
        border: 1px solid #c9dccf;
        border-radius: 16px;
        padding: 16px 14px;
        text-align: center;
        min-height: 118px;
    }
    .kpi-emoji { font-size: 2.1rem; line-height: 1; margin-bottom: 6px; }
    .kpi-label {
        font-size: 0.95rem;
        font-weight: 700;
        color: #2f5d43;
        letter-spacing: 0.02em;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 1.15rem;
        font-weight: 600;
        color: #1f3d2c;
        line-height: 1.25;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

kpi_html = f"""
<div class="kpi-grid">
  <div class="kpi-card"><div class="kpi-emoji">🏆</div><div class="kpi-label">Current Leader</div><div class="kpi-value">{leader['player']}</div></div>
  <div class="kpi-card"><div class="kpi-emoji">🔥</div><div class="kpi-label">Hottest Player</div><div class="kpi-value">{hottest['player']}</div></div>
  <div class="kpi-card"><div class="kpi-emoji">📈</div><div class="kpi-label">Biggest Mover</div><div class="kpi-value">{biggest_mover['player']} (Elo {biggest_mover['elo_delta_tonight']:+.1f})</div></div>
  <div class="kpi-card"><div class="kpi-emoji">⏱️</div><div class="kpi-label">Games Remaining</div><div class="kpi-value">{remaining_games}</div></div>
  <div class="kpi-card"><div class="kpi-emoji">🎾</div><div class="kpi-label">Games Completed</div><div class="kpi-value">{completed_games}</div></div>
  <div class="kpi-card"><div class="kpi-emoji">💥</div><div class="kpi-label">Biggest Upset</div><div class="kpi-value">{upset_label}</div></div>
</div>
"""
st.markdown(kpi_html, unsafe_allow_html=True)

st.subheader("Live Rankings")
st.caption(
    "Ranked by **power score** (win % + point differential + Elo gain tonight + wins). "
    "**SOS** is average opponent team Elo before each match tonight. "
    "Movement is vs power rank **before the most recent completed match** "
    "(▲ up / ▼ down). "
    "🔥 = top 3 climbers this update · 🧊 = top 3 droppers · "
    "Trend dots are last up to 5 results (🟢 win / 🔴 loss, most recent first)."
)

def _trend_badge(code: str) -> str:
    if not code:
        return "—"
    return "".join("🟢" if ch == "W" else "🔴" for ch in code)


def _movement_label(delta: int) -> str:
    d = int(delta)
    if d > 0:
        return f"▲ {d}"
    if d < 0:
        return f"▼ {abs(d)}"
    return "—"


power = live.sort_values("power_score", ascending=False).copy().reset_index(drop=True)
power["rank"] = power.index + 1
mover_ids = set(
    power.sort_values("rank_delta", ascending=False).head(3)["player_id"].astype(int).tolist()
)
sinker_ids = set(
    power.sort_values("rank_delta", ascending=True).head(3)["player_id"].astype(int).tolist()
)


def _name_with_flair(row: pd.Series) -> str:
    name = str(row["player"])
    pid = int(row["player_id"])
    if pid in mover_ids and int(row["rank_delta"]) > 0:
        return f"🔥 {name}"
    if pid in sinker_ids and int(row["rank_delta"]) < 0:
        return f"🧊 {name}"
    return name


rankings_table = pd.DataFrame(
    {
        "Rank": power["rank"].astype(int),
        "Movement": power["rank_delta"].map(_movement_label),
        "Player": power.apply(_name_with_flair, axis=1),
        "Record": power.apply(lambda r: f"{int(r['wins'])}-{int(r['losses'])}", axis=1),
        "Pt Diff": power["point_diff"].map(lambda v: f"{float(v):+.1f}"),
        "Avg Win Margin": power["avg_win_margin"].map(lambda v: f"{float(v):+.1f}"),
        "Elo Δ": power["elo_delta_tonight"].map(lambda v: f"{float(v):+.1f}"),
        "SOS": power["strength_of_schedule"].map(lambda v: f"{float(v):.0f}"),
        "Trend (Last 5)": power["momentum"].map(_trend_badge),
        "Streak": power["current_streak"].map(
            lambda s: (
                f"{abs(int(s))} straight wins"
                if int(s) > 0
                else (f"{abs(int(s))} straight losses" if int(s) < 0 else "Even")
            )
        ),
    }
)
# Explicit height so the grid shows every row (Streamlit "auto" still caps with a scroll).
_rankings_height = 38 + 36 * (len(rankings_table) + 1)
st.caption(
    "Rankings currently reward **who you beat (Elo)** more than **by how much (PD)**."
)
st.dataframe(
    rankings_table,
    use_container_width=True,
    hide_index=True,
    height=_rankings_height,
)

st.subheader("Leaders")
if standings.empty:
    st.caption("No standings available yet.")
else:
    leaders_view = standings.copy()
    leaders_view["Player"] = leaders_view["display_name"].fillna(leaders_view["name"])
    leaders_view["Pt Diff"] = leaders_view["point_diff"].astype(int)
    leaders_view["Elo"] = leaders_view["elo"].round(0).astype(int)
    elo_delta_by_player = live.set_index("player_id")["elo_delta_tonight"].to_dict()
    leaders_view["Elo Δ"] = (
        leaders_view["player_id"].map(elo_delta_by_player).fillna(0.0)
    )
    dark_green = "#2f5d43"

    chart_left, chart_right = st.columns(2)
    with chart_left:
        wins_chart = leaders_view.sort_values(
            ["wins", "Pt Diff"], ascending=[False, False]
        ).head(8).copy()
        wins_chart["bar_label"] = wins_chart.apply(
            lambda row: f"<b style='font-size:18px'>{int(row['wins'])}</b><br>"
            f"<span style='font-size:11px'>({int(row['Pt Diff']):+d})</span>",
            axis=1,
        )
        fig_wins = px.bar(
            wins_chart,
            x="Player",
            y="wins",
            title="Top wins",
            labels={"wins": "Wins"},
            color_discrete_sequence=[dark_green],
        )
        fig_wins.update_traces(
            text=wins_chart["bar_label"].tolist(),
            textposition="outside",
            cliponaxis=False,
            marker_color=dark_green,
            textfont=dict(size=14),
        )
        st.plotly_chart(fig_wins, use_container_width=True)

    with chart_right:
        elo_chart = leaders_view.sort_values("Elo", ascending=False).head(8).copy()
        elo_chart["bar_label"] = elo_chart.apply(
            lambda row: f"<b style='font-size:18px'>{int(row['Elo'])}</b><br>"
            f"<span style='font-size:11px'>({float(row['Elo Δ']):+.1f})</span>",
            axis=1,
        )
        fig_leaders_elo = px.bar(
            elo_chart,
            x="Player",
            y="Elo",
            title="Current Elo leaders<br><sup>Current Elo (tonight's change)</sup>",
            labels={"Elo": "Elo"},
            color_discrete_sequence=[dark_green],
        )
        fig_leaders_elo.update_traces(
            text=elo_chart["bar_label"].tolist(),
            textposition="outside",
            cliponaxis=False,
            marker_color=dark_green,
            textfont=dict(size=14),
        )
        fig_leaders_elo.update_yaxes(
            range=[600, max(650, float(elo_chart["Elo"].max()) + 55)]
        )
        st.plotly_chart(fig_leaders_elo, use_container_width=True)

st.subheader("Winners Club")
finale_df = (
    schedule_df[schedule_df["is_finale"].astype(bool)].copy()
    if not schedule_df.empty and "is_finale" in schedule_df.columns
    else schedule_df.iloc[0:0].copy()
)
if finale_df.empty:
    st.caption("No finale matches yet. Generate playoffs from Schedule Builder.")
else:
    def _finale_sort_key(label: object) -> int:
        text = str(label)
        if text == "Top Seed":
            return 0
        if text.isdigit():
            return int(text)
        return {"Consolation": 2, "Runner-up": 3}.get(text, 99)

    finale_df["_ord"] = finale_df["finale_label"].map(_finale_sort_key)
    finale_df = finale_df.sort_values(["_ord", "match_order", "match_id"])
    st.markdown("**Finale matchups**")
    finale_cols = st.columns(min(3, max(1, len(finale_df))))
    for idx, (_, row) in enumerate(finale_df.iterrows()):
        with finale_cols[idx % len(finale_cols)]:
            title = row.get("finale_display") or (
                f"Finale - {row['finale_label']}"
                if pd.notna(row.get("finale_label"))
                else "Finale"
            )
            if row["status"] == "completed" and pd.notna(row["team_a_score"]):
                score_a = int(row["team_a_score"])
                score_b = int(row["team_b_score"])
                a_won = score_a > score_b
                team_a_html = (
                    f"<div style='margin-top:8px;font-weight:700;color:#137a3a;'>{row['a1']} / {row['a2']}"
                    f"&nbsp;&nbsp;{score_a}</div>"
                    f"<div style='font-size:0.85rem;font-style:italic;margin-top:2px;color:#137a3a;'>*Winner*</div>"
                    if a_won
                    else f"<div style='margin-top:8px;'>{row['a1']} / {row['a2']}&nbsp;&nbsp;{score_a}</div>"
                )
                team_b_html = (
                    f"<div style='margin-top:6px;font-weight:700;color:#137a3a;'>{row['b1']} / {row['b2']}"
                    f"&nbsp;&nbsp;{score_b}</div>"
                    f"<div style='font-size:0.85rem;font-style:italic;margin-top:2px;color:#137a3a;'>*Winner*</div>"
                    if not a_won
                    else f"<div style='margin-top:6px;'>{row['b1']} / {row['b2']}&nbsp;&nbsp;{score_b}</div>"
                )
                body_html = (
                    f"{team_a_html}"
                    f"<div style='opacity:0.55;margin:4px 0;'>vs</div>"
                    f"{team_b_html}"
                )
            else:
                body_html = (
                    f"<div style='margin-top:8px;'>{row['a1']} / {row['a2']}</div>"
                    f"<div style='opacity:0.55;margin:2px 0;'>vs</div>"
                    f"<div>{row['b1']} / {row['b2']}</div>"
                    f"<div style='margin-top:8px;opacity:0.7;'>Awaiting score</div>"
                )
            st.markdown(
                f"""
                <div style="background:#f4f0e6;border:1px solid #d9d2c3;border-radius:14px;
                            padding:14px;min-height:140px;">
                  <div style="font-size:0.95rem;font-weight:700;color:#5a4e3a;">{title}</div>
                  {body_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown("**Overall podium**")
st.caption("Based on tonight's Live Rankings power score (same as finale seeding).")
podium_view = live.sort_values(
    ["power_score", "wins", "point_diff", "elo_delta_tonight"],
    ascending=[False, False, False, False],
).reset_index(drop=True)
medal_colors = ["#d4af37", "#c0c0c0", "#cd7f32"]
medal_labels = ["🥇 1st", "🥈 2nd", "🥉 3rd"]
podium_cols = st.columns(3)
for idx, (_, podium_row) in enumerate(podium_view.head(3).iterrows()):
    with podium_cols[idx]:
        st.markdown(
            f"""
            <div style="background:{medal_colors[idx]}22;border:1px solid {medal_colors[idx]};
                        border-radius:14px;padding:14px;text-align:center;">
              <div style="font-size:1.4rem;">{medal_labels[idx]}</div>
              <div style="font-size:1.15rem;font-weight:700;margin-top:6px;">{podium_row['player']}</div>
              <div style="margin-top:4px;">{int(podium_row['wins'])}-{int(podium_row['losses'])}
                · PD {int(podium_row['point_diff']):+d}
                · Elo {float(podium_row['elo_delta_tonight']):+.1f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

lower_left, lower_right = st.columns(2)
card_css = """
<style>
.info-card {
    background: #2f5d43;
    color: #f3f7f4;
    border-radius: 16px;
    padding: 18px 16px;
    min-height: 150px;
}
.info-card .card-kicker {
    font-size: 0.85rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    opacity: 0.8;
    margin-bottom: 8px;
}
.info-card .card-title {
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1.3;
    margin-bottom: 10px;
}
.info-card .card-team {
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1.3;
}
.info-card .card-vs {
    opacity: 0.7;
    margin: 6px 0;
    font-size: 0.95rem;
}
.info-card .card-score {
    font-size: 1rem;
    font-weight: 700;
    margin: 8px 0;
}
.info-card .card-meta {
    font-size: 1rem;
    opacity: 0.9;
    margin-top: 4px;
}
</style>
"""
st.markdown(card_css, unsafe_allow_html=True)

with lower_left:
    st.subheader("Tonight's Best Partnership")
    if best_partnership is None:
        st.caption("No completed pairings yet.")
    else:
        st.markdown(
            f"""
            <div class="info-card">
              <div class="card-kicker">Best partnership</div>
              <div class="card-title">{best_partnership['partners']}</div>
              <div class="card-meta">Record: {int(best_partnership['wins'])}-{int(best_partnership['losses'])}</div>
              <div class="card-meta">Point Differential: {float(best_partnership['avg_margin']):+.1f} avg margin</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with lower_right:
    st.subheader("Closest Match")
    if closest is None:
        st.caption("No completed matches yet.")
    else:
        st.markdown(
            f"""
            <div class="info-card">
              <div class="card-kicker">Closest match</div>
              <div class="card-team">{closest['team_a']}</div>
              <div class="card-score">{closest['score']}</div>
              <div class="card-team">{closest['team_b']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.subheader("Tonight-only Scatter: Win % vs SOS")
st.caption("Farther right = tougher SOS; higher = better win %.")
if scatter.empty:
    st.caption("No completed matches yet.")
else:
    scatter_plot = scatter.copy()
    scatter_plot["initial"] = scatter_plot["player"].astype(str).str.strip().str[0].str.upper()
    scatter_plot["marker_size"] = 18
    fig_scatter = px.scatter(
        scatter_plot,
        x="strength_of_schedule",
        y="win_pct",
        color="player",
        text="initial",
        size="marker_size",
        size_max=18,
        hover_data=["player", "wins", "losses", "games", "point_diff", "elo_delta_tonight"],
        labels={
            "win_pct": "Win %",
            "strength_of_schedule": "SOS (avg opponent Elo)",
        },
    )
    fig_scatter.update_traces(
        textposition="top center",
        textfont=dict(size=11, color="rgba(40,40,40,0.75)"),
        marker=dict(line=dict(width=0), opacity=0.65),
    )
    fig_scatter.update_layout(
        yaxis_tickformat=".0%",
        xaxis_title="SOS (avg opponent Elo)",
        margin=dict(b=80),
        annotations=[
            dict(
                text="(Easier Schedule)",
                xref="paper",
                yref="paper",
                x=0,
                y=-0.18,
                showarrow=False,
                font=dict(size=11, color="#666666"),
                xanchor="left",
            ),
            dict(
                text="(Tougher Schedule)",
                xref="paper",
                yref="paper",
                x=1,
                y=-0.18,
                showarrow=False,
                font=dict(size=11, color="#666666"),
                xanchor="right",
            ),
        ],
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

st.subheader("Elo Δ by player")
if live.empty:
    st.caption("No completed matches yet.")
else:
    elo_chart = live.sort_values("elo_delta_tonight", ascending=False).copy()
    elo_chart["Elo Δ"] = elo_chart["elo_delta_tonight"].round(1)
    fig_elo = px.bar(
        elo_chart,
        x="player",
        y="Elo Δ",
        color="Elo Δ",
        color_continuous_scale=["#b85c38", "#e7f3ea", "#2f5d43"],
        color_continuous_midpoint=0,
        labels={"player": "Player", "Elo Δ": "Elo change tonight"},
    )
    fig_elo.update_traces(
        texttemplate="%{y:+.1f}",
        textposition="outside",
        cliponaxis=False,
    )
    fig_elo.update_layout(showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(fig_elo, use_container_width=True)

st.subheader("Recent results")
if schedule_df.empty:
    st.caption("No matches scheduled.")
else:
    recent = schedule_df[schedule_df["status"] == "completed"].sort_values(
        "match_order", ascending=False
    ).head(8)
    if recent.empty:
        st.caption("No scores submitted yet.")
    else:
        recent_rows = [
            {
                "#": int(row["match_order"]),
                "Team A": f"{row['a1']} / {row['a2']}",
                "Score": f"{int(row['team_a_score'])}–{int(row['team_b_score'])}",
                "Team B": f"{row['b1']} / {row['b2']}",
                "Court": row["court"],
            }
            for _, row in recent.iterrows()
        ]
        st.dataframe(recent_rows, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Night recap")
st.caption("Light commentary powered by local Ollama. Not actuarial science.")
if st.button("Generate night recap with Ollama", type="primary"):
    with st.spinner("Writing tonight's recap…"):
        text = llm.generate_event_recap(event_id)
    st.session_state[recap_key] = text
    silly_recap = text
if silly_recap:
    st.markdown(silly_recap)
