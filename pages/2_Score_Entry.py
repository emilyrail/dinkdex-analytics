"""Live score entry — table on laptop, cards on phone."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from database.connection import reset_connection
from models.enums import MatchStatus
from services.event_service import EventService
from services.recompute_service import RecomputeService
from services.schedule_service import ScheduleService
from services.score_service import ScoreService, ScoreValidationError
from utils.session import bootstrap_session, bump_data_version, set_active_event

bootstrap_session()
init_db(st.session_state.db_path)


def _is_phone() -> bool:
    """Best-effort phone detection from the browser user agent."""
    try:
        headers = st.context.headers
        ua = str(headers.get("User-Agent") or headers.get("user-agent") or "")
    except Exception:
        ua = ""
    low = ua.lower()
    if "ipad" in low:
        return False
    return any(token in low for token in ("iphone", "ipod", "android", "mobile"))


def _load_schedule(event_id: int) -> pd.DataFrame:
    """Load schedule; reconnect once if the DuckDB result looks corrupted."""
    df = ScheduleService().schedule_df(event_id)
    if df.empty or "round_number" in df.columns:
        return df.copy()
    reset_connection(st.session_state.db_path)
    init_db(st.session_state.db_path)
    df = ScheduleService().schedule_df(event_id)
    return df.copy()


def _court_label(row: pd.Series) -> str:
    if bool(row.get("is_finale")) and pd.notna(row.get("finale_display")):
        return str(row["finale_display"])
    court = row.get("court")
    if pd.isna(court):
        return "Court —"
    return f"Court {int(court)}"


def _ensure_score_key(key: str, raw: object) -> None:
    if key not in st.session_state:
        st.session_state[key] = int(raw) if pd.notna(raw) else None


def _score_input(label: str, key: str) -> None:
    st.number_input(
        label,
        min_value=0,
        max_value=50,
        step=1,
        key=key,
        placeholder="–",
        label_visibility="collapsed",
    )


def _save_round_scores(
    *,
    round_df: pd.DataFrame,
    new_scores: dict[int, tuple[object, object]],
    event,
    score_service: ScoreService,
    strict: bool,
) -> None:
    errors: list[str] = []
    saved = 0
    for _, row in round_df.iterrows():
        mid = int(row["match_id"])
        old_a = row.get("team_a_score")
        old_b = row.get("team_b_score")
        new_a, new_b = new_scores.get(mid, (None, None))

        old_has = pd.notna(old_a) and pd.notna(old_b)
        new_has = new_a is not None and new_b is not None and pd.notna(new_a) and pd.notna(new_b)
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
            errors.append(f"{_court_label(row)}: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{_court_label(row)}: {exc}")

    if saved:
        try:
            RecomputeService().rebuild_all()
        except Exception as exc:  # noqa: BLE001
            reset_connection(st.session_state.db_path)
            errors.append(f"Saved scores but Elo rebuild failed: {exc}")
        else:
            bump_data_version()
            st.success(f"Saved {saved} score change(s).")
        reset_connection(st.session_state.db_path)

    if errors:
        st.error("Some matches failed to save:")
        for err in errors:
            st.write(f"- {err}")
    elif saved:
        st.rerun()


st.title("Score Entry")

event_service = EventService()
events = event_service.list_events()
if not events:
    st.warning("No events yet. Create one on Home first.")
    st.stop()

event_ids = [event.id for event in events]
event_labels = {
    event.id: f"{event.event_date} — {event.name} ({event.status.value})"
    for event in events
}
current_event_id = st.session_state.active_event_id
if current_event_id not in event_ids:
    current_event_id = event_ids[0]
    set_active_event(current_event_id)

selected_event_id = st.selectbox(
    "Active event",
    options=event_ids,
    index=event_ids.index(current_event_id),
    format_func=lambda selected_id: event_labels[selected_id],
    key="score_entry_event_select",
)
if selected_event_id != st.session_state.active_event_id:
    set_active_event(int(selected_event_id))
    st.rerun()

event_id = int(selected_event_id)
event = event_service.get_event(event_id)
assert event is not None
st.caption(f"{event.name} · to {event.game_to}, win by {event.win_by}")

phone = _is_phone()
layout_choice = st.segmented_control(
    "Layout",
    options=["Auto", "Cards", "Table"],
    default="Auto",
    key="score_entry_layout",
    help="Auto uses cards on phones and the table on laptops.",
)
use_cards = layout_choice == "Cards" or (layout_choice == "Auto" and phone)

if use_cards:
    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
          .block-container {
            padding-left: 0.7rem !important;
            padding-right: 0.7rem !important;
            padding-top: 0.8rem !important;
            padding-bottom: 5rem !important;
          }
          h1 { font-size: 1.45rem !important; margin-bottom: 0.2rem !important; }
        }
        div[data-testid="stNumberInput"] input {
          font-size: 1.55rem !important;
          min-height: 3rem !important;
          text-align: center !important;
          font-weight: 700 !important;
        }
        div[data-testid="stNumberInput"] button {
          min-width: 2.75rem !important;
          min-height: 2.75rem !important;
        }
        .stButton > button {
          min-height: 2.8rem !important;
          font-size: 1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

score_service = ScoreService()
sched_df = _load_schedule(int(event_id))
if not sched_df.empty and "round_number" not in sched_df.columns:
    st.error("Could not load the schedule (database connection glitch). Click rerun / refresh.")
    st.stop()

if sched_df.empty:
    st.info("No matches scheduled yet.")
    st.stop()

rounds = sorted(sched_df["round_number"].dropna().astype(int).unique().tolist())
if not rounds:
    rounds = [1]

if "score_round" not in st.session_state or st.session_state.score_round not in rounds:
    st.session_state.score_round = rounds[0]

current_idx = rounds.index(st.session_state.score_round)
prev_col, next_col = st.columns(2, gap="small")
if prev_col.button(
    "← Prev round",
    disabled=current_idx == 0,
    use_container_width=True,
):
    st.session_state.score_round = rounds[current_idx - 1]
    st.rerun()
if next_col.button(
    "Next round →",
    disabled=current_idx == len(rounds) - 1,
    use_container_width=True,
    type="primary",
):
    st.session_state.score_round = rounds[current_idx + 1]
    st.rerun()

if use_cards:
    selected_round = st.selectbox(
        "Round",
        options=rounds,
        index=rounds.index(st.session_state.score_round),
        format_func=lambda r: f"Round {r} of {rounds[-1]}",
    )
    if selected_round != st.session_state.score_round:
        st.session_state.score_round = int(selected_round)
        st.rerun()
else:
    pager = st.columns(min(len(rounds), 10))
    for i, rnd in enumerate(rounds[:10]):
        label = f"[{rnd}]" if rnd == st.session_state.score_round else str(rnd)
        if pager[i].button(label, key=f"round_btn_{rnd}", use_container_width=True):
            st.session_state.score_round = rnd
            st.rerun()

selected_round = st.session_state.score_round
st.caption(f"Viewing round {selected_round} of {rounds[-1]}")
strict = st.checkbox("Enforce win-by rules", value=False, key="score_entry_strict")

round_df = sched_df[sched_df["round_number"].astype(int) == int(selected_round)].copy()
round_df = round_df.sort_values(["court", "match_order"], kind="stable")
scored_n = int(round_df["team_a_score"].notna().sum()) if not round_df.empty else 0
st.caption(f"{len(round_df)} match(es) · {scored_n} scored")

if use_cards:
    for _, row in round_df.iterrows():
        mid = int(row["match_id"])
        a_key = f"score_a_{selected_round}_{mid}"
        b_key = f"score_b_{selected_round}_{mid}"
        _ensure_score_key(a_key, row.get("team_a_score"))
        _ensure_score_key(b_key, row.get("team_b_score"))
        saved = pd.notna(row.get("team_a_score")) and pd.notna(row.get("team_b_score"))
        court = _court_label(row)

        with st.container(border=True):
            head_l, head_r = st.columns([3, 2])
            head_l.markdown(f"**{court}**")
            if saved:
                head_r.markdown(
                    f"<p style='text-align:right;margin:0;color:#2B6A46;font-weight:700;'>"
                    f"Saved {int(row['team_a_score'])}–{int(row['team_b_score'])}</p>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                f"<div style='font-size:1.05rem;font-weight:600;line-height:1.35;'>"
                f"{row['a1']} / {row['a2']}"
                f"<div style='font-size:0.8rem;font-weight:500;color:#667;margin:0.15rem 0;'>vs</div>"
                f"{row['b1']} / {row['b2']}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"{row['a1']} / {row['a2']}")
            _score_input("Team A", a_key)
            st.caption(f"{row['b1']} / {row['b2']}")
            _score_input("Team B", b_key)

    if st.button("Save round scores", type="primary", use_container_width=True):
        new_scores = {
            int(row["match_id"]): (
                st.session_state.get(f"score_a_{selected_round}_{int(row['match_id'])}"),
                st.session_state.get(f"score_b_{selected_round}_{int(row['match_id'])}"),
            )
            for _, row in round_df.iterrows()
        }
        _save_round_scores(
            round_df=round_df,
            new_scores=new_scores,
            event=event,
            score_service=score_service,
            strict=strict,
        )
else:
    round_df["Team A"] = round_df["a1"] + " / " + round_df["a2"]
    round_df["Team B"] = round_df["b1"] + " / " + round_df["b2"]
    round_df["score_a"] = pd.to_numeric(round_df["team_a_score"], errors="coerce")
    round_df["score_b"] = pd.to_numeric(round_df["team_b_score"], errors="coerce")
    round_df["Court/Finale"] = round_df.apply(_court_label, axis=1)
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
        new_scores = {
            int(row["match_id"]): (row["score_a"], row["score_b"])
            for _, row in edited.iterrows()
        }
        _save_round_scores(
            round_df=round_df,
            new_scores=new_scores,
            event=event,
            score_service=score_service,
            strict=strict,
        )

last_id = st.session_state.get("last_submitted_match_id")
if last_id:
    if st.button("Undo last score", type="secondary", use_container_width=True):
        try:
            score_service.undo_score(int(last_id))
            st.session_state.last_submitted_match_id = None
            bump_data_version()
            st.rerun()
        except ScoreValidationError as exc:
            st.error(str(exc))

st.divider()
with st.expander("Edit / clear saved scores", expanded=False):
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
                    f"R{int(row['round_number'])} · {_court_label(row)}: "
                    f"{row['a1']}/{row['a2']} "
                    f"{int(row['team_a_score'])}–{int(row['team_b_score'])} "
                    f"{row['b1']}/{row['b2']}"
                )
                with st.expander(title):
                    ea = st.number_input(
                        f"{row['a1']} / {row['a2']}",
                        min_value=0,
                        max_value=50,
                        value=int(row["team_a_score"]),
                        key=f"ea_{mid}",
                    )
                    eb = st.number_input(
                        f"{row['b1']} / {row['b2']}",
                        min_value=0,
                        max_value=50,
                        value=int(row["team_b_score"]),
                        key=f"eb_{mid}",
                    )
                    if st.button("Save correction", type="primary", key=f"save_corr_{mid}", use_container_width=True):
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
                    if st.button("Clear score (reopen match)", key=f"clear_{mid}", use_container_width=True):
                        try:
                            score_service.undo_score(mid)
                            bump_data_version()
                            st.rerun()
                        except ScoreValidationError as exc:
                            st.error(str(exc))
