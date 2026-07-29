"""Live score entry — hot path."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from database.connection import close_connection, reset_connection
from models.enums import MatchStatus
from services.event_service import EventService
from services.recompute_service import RecomputeService
from services.schedule_service import ScheduleService
from services.score_service import ScoreService, ScoreValidationError
from utils.session import bootstrap_session, bump_data_version

bootstrap_session()
init_db(st.session_state.db_path)


def _load_schedule(event_id: int) -> pd.DataFrame:
    """Load schedule; reconnect once if the DuckDB result looks corrupted."""
    df = ScheduleService().schedule_df(event_id)
    if df.empty or "round_number" in df.columns:
        return df.copy()
    reset_connection(st.session_state.db_path)
    init_db(st.session_state.db_path)
    df = ScheduleService().schedule_df(event_id)
    return df.copy()


st.title("Score Entry")
event_id = st.session_state.active_event_id
if not event_id:
    st.warning("Select an active event from the Home page sidebar.")
    st.stop()

event = EventService().get_event(event_id)
assert event is not None
st.caption(f"{event.name} · to {event.game_to}, win by {event.win_by}")

score_service = ScoreService()
sched_df = _load_schedule(int(event_id))
if not sched_df.empty and "round_number" not in sched_df.columns:
    st.error("Could not load the schedule (database connection glitch). Click rerun / refresh.")
    st.stop()

st.subheader("Round score table")
if sched_df.empty:
    st.info("No matches scheduled yet.")
else:
    rounds = sorted(sched_df["round_number"].dropna().astype(int).unique().tolist())
    if not rounds:
        rounds = [1]

    if "score_round" not in st.session_state or st.session_state.score_round not in rounds:
        st.session_state.score_round = rounds[0]

    current_idx = rounds.index(st.session_state.score_round)
    nav1, nav2, nav3 = st.columns([1, 1, 6])
    if nav1.button("← Prev", disabled=current_idx == 0, use_container_width=True):
        st.session_state.score_round = rounds[current_idx - 1]
        st.rerun()
    if nav2.button("Next →", disabled=current_idx == len(rounds) - 1, use_container_width=True):
        st.session_state.score_round = rounds[current_idx + 1]
        st.rerun()

    pager = st.columns(min(len(rounds), 10))
    for i, rnd in enumerate(rounds[:10]):
        label = f"[{rnd}]" if rnd == st.session_state.score_round else str(rnd)
        if pager[i].button(label, key=f"round_btn_{rnd}", use_container_width=True):
            st.session_state.score_round = rnd
            st.rerun()

    selected_round = st.session_state.score_round
    st.caption(f"Viewing round {selected_round} of {rounds[-1]}")
    strict = st.checkbox("Enforce win-by rules", value=True, key="score_table_strict")

    round_df = sched_df[sched_df["round_number"].astype(int) == int(selected_round)].copy()
    round_df["Team A"] = round_df["a1"] + " / " + round_df["a2"]
    round_df["Team B"] = round_df["b1"] + " / " + round_df["b2"]
    round_df["score_a"] = pd.to_numeric(round_df["team_a_score"], errors="coerce")
    round_df["score_b"] = pd.to_numeric(round_df["team_b_score"], errors="coerce")
    if "finale_display" in round_df.columns:
        round_df["Court/Finale"] = round_df.apply(
            lambda r: r["finale_display"]
            if bool(r.get("is_finale")) and pd.notna(r.get("finale_display"))
            else r["court"],
            axis=1,
        )
    else:
        round_df["Court/Finale"] = round_df["court"]

    edit_df = round_df[
        ["match_id", "match_order", "Court/Finale", "Team A", "Team B", "score_a", "score_b", "status"]
    ].rename(columns={"match_order": "#", "status": "Status"})
    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        disabled=["match_id", "#", "Court/Finale", "Team A", "Team B", "Status"],
        column_config={
            "score_a": st.column_config.NumberColumn("Team A score", min_value=0, max_value=50, step=1),
            "score_b": st.column_config.NumberColumn("Team B score", min_value=0, max_value=50, step=1),
        },
        key=f"score_table_round_{selected_round}",
    )

    if st.button("Save round scores", type="primary", use_container_width=True):
        errors: list[str] = []
        saved = 0
        original = round_df.set_index("match_id")
        for _, row in edited.iterrows():
            mid = int(row["match_id"])
            orig = original.loc[mid]
            old_a = orig["score_a"]
            old_b = orig["score_b"]
            new_a = row["score_a"]
            new_b = row["score_b"]

            old_has = pd.notna(old_a) and pd.notna(old_b)
            new_has = pd.notna(new_a) and pd.notna(new_b)
            if not old_has and not new_has:
                continue
            if old_has and new_has and int(old_a) == int(new_a) and int(old_b) == int(new_b):
                continue

            try:
                if new_has and not old_has:
                    score_service.submit_score(
                        mid,
                        int(new_a),
                        int(new_b),
                        game_to=event.game_to,
                        win_by=event.win_by,
                        strict=strict,
                        rebuild=False,
                    )
                    st.session_state.last_submitted_match_id = mid
                    saved += 1
                elif new_has and old_has:
                    score_service.edit_score(
                        mid,
                        int(new_a),
                        int(new_b),
                        game_to=event.game_to,
                        win_by=event.win_by,
                        strict=strict,
                        rebuild=False,
                    )
                    saved += 1
                elif old_has and not new_has:
                    score_service.undo_score(mid, rebuild=False)
                    saved += 1
            except ScoreValidationError as exc:
                errors.append(f"Match #{int(row['#'])}: {exc}")
            except Exception as exc:  # noqa: BLE001 — surface DB glitches in-row
                errors.append(f"Match #{int(row['#'])}: {exc}")

        if saved:
            try:
                RecomputeService().rebuild_all()
            except Exception as exc:  # noqa: BLE001
                reset_connection(st.session_state.db_path)
                errors.append(f"Saved scores but Elo rebuild failed: {exc}")
            else:
                bump_data_version()
                st.success(f"Saved {saved} score change(s).")
            # Fresh connection before rerun — avoids aborted-txn ghost errors
            reset_connection(st.session_state.db_path)

        if errors:
            st.error("Some rows failed to save:")
            for err in errors:
                st.write(f"- {err}")
        elif saved:
            st.rerun()

# Undo last
last_id = st.session_state.get("last_submitted_match_id")
if last_id:
    if st.button("Undo last score", type="secondary"):
        try:
            score_service.undo_score(int(last_id))
            st.session_state.last_submitted_match_id = None
            bump_data_version()
            st.rerun()
        except ScoreValidationError as exc:
            st.error(str(exc))

st.divider()
st.subheader("Recent / edit scores")
schedule_df = _load_schedule(int(event_id))
if schedule_df.empty or "status" not in schedule_df.columns:
    st.caption("No completed matches yet.")
else:
    completed = schedule_df[schedule_df["status"] == MatchStatus.COMPLETED.value]
    if completed.empty:
        st.caption("No completed matches yet.")
    else:
        for _, row in completed.sort_values("match_order", ascending=False).head(12).iterrows():
            mid = int(row["match_id"])
            title = (
                f"#{int(row['match_order'])}: {row['a1']}/{row['a2']} "
                f"{int(row['team_a_score'])}–{int(row['team_b_score'])} "
                f"{row['b1']}/{row['b2']}"
            )
            with st.expander(title):
                with st.form(f"edit_score_{mid}"):
                    ea = st.number_input(
                        "Team A",
                        min_value=0,
                        max_value=50,
                        value=int(row["team_a_score"]),
                        key=f"ea_{mid}",
                    )
                    eb = st.number_input(
                        "Team B",
                        min_value=0,
                        max_value=50,
                        value=int(row["team_b_score"]),
                        key=f"eb_{mid}",
                    )
                    cols = st.columns(2)
                    save = cols[0].form_submit_button("Save correction", type="primary")
                    if save:
                        try:
                            score_service.edit_score(
                                mid,
                                int(ea),
                                int(eb),
                                game_to=event.game_to,
                                win_by=event.win_by,
                                strict=False,
                            )
                            bump_data_version()
                            st.rerun()
                        except ScoreValidationError as exc:
                            st.error(str(exc))
                if st.button("Clear score (reopen match)", key=f"clear_{mid}"):
                    try:
                        score_service.undo_score(mid)
                        bump_data_version()
                        st.rerun()
                    except ScoreValidationError as exc:
                        st.error(str(exc))
