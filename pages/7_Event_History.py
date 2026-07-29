"""Past events archive."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from services.event_service import EventService
from services.player_service import PlayerService
from services.schedule_service import ScheduleService
from utils.session import bootstrap_session, set_active_event

import pandas as pd

bootstrap_session()
init_db(st.session_state.db_path)

st.title("Event History")
event_service = EventService()
events = event_service.list_events()
if not events:
    st.info("No events yet.")
    st.stop()

labels = {e.id: f"{e.event_date} — {e.name} ({e.status.value})" for e in events}
selected_id = st.selectbox(
    "Select event",
    options=[e.id for e in events],
    format_func=lambda i: labels[i],
    key="event_history_select",
)
event = event_service.get_event(int(selected_id))
assert event is not None

top = st.columns([3, 1])
top[0].markdown(f"**{event.name}** · {event.event_date} · {event.status.value}")
if top[1].button("Set active", type="primary"):
    set_active_event(event.id)
    st.success(f"Active event: {event.name}")
    st.rerun()

schedule_df = ScheduleService().schedule_df(event.id)
attendee_ids = event_service.get_attendee_ids(event.id)
players_by_id = {p.id: p.label for p in PlayerService().list_players(active_only=False)}
attendee_rows = [
    {"#": i, "Player": players_by_id.get(pid, f"Player {pid}")}
    for i, pid in enumerate(
        sorted(attendee_ids, key=lambda pid: players_by_id.get(pid, "").lower()),
        start=1,
    )
]

left, right = st.columns([1, 3])
with left:
    st.subheader("Attendance")
    if not attendee_rows:
        st.caption("No attendees listed.")
    else:
        st.dataframe(attendee_rows, use_container_width=True, hide_index=True)

with right:
    st.subheader("Scores")
    if schedule_df.empty:
        st.caption("No matches for this event.")
    else:
        completed = schedule_df[schedule_df["status"] == "completed"].sort_values(
            ["round_number", "match_order", "match_id"]
        )
        if completed.empty:
            st.caption("No completed scores yet.")
        else:
            rows = []
            for _, row in completed.iterrows():
                rows.append(
                    {
                        "Round": int(row["round_number"]),
                        "#": int(row["match_order"]),
                        "Court": (
                            row["finale_display"]
                            if bool(row.get("is_finale")) and pd.notna(row.get("finale_display"))
                            else row["court"]
                        ),
                        "Team A": f"{row['a1']} / {row['a2']}",
                        "Score": f"{int(row['team_a_score'])}–{int(row['team_b_score'])}",
                        "Team B": f"{row['b1']} / {row['b2']}",
                        "Winner": (
                            f"{row['a1']} / {row['a2']}"
                            if int(row["team_a_score"]) > int(row["team_b_score"])
                            else f"{row['b1']} / {row['b2']}"
                        ),
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)

st.divider()
st.subheader("All events")
for event_row in events:
    cols = st.columns([3, 2, 2, 2])
    cols[0].markdown(f"**{event_row.name}**")
    cols[1].write(str(event_row.event_date))
    cols[2].write(event_row.status.value)
    if cols[3].button("Set active", key=f"hist_{event_row.id}"):
        set_active_event(event_row.id)
        st.success(f"Active event: {event_row.name}")
        st.rerun()
