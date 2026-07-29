"""Historical CSV import."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from import_.templates import sample_csv
from services.import_service import ImportService
from utils.session import bootstrap_session, bump_data_version

bootstrap_session()
init_db(st.session_state.db_path)

st.title("Data Import")
st.caption("Upload past games: date, four players (two teams), and scores.")
st.download_button(
    "Download CSV template",
    data=sample_csv(),
    file_name="pickleball_schema_matches.csv",
    mime="text/csv",
)

uploaded = st.file_uploader("Upload match CSV", type=["csv"])
if not uploaded:
    st.code(sample_csv(), language="csv")
    st.stop()

df = pd.read_csv(uploaded)
st.subheader("Preview")
st.dataframe(df.head(20), use_container_width=True, hide_index=True)
service = ImportService()
errors = service.validate(df)
if errors:
    st.error("Validation errors:")
    for err in errors:
        st.write(f"- {err}")
    st.stop()

st.success("Validation passed.")
mark_completed = st.checkbox("Mark imported events as completed", value=True)
if st.button("Import CSV", type="primary"):
    try:
        result = service.import_matches(
            df,
            source_filename=uploaded.name,
            mark_events_completed=mark_completed,
        )
        bump_data_version()
        st.success(
            f"Imported {result['rows_imported']} rows into {result['events_touched']} event(s). "
            f"Players total: {result['players_total']}."
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Import failed: {exc}")
