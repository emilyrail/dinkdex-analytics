"""App settings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from services.recompute_service import RecomputeService
from utils.config import (
    DEFAULT_DB_PATH,
    DEFAULT_GAME_TO,
    DEFAULT_WIN_BY,
    ELO_K,
    INITIAL_ELO,
    OLLAMA_MODEL,
    OLLAMA_URL,
    PROVISIONAL_GAMES,
    PROVISIONAL_K_MULTIPLIER,
)
from utils.session import bootstrap_session, bump_data_version

bootstrap_session()
init_db(st.session_state.db_path)

st.title("Settings")

st.subheader("Database")
st.code(st.session_state.db_path)
st.caption(f"Default path: {DEFAULT_DB_PATH}")

st.subheader("Defaults")
st.write(f"Initial Elo: **{INITIAL_ELO:.0f}** · K-factor: **{ELO_K:.0f}**")
st.write(
    f"Provisional (first **{PROVISIONAL_GAMES}** games): "
    f"K × **{PROVISIONAL_K_MULTIPLIER:.0f}** = **{ELO_K * PROVISIONAL_K_MULTIPLIER:.0f}**"
)
st.write(f"Scoring: to **{DEFAULT_GAME_TO}**, win by **{DEFAULT_WIN_BY}**")

st.subheader("Maintenance")
if st.button("Rebuild Elo & standings"):
    RecomputeService().rebuild_all()
    bump_data_version()
    st.success("Rebuilt Elo history and event standings from all scores.")

st.subheader("Ollama")
st.write(f"URL: `{OLLAMA_URL}` · Model: `{OLLAMA_MODEL}`")
st.caption("AI summaries require a local Ollama install. Core scoring works offline without it.")
