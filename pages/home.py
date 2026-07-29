"""Home — active event, quick start, create event."""

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
from utils.session import bootstrap_session, set_active_event

bootstrap_session()
init_db(st.session_state.db_path)

event_service = EventService()
player_service = PlayerService()

st.title("Home")
st.caption("Local-first pickleball analytics for competitive game nights.")

events = event_service.list_events()
players = player_service.list_players(active_only=True)

col_a, col_b, col_c = st.columns(3)
col_a.metric("Players", len(players))
col_b.metric("Events", len(events))
active = st.session_state.active_event_id
if active:
    event = event_service.get_event(active)
    attendees = event_service.get_attendee_ids(active) if event else []
    col_c.metric("Tonight’s roster", len(attendees))
else:
    col_c.metric("Tonight’s roster", "—")

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Quick start")
    st.markdown(
        """
1. Add players on **Players**
2. Create an event below
3. Build the schedule on **Schedule Builder**
4. Enter scores live on **Score Entry**
5. Follow the night on **Match Central**, then dive into **Picklelytics**
        """
    )

with right:
    st.subheader("Create event")
    with st.form("create_event_home"):
        name = st.text_input("Event name", value="Game Night")
        event_date = st.date_input("Date")
        num_courts = st.number_input("Courts", min_value=1, max_value=8, value=2)
        player_options = {p.id: p.label for p in players}
        selected_players = st.multiselect(
            "Attending players",
            options=list(player_options.keys()),
            format_func=lambda i: player_options[i],
        )
        submitted = st.form_submit_button("Create event", type="primary")
        if submitted:
            if not name.strip():
                st.error("Name is required")
            elif not selected_players:
                st.error("Select at least one player")
            else:
                event = event_service.create_event(
                    name,
                    event_date,
                    player_ids=selected_players,
                    num_courts=int(num_courts),
                )
                set_active_event(event.id)
                st.success(f"Created {event.name}")
                st.rerun()

if active:
    event = event_service.get_event(active)
    if event:
        st.divider()
        st.subheader(f"Active: {event.name}")
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Date:** {event.event_date}")
        c2.write(f"**Status:** {event.status.value}")
        c3.write(f"**Scoring:** to {event.game_to}, win by {event.win_by}")
        c4.write(f"**Courts:** {event.num_courts}")

if players:
    st.divider()
    st.subheader("Roster snapshot")
    games_by_player = player_service.games_played_counts()
    st.dataframe(
        [
            {
                "Player": p.label,
                "Elo": round(p.current_elo) if p.current_elo is not None else None,
                "Badge": (
                    "Provisional (fewer than 10 games)"
                    if player_service.is_provisional_player(p.id, games_by_player.get(p.id, 0))
                    else ""
                ),
                "Active": p.active,
            }
            for p in players
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Elo is a rolling skill rating (starting at 1000). "
        "Beat higher-rated teams and you gain more; lose to lower-rated teams and you lose more. "
        "Players with fewer than 10 games are Provisional and move with 2× the normal K-factor."
    )
else:
    st.info("No players yet — open **Players** to add your roster.")
