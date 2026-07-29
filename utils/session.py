"""Streamlit session-state helpers."""

from __future__ import annotations

import streamlit as st

from utils.config import DEFAULT_DB_PATH


def _apply_global_style_overrides() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            background-color: #609078 !important;
            color: #F4F0E6 !important;
        }
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] .stMarkdown {
            color: #F4F0E6 !important;
        }
        /* Select / input fields: dark green field, light readable text */
        section[data-testid="stSidebar"] [data-baseweb="select"] > div,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        section[data-testid="stSidebar"] .stTextInput input,
        section[data-testid="stSidebar"] .stNumberInput input {
            background-color: #2B6A46 !important;
            color: #F4F0E6 !important;
            -webkit-text-fill-color: #F4F0E6 !important;
            border: 1px solid #C9D7C5 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {
            fill: #F4F0E6 !important;
            color: #F4F0E6 !important;
        }
        section[data-testid="stSidebar"] [data-baseweb="select"] > div *,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"],
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"] * {
            color: #F4F0E6 !important;
            -webkit-text-fill-color: #F4F0E6 !important;
            opacity: 1 !important;
        }
        section[data-testid="stSidebar"] button[kind="secondary"] {
            border-color: #C9D7C5 !important;
            color: #F4F0E6 !important;
        }
        /* Dropdown menu portals outside the sidebar — force dark text on light menu */
        div[data-baseweb="popover"] li,
        div[data-baseweb="popover"] li *,
        div[data-baseweb="menu"] li,
        div[data-baseweb="menu"] li *,
        ul[role="listbox"] li,
        ul[role="listbox"] li * {
            color: #1b4332 !important;
            -webkit-text-fill-color: #1b4332 !important;
        }
        div[data-baseweb="popover"] li[aria-selected="true"],
        div[data-baseweb="menu"] li[aria-selected="true"] {
            background-color: #dcefe3 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def bootstrap_session() -> None:
    _apply_global_style_overrides()
    if "active_event_id" not in st.session_state:
        st.session_state.active_event_id = None
    if "data_version" not in st.session_state:
        st.session_state.data_version = 0
    if "last_submitted_match_id" not in st.session_state:
        st.session_state.last_submitted_match_id = None
    if "db_path" not in st.session_state:
        st.session_state.db_path = str(DEFAULT_DB_PATH)


def bump_data_version() -> None:
    st.session_state.data_version = int(st.session_state.get("data_version", 0)) + 1


def set_active_event(event_id: int | None) -> None:
    st.session_state.active_event_id = event_id
