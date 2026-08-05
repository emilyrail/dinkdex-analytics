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

pages = {
    "": [
        st.Page("pages/home.py", title="Home", icon="🏠", default=True),
    ],
    "Set Up": [
        st.Page("pages/3_Schedule_Builder.py", title="Schedule Builder", icon="🗓️"),
        st.Page("pages/2_Score_Entry.py", title="Score Entry", icon="✍️"),
    ],
    "🧹 Housekeeping": [
        st.Page("pages/4_Players.py", title="Players", icon="👥"),
        st.Page("pages/7_Event_History.py", title="Event History", icon="📜"),
        st.Page("pages/8_Data_Import.py", title="Data Import", icon="📥"),
        st.Page("pages/9_Settings.py", title="Settings", icon="⚙️"),
    ],
    "🥒📈 DinkDex Analytics": [
        st.Page("pages/10_Live_Event_Dashboard.py", title="Match Central", icon="🏆"),
        st.Page("pages/5_Player_Profiles.py", title="Player Profiles", icon="✨"),
        st.Page("pages/6_Analytics.py", title="Overall Analytics", icon="📊"),
    ],
}

pg = st.navigation(pages, position="sidebar")
pg.run()
