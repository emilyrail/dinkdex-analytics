"""DinkDex Analytics — local-first pickleball analytics."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from utils.session import bootstrap_session

st.set_page_config(
    page_title="DinkDex Analytics",
    page_icon="🥒",
    layout="wide",
    initial_sidebar_state="expanded",
)

bootstrap_session()
init_db(st.session_state.db_path)

home = st.Page("pages/home.py", title="Home", icon="🏠", default=True)
schedule_builder = st.Page("pages/3_Schedule_Builder.py", title="Schedule Builder", icon="🗓️")
score_entry = st.Page("pages/2_Score_Entry.py", title="Score Entry", icon="✍️")
match_central = st.Page("pages/10_Live_Event_Dashboard.py", title="Match Central", icon="🏆")
player_profiles = st.Page("pages/5_Player_Profiles.py", title="Player Profiles", icon="✨")
overall_analytics = st.Page("pages/6_Analytics.py", title="Overall Analytics", icon="📊")
players = st.Page("pages/4_Players.py", title="Players", icon="👥")
event_history = st.Page("pages/7_Event_History.py", title="Event History", icon="📜")
data_import = st.Page("pages/8_Data_Import.py", title="Data Import", icon="📥")
settings = st.Page("pages/9_Settings.py", title="Settings", icon="⚙️")

housekeeping_pages = [players, event_history, data_import, settings]

# Hidden native nav so we can render a custom expandable sidebar.
pg = st.navigation(
    [
        home,
        schedule_builder,
        score_entry,
        match_central,
        player_profiles,
        overall_analytics,
        *housekeeping_pages,
    ],
    position="hidden",
)

with st.sidebar:
    st.page_link(home, label="Home", icon="🏠")

    st.markdown("**Set Up**")
    st.page_link(schedule_builder, label="Schedule Builder", icon="🗓️")
    st.page_link(score_entry, label="Score Entry", icon="✍️")

    st.markdown("**🥒📈 DinkDex Analytics**")
    st.page_link(match_central, label="Match Central", icon="🏆")
    st.page_link(player_profiles, label="Player Profiles", icon="✨")
    st.page_link(overall_analytics, label="Overall Analytics", icon="📊")

    # Keep Housekeeping open when one of its pages is active.
    hk_titles = {p.title for p in housekeeping_pages}
    with st.expander("🧹 Housekeeping", expanded=pg.title in hk_titles):
        st.page_link(players, label="Players", icon="👥")
        st.page_link(event_history, label="Event History", icon="📜")
        st.page_link(data_import, label="Data Import", icon="📥")
        st.page_link(settings, label="Settings", icon="⚙️")

pg.run()

