"""Players roster management."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from database.seed import seed_demo_players
from services.player_service import PlayerService
from utils.formatting import format_elo, provisional_badge_markdown
from utils.session import bootstrap_session, bump_data_version

bootstrap_session()
init_db(st.session_state.db_path)

service = PlayerService()

st.title("Players")
st.caption(
    "Manage the club roster. Elo starts at 1000 and updates as scores are entered. "
    "Players with fewer than 10 games are Provisional and use a higher Elo K-factor."
)

with st.sidebar:
    if st.button("Load demo roster"):
        inserted = seed_demo_players()
        if inserted:
            bump_data_version()
            st.success(f"Added {inserted} demo players")
            st.rerun()
        else:
            st.info("Roster already has players")

tab_list, tab_add = st.tabs(["Roster", "Add player"])

with tab_add:
    with st.form("add_player"):
        name = st.text_input("Name")
        display_name = st.text_input("Display name (optional)")
        active = st.checkbox("Active", value=True)
        if st.form_submit_button("Add player", type="primary"):
            try:
                service.create_player(
                    name,
                    display_name=display_name.strip() or None,
                    active=active,
                )
                bump_data_version()
                st.success(f"Added {name}")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

with tab_list:
    show_inactive = st.checkbox("Show inactive", value=False)
    players = service.list_players(active_only=not show_inactive)
    games_by_player = service.games_played_counts()
    if not players:
        st.info("No players yet. Add someone or load the demo roster.")
    else:
        for player in players:
            games = games_by_player.get(player.id, 0)
            provisional = service.is_provisional_player(player.id, games)
            cols = st.columns([3, 1, 1, 2])
            name_bits = [f"**{player.label}**"]
            if provisional:
                name_bits.append(provisional_badge_markdown())
            cols[0].markdown(" ".join(name_bits))
            cols[1].write(format_elo(player.current_elo))
            cols[2].write("Active" if player.active else "Inactive")
            with cols[3].expander("Edit"):
                with st.form(f"edit_{player.id}"):
                    new_name = st.text_input("Name", value=player.name)
                    new_display = st.text_input(
                        "Display name",
                        value=player.display_name or "",
                    )
                    new_active = st.checkbox("Active", value=player.active)
                    if st.form_submit_button("Save"):
                        try:
                            service.update_player(
                                player.id,
                                name=new_name,
                                display_name=new_display.strip() or new_name,
                                active=new_active,
                            )
                            bump_data_version()
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            if provisional:
                cols[0].caption("Provisional (fewer than 10 games)")
