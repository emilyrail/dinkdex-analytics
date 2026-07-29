"""Schedule builder — manual matchups + generator hooks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from collections import Counter

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.migrate import init_db
from models.enums import EventStatus
from models.match import finale_label_for_bracket
from repositories.events import EventRepository
from services.analytics_service import AnalyticsService
from services.event_service import EventService
from services.player_service import PlayerService
from services.schedule_service import ScheduleService
from utils.session import bootstrap_session, bump_data_version, set_active_event

bootstrap_session()
init_db(st.session_state.db_path)

st.title("Schedule Builder")

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
    key="schedule_builder_event_select",
)
if selected_event_id != st.session_state.active_event_id:
    set_active_event(int(selected_event_id))
    st.rerun()

event_id = int(selected_event_id)
schedule_service = ScheduleService()
analytics_service = AnalyticsService()
event = event_service.get_event(event_id)
assert event is not None

st.caption(
    f"{event.name} · {event.event_date} · {event.num_courts} courts · {event.status.value}"
)

st.markdown("**Event status**")
status_cols = st.columns(4)
status_options = [
    (EventStatus.DRAFT, "Mark draft"),
    (EventStatus.SCHEDULED, "Mark scheduled"),
    (EventStatus.LIVE, "Go live"),
    (EventStatus.COMPLETED, "Mark completed"),
]
for col, (status, label) in zip(status_cols, status_options):
    if col.button(
        label,
        disabled=event.status == status,
        use_container_width=True,
        key=f"schedule_status_{status.value}",
    ):
        event_service.set_status(event.id, status)
        bump_data_version()
        st.rerun()


def _round_duplicate_players(
    df: pd.DataFrame,
    *,
    name_to_id_lookup: dict[str, int],
) -> tuple[dict[int, set[object]], dict[int, list[str]]]:
    duplicate_ids_by_round: dict[int, set[object]] = {}
    duplicate_names_by_round: dict[int, list[str]] = {}
    if df.empty:
        return duplicate_ids_by_round, duplicate_names_by_round

    has_player_id_cols = all(col in df.columns for col in ("a1_id", "a2_id", "b1_id", "b2_id"))
    player_cols = [("a1_id", "a1"), ("a2_id", "a2"), ("b1_id", "b1"), ("b2_id", "b2")]
    for round_number, round_df in df.groupby("round_number"):
        id_to_names: dict[object, list[str]] = {}
        for _, row in round_df.iterrows():
            for id_col, name_col in player_cols:
                raw_name = str(row[name_col]).strip()
                if has_player_id_cols:
                    player_key: object = int(row[id_col])
                else:
                    player_key = name_to_id_lookup.get(raw_name.casefold(), f"name::{raw_name.casefold()}")
                id_to_names.setdefault(player_key, []).append(raw_name)
        duplicates = {pid: names for pid, names in id_to_names.items() if len(names) > 1}
        if not duplicates:
            continue

        duplicate_ids_by_round[int(round_number)] = set(duplicates.keys())
        duplicate_names_by_round[int(round_number)] = sorted(
            {names[0] for names in duplicates.values()},
            key=str.lower,
        )

    return duplicate_ids_by_round, duplicate_names_by_round


def _parse_round_conflict(error_text: str) -> tuple[int | None, set[str]]:
    match = re.search(r"Round\s+(\d+)\s+already includes\s+(.+?)\.\s+Each player", error_text)
    if not match:
        return None, set()
    round_number = int(match.group(1))
    names = {part.strip().casefold() for part in match.group(2).split(",") if part.strip()}
    return round_number, names

# --- Attendees ---
repo = EventRepository()
attendees_df = repo.get_players_df(event_id)
players = PlayerService().list_players(active_only=True)
all_players = PlayerService().list_players(active_only=False)
player_elo_by_id = {p.id: float(p.current_elo) for p in all_players}
options = {p.id: p.label for p in players}
current_ids = event_service.get_attendee_ids(event_id)
# Keep current attendees selectable even if marked inactive.
for p in all_players:
    if p.id in set(current_ids) and p.id not in options:
        options[p.id] = f"{p.label} (inactive)"
valid_current_ids = [pid for pid in current_ids if pid in options]
player_name_to_id = {}
for p in all_players:
    if p.name:
        player_name_to_id[p.name.strip().casefold()] = p.id
    if p.label:
        player_name_to_id[p.label.strip().casefold()] = p.id

with st.expander("Attendees & courts", expanded=not current_ids):
    selected = st.multiselect(
        "Players attending",
        options=list(options.keys()),
        default=valid_current_ids,
        format_func=lambda i: options[i],
    )
    st.caption(f"Selected attendees: {len(selected)}")
    c1, c2 = st.columns(2)
    num_courts = c1.number_input("Courts", min_value=1, max_value=8, value=event.num_courts)
    if c2.button("Save attendees & courts", type="primary"):
        event_service.update_event(
            event_id,
            player_ids=selected,
            num_courts=int(num_courts),
        )
        bump_data_version()
        st.success("Saved")
        st.rerun()

attendee_ids = event_service.get_attendee_ids(event_id)
attendee_labels = {
    p.id: options.get(p.id, p.label) for p in all_players if p.id in set(attendee_ids)
}
if len(attendee_ids) < 4:
    st.warning("Need at least 4 attendees to create matches.")
    st.stop()

st.markdown("**Schedule Generator**")
with st.expander("Generate schedule", expanded=False):
    with st.form("generate_schedule"):
        g1, g2, g3 = st.columns(3)
        num_rounds = g1.number_input("Rounds", min_value=1, max_value=30, value=6)
        seed = g2.number_input("Seed", min_value=0, value=42)
        balance_elo = g3.checkbox("Balance by Elo", value=True)
        replace = st.checkbox("Replace existing upcoming matches", value=True)
        generate = st.form_submit_button("Generate", type="primary")
        if generate:
            try:
                result = schedule_service.generate_schedule(
                    event_id,
                    num_rounds=int(num_rounds),
                    seed=int(seed),
                    replace_existing=replace,
                    balance_elo=balance_elo,
                )
                bump_data_version()
                q = result.quality
                st.success(
                    f"Generated {len(result.matches)} matches · "
                    f"partner repeats={q.partner_repeat_total} · "
                    f"cost={q.total_cost:.1f}"
                )
                games = sorted(q.games_per_player.items(), key=lambda x: x[0])
                st.caption(
                    "Games/player: "
                    + ", ".join(
                        f"{attendee_labels.get(pid, pid)}={n}" for pid, n in games
                    )
                )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.divider()

# --- Current schedule ---
st.subheader("Schedule")
schedule_df = schedule_service.schedule_df(event_id)
duplicate_ids_by_round, duplicate_names_by_round = _round_duplicate_players(
    schedule_df,
    name_to_id_lookup=player_name_to_id,
)


def _schedule_variety_stats(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {
            "partner_repeat_total": 0,
            "opponent_repeat_total": 0,
            "top_partner_pair": None,
            "top_opponent_pair": None,
        }

    partner_counts: Counter[tuple[int, int]] = Counter()
    opponent_counts: Counter[tuple[int, int]] = Counter()

    for _, row in df.iterrows():
        if not all(col in df.columns for col in ("a1_id", "a2_id", "b1_id", "b2_id")):
            continue
        a1 = int(row["a1_id"])
        a2 = int(row["a2_id"])
        b1 = int(row["b1_id"])
        b2 = int(row["b2_id"])

        partner_counts[tuple(sorted((a1, a2)))] += 1
        partner_counts[tuple(sorted((b1, b2)))] += 1

        for a in (a1, a2):
            for b in (b1, b2):
                opponent_counts[tuple(sorted((a, b)))] += 1

    partner_repeat_total = int(sum(max(0, n - 1) for n in partner_counts.values()))
    opponent_repeat_total = int(sum(max(0, n - 1) for n in opponent_counts.values()))

    top_partner_pair = None
    if partner_counts:
        pair, count = max(partner_counts.items(), key=lambda item: item[1])
        if count > 1:
            top_partner_pair = (pair, int(count))

    top_opponent_pair = None
    if opponent_counts:
        pair, count = max(opponent_counts.items(), key=lambda item: item[1])
        if count > 1:
            top_opponent_pair = (pair, int(count))

    return {
        "partner_repeat_total": partner_repeat_total,
        "opponent_repeat_total": opponent_repeat_total,
        "top_partner_pair": top_partner_pair,
        "top_opponent_pair": top_opponent_pair,
    }
page_error = st.session_state.pop("schedule_builder_page_error", None)
conflict_round = st.session_state.pop("schedule_builder_conflict_round", None)
conflict_names = set(st.session_state.pop("schedule_builder_conflict_names", []))
if page_error and conflict_round is None and not conflict_names:
    parsed_round, parsed_names = _parse_round_conflict(page_error)
    conflict_round, conflict_names = parsed_round, parsed_names
if schedule_df.empty:
    st.info("No matches yet. Add one below.")
else:
    variety = _schedule_variety_stats(schedule_df)
    scheduled_team_elos = []
    for _, scheduled_row in schedule_df.iterrows():
        if all(
            col in schedule_df.columns
            for col in ("a1_id", "a2_id", "b1_id", "b2_id")
        ):
            scheduled_team_elos.extend(
                [
                    (
                        player_elo_by_id.get(int(scheduled_row["a1_id"]), 1000.0)
                        + player_elo_by_id.get(int(scheduled_row["a2_id"]), 1000.0)
                    )
                    / 2.0,
                    (
                        player_elo_by_id.get(int(scheduled_row["b1_id"]), 1000.0)
                        + player_elo_by_id.get(int(scheduled_row["b2_id"]), 1000.0)
                    )
                    / 2.0,
                ]
            )
    avg_team_elo = (
        sum(scheduled_team_elos) / len(scheduled_team_elos)
        if scheduled_team_elos
        else 1000.0
    )
    v1, v2, v3 = st.columns(3)
    v1.metric("Repeated partners", int(variety["partner_repeat_total"]))
    v2.metric("Repeated opponents", int(variety["opponent_repeat_total"]))
    v3.metric("Avg Team Elo", f"{avg_team_elo:.0f}")

    details: list[str] = []
    top_partner_pair = variety["top_partner_pair"]
    if top_partner_pair:
        (p1, p2), n = top_partner_pair
        details.append(
            f"Top repeated partner pair: {attendee_labels.get(p1, f'Player {p1}')} + "
            f"{attendee_labels.get(p2, f'Player {p2}')} ({n} times)"
        )
    top_opponent_pair = variety["top_opponent_pair"]
    if top_opponent_pair:
        (p1, p2), n = top_opponent_pair
        details.append(
            f"Top repeated opponents: {attendee_labels.get(p1, f'Player {p1}')} vs "
            f"{attendee_labels.get(p2, f'Player {p2}')} ({n} times)"
        )
    if details:
        st.caption(" | ".join(details))
    else:
        st.caption("Nice variety so far: no repeated partner or opponent pairings yet.")

    if page_error:
        st.error(page_error)

    if duplicate_names_by_round:
        rounds = sorted(duplicate_names_by_round.keys())
        details = "; ".join(
            f"Round {r}: {', '.join(duplicate_names_by_round[r])}" for r in rounds
        )
        st.error(
            "Duplicate players found within the same round. "
            "Repeated players are highlighted in red below.\n\n"
            f"{details}"
        )

    display = schedule_df.copy()
    display["Team A"] = display["a1"] + " / " + display["a2"]
    display["Team B"] = display["b1"] + " / " + display["b2"]

    def _team_elo(
        row: pd.Series,
        id_col_1: str,
        id_col_2: str,
        name_col_1: str,
        name_col_2: str,
    ) -> float:
        if id_col_1 in row.index and id_col_2 in row.index:
            player_1 = int(row[id_col_1])
            player_2 = int(row[id_col_2])
        else:
            player_1 = player_name_to_id.get(str(row[name_col_1]).strip().casefold())
            player_2 = player_name_to_id.get(str(row[name_col_2]).strip().casefold())
        elo_1 = player_elo_by_id.get(player_1, 1000.0)
        elo_2 = player_elo_by_id.get(player_2, 1000.0)
        return (elo_1 + elo_2) / 2.0

    display["Team A Elo"] = display.apply(
        lambda row: _team_elo(row, "a1_id", "a2_id", "a1", "a2"),
        axis=1,
    ).round(0).astype(int)
    display["Team B Elo"] = display.apply(
        lambda row: _team_elo(row, "b1_id", "b2_id", "b1", "b2"),
        axis=1,
    ).round(0).astype(int)
    has_score = pd.notna(display["team_a_score"]) & pd.notna(display["team_b_score"])
    display["Score"] = "—"
    display.loc[has_score, "Score"] = (
        display.loc[has_score, "team_a_score"].astype(int).astype(str)
        + "–"
        + display.loc[has_score, "team_b_score"].astype(int).astype(str)
    )
    has_player_id_cols = all(col in display.columns for col in ("a1_id", "a2_id", "b1_id", "b2_id"))
    base_columns = [
        "match_order",
        "round_number",
        "court",
        "a1",
        "a2",
        "b1",
        "b2",
        "Team A",
        "Team A Elo",
        "Team B",
        "Team B Elo",
        "Score",
        "status",
        "match_id",
    ]
    id_columns = ["a1_id", "a2_id", "b1_id", "b2_id"] if has_player_id_cols else []
    table = display[id_columns + base_columns].rename(
        columns={
            "match_order": "#",
            "round_number": "Round",
            "court": "Court",
            "a1": "A1",
            "a2": "A2",
            "b1": "B1",
            "b2": "B2",
            "status": "Status",
            "match_id": "ID",
        }
    )
    table = table.sort_values(["Round", "Court", "#"], na_position="last")

    display_table = table.drop(columns=["a1_id", "a2_id", "b1_id", "b2_id"], errors="ignore")

    def _highlight_duplicate_cells(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        duplicate_ids = duplicate_ids_by_round.get(int(row["Round"]), set())
        source_row = table.loc[row.name]
        for name_col, id_col in (("A1", "a1_id"), ("A2", "a2_id"), ("B1", "b1_id"), ("B2", "b2_id")):
            if (
                conflict_round is not None
                and int(row["Round"]) == int(conflict_round)
                and str(source_row[name_col]).strip().casefold() in conflict_names
            ):
                styles[row.index.get_loc(name_col)] = "background-color: #f8d7da; color: #7a1f2b;"
                continue
            if not duplicate_ids:
                continue
            if id_col in source_row.index:
                player_key: object = int(source_row[id_col])
            else:
                player_key = player_name_to_id.get(str(source_row[name_col]).strip().casefold())
            if player_key in duplicate_ids:
                styles[row.index.get_loc(name_col)] = "background-color: #f8d7da; color: #7a1f2b;"
        return styles

    st.dataframe(
        display_table.style.apply(_highlight_duplicate_cells, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**Round sit-outs / unassigned**")
    assigned_by_round: dict[int, set[int]] = {}
    for round_number, round_df in schedule_df.groupby("round_number"):
        assigned: set[int] = set()
        if all(col in round_df.columns for col in ("a1_id", "a2_id", "b1_id", "b2_id")):
            for col in ("a1_id", "a2_id", "b1_id", "b2_id"):
                assigned.update({int(player_id) for player_id in round_df[col].tolist()})
        else:
            for col in ("a1", "a2", "b1", "b2"):
                for raw_name in round_df[col].tolist():
                    resolved = player_name_to_id.get(str(raw_name).strip().casefold())
                    if resolved is not None:
                        assigned.add(int(resolved))
        assigned_by_round[int(round_number)] = assigned

    attendee_id_set = set(attendee_ids)
    for round_number in sorted(assigned_by_round.keys()):
        sitting_out_ids = sorted(attendee_id_set - assigned_by_round[round_number])
        sitting_out = sorted(
            [attendee_labels.get(pid, f"Player {pid}") for pid in sitting_out_ids],
            key=str.lower,
        )
        if sitting_out:
            st.caption(f"Round {round_number}: {', '.join(sitting_out)}")
        else:
            st.caption(f"Round {round_number}: none")

# --- Add match ---
with st.expander("Add a match", expanded=False):
    with st.form("add_match"):
        c1, c2, c3, c4 = st.columns(4)
        a1 = c1.selectbox("Team A — player 1", attendee_ids, format_func=lambda i: attendee_labels[i], key="a1")
        a2 = c2.selectbox("Team A — player 2", attendee_ids, format_func=lambda i: attendee_labels[i], key="a2")
        b1 = c3.selectbox("Team B — player 1", attendee_ids, format_func=lambda i: attendee_labels[i], key="b1")
        b2 = c4.selectbox("Team B — player 2", attendee_ids, format_func=lambda i: attendee_labels[i], key="b2")
        r1, r2, r3 = st.columns(3)
        round_number = r1.number_input("Round", min_value=1, value=1)
        court = r2.number_input("Court", min_value=1, max_value=int(event.num_courts), value=1)
        submitted = r3.form_submit_button("Add match", type="primary")
        if submitted:
            try:
                schedule_service.add_match(
                    event_id,
                    a1=int(a1),
                    a2=int(a2),
                    b1=int(b1),
                    b2=int(b2),
                    round_number=int(round_number),
                    court=int(court),
                )
                bump_data_version()
                st.success("Match added")
                st.rerun()
            except ValueError as exc:
                error_text = str(exc)
                st.session_state["schedule_builder_page_error"] = error_text
                parsed_round, parsed_names = _parse_round_conflict(error_text)
                if parsed_round is not None and parsed_names:
                    st.session_state["schedule_builder_conflict_round"] = parsed_round
                    st.session_state["schedule_builder_conflict_names"] = sorted(parsed_names)
                st.rerun()

# --- Edit / delete upcoming ---
upcoming = [
    m
    for m in schedule_service.list_matches(event_id)
    if m.status.value == "scheduled"
]
with st.expander("Edit upcoming match", expanded=False):
    if not upcoming:
        st.caption("No upcoming matches to edit.")
    else:
        st.markdown("**Bulk edit a round**")
        upcoming_df = schedule_df[schedule_df["status"] == "scheduled"].copy() if not schedule_df.empty else pd.DataFrame()
        available_rounds = sorted(upcoming_df["round_number"].dropna().astype(int).unique().tolist()) if not upcoming_df.empty else []
        if available_rounds:
            selected_round = st.selectbox("Round to edit", options=available_rounds, key="bulk_round_to_edit")
            round_rows = upcoming_df[upcoming_df["round_number"].astype(int) == int(selected_round)].sort_values(
                ["match_order", "match_id"]
            )

            with st.form("bulk_edit_round_form"):
                st.caption("Update all match lineups in this round, then save once.")
                bulk_values: list[dict[str, int]] = []
                for _, row in round_rows.iterrows():
                    match_id = int(row["match_id"])
                    order = int(row["match_order"])
                    court = int(row["court"]) if pd.notna(row["court"]) else 1
                    player_options = sorted(
                        set(attendee_ids) | {int(row["a1_id"]), int(row["a2_id"]), int(row["b1_id"]), int(row["b2_id"])}
                    )
                    player_labels = {
                        pid: attendee_labels.get(pid, f"Player {pid}")
                        for pid in player_options
                    }

                    st.markdown(f"**Match #{order} · Court {court}**")
                    c1, c2, c3, c4 = st.columns(4)
                    ba1 = c1.selectbox(
                        "Team A — 1",
                        player_options,
                        index=player_options.index(int(row["a1_id"])),
                        format_func=lambda i, labels=player_labels: labels[i],
                        key=f"bulk_a1_{match_id}",
                    )
                    ba2 = c2.selectbox(
                        "Team A — 2",
                        player_options,
                        index=player_options.index(int(row["a2_id"])),
                        format_func=lambda i, labels=player_labels: labels[i],
                        key=f"bulk_a2_{match_id}",
                    )
                    bb1 = c3.selectbox(
                        "Team B — 1",
                        player_options,
                        index=player_options.index(int(row["b1_id"])),
                        format_func=lambda i, labels=player_labels: labels[i],
                        key=f"bulk_b1_{match_id}",
                    )
                    bb2 = c4.selectbox(
                        "Team B — 2",
                        player_options,
                        index=player_options.index(int(row["b2_id"])),
                        format_func=lambda i, labels=player_labels: labels[i],
                        key=f"bulk_b2_{match_id}",
                    )
                    bulk_values.append(
                        {
                            "match_id": match_id,
                            "a1": int(ba1),
                            "a2": int(ba2),
                            "b1": int(bb1),
                            "b2": int(bb2),
                            "court": court,
                            "order": order,
                            "round": int(selected_round),
                        }
                    )
                    st.divider()

                save_round = st.form_submit_button("Save round changes", type="primary")
                if save_round:
                    try:
                        for item in bulk_values:
                            schedule_service.update_scheduled_match(
                                item["match_id"],
                                a1=item["a1"],
                                a2=item["a2"],
                                b1=item["b1"],
                                b2=item["b2"],
                                round_number=item["round"],
                                court=item["court"],
                                match_order=item["order"],
                            )
                        bump_data_version()
                        st.success(f"Updated round {selected_round}.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.caption("No scheduled rounds available for bulk edit.")

        st.markdown("**Edit a single upcoming match**")
        match_options = {m.id: f"#{m.match_order} (round {m.round_number}, court {m.court})" for m in upcoming}
        edit_id = st.selectbox(
            "Match",
            options=list(match_options.keys()),
            format_func=lambda i: match_options[i],
        )
        match = next(m for m in upcoming if m.id == edit_id)
        from repositories.matches import TeamRepository

        teams = TeamRepository()
        ta = teams.get_player_ids(match.team_a_id)
        tb = teams.get_player_ids(match.team_b_id)

        with st.form("edit_match"):
            c1, c2, c3, c4 = st.columns(4)
            ea1 = c1.selectbox(
                "Team A — 1",
                attendee_ids,
                index=attendee_ids.index(ta[0]) if ta[0] in attendee_ids else 0,
                format_func=lambda i: attendee_labels[i],
            )
            ea2 = c2.selectbox(
                "Team A — 2",
                attendee_ids,
                index=attendee_ids.index(ta[1]) if ta[1] in attendee_ids else 1,
                format_func=lambda i: attendee_labels[i],
            )
            eb1 = c3.selectbox(
                "Team B — 1",
                attendee_ids,
                index=attendee_ids.index(tb[0]) if tb[0] in attendee_ids else 2,
                format_func=lambda i: attendee_labels[i],
            )
            eb2 = c4.selectbox(
                "Team B — 2",
                attendee_ids,
                index=attendee_ids.index(tb[1]) if tb[1] in attendee_ids else 3,
                format_func=lambda i: attendee_labels[i],
            )
            r1, r2, r3 = st.columns(3)
            eround = r1.number_input("Round", min_value=1, value=match.round_number)
            ecourt = r2.number_input(
                "Court",
                min_value=1,
                max_value=int(event.num_courts),
                value=match.court or 1,
            )
            eorder = r3.number_input("Order", min_value=1, value=match.match_order)
            save = st.form_submit_button("Save changes", type="primary")
            if save:
                try:
                    schedule_service.update_scheduled_match(
                        edit_id,
                        a1=int(ea1),
                        a2=int(ea2),
                        b1=int(eb1),
                        b2=int(eb2),
                        round_number=int(eround),
                        court=int(ecourt),
                        match_order=int(eorder),
                    )
                    bump_data_version()
                    st.success("Updated")
                    st.rerun()
                except ValueError as exc:
                    error_text = str(exc)
                    st.session_state["schedule_builder_page_error"] = error_text
                    parsed_round, parsed_names = _parse_round_conflict(error_text)
                    if parsed_round is not None and parsed_names:
                        st.session_state["schedule_builder_conflict_round"] = parsed_round
                        st.session_state["schedule_builder_conflict_names"] = sorted(parsed_names)
                    st.rerun()

        if st.button("Delete this match", type="secondary"):
            try:
                schedule_service.delete_match(edit_id)
                bump_data_version()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.divider()
st.subheader("Generate playoffs")
st.caption(
    "Rankings currently reward who you beat (Elo) more than by how much (PD)."
)
live_rankings = analytics_service.live_event_player_metrics(event_id)
if live_rankings.empty:
    standings = analytics_service.event_standings(event_id)
    if standings.empty:
        seed_ids = attendee_ids
    else:
        seeded = [int(pid) for pid in standings["player_id"].tolist() if int(pid) in set(attendee_ids)]
        missing = [pid for pid in attendee_ids if pid not in set(seeded)]
        seed_ids = seeded + sorted(missing)
else:
    ranked = live_rankings.sort_values(
        ["power_score", "wins", "point_diff", "elo_delta_tonight"],
        ascending=[False, False, False, False],
    )
    seeded = [int(pid) for pid in ranked["player_id"].tolist() if int(pid) in set(attendee_ids)]
    missing = [pid for pid in attendee_ids if pid not in set(seeded)]
    seed_ids = seeded + sorted(missing)

if len(seed_ids) < 4:
    st.caption("Need at least 4 attendees for playoff generation.")
else:
    playoff_rows = []
    quartet_count = len(seed_ids) // 4
    for i in range(quartet_count):
        group = seed_ids[i * 4 : (i + 1) * 4]
        label = finale_label_for_bracket(i)
        playoff_rows.append(
            {
                "Finale": f"Finale - {label}",
                "Team A (seed pair)": f"{i*4+1}+{i*4+4}",
                "Team A": f"{attendee_labels.get(group[0], group[0])} / {attendee_labels.get(group[3], group[3])}",
                "Team B (seed pair)": f"{i*4+2}+{i*4+3}",
                "Team B": f"{attendee_labels.get(group[1], group[1])} / {attendee_labels.get(group[2], group[2])}",
            }
        )
    if playoff_rows:
        st.dataframe(playoff_rows, use_container_width=True, hide_index=True)
    leftovers = seed_ids[quartet_count * 4 :]
    if leftovers:
        st.caption("Not enough players to seed final group: " + ", ".join(attendee_labels.get(pid, str(pid)) for pid in leftovers))

    with st.form("generate_playoffs"):
        clear_unplayed = st.checkbox(
            "Drop unplayed scheduled matches before playoffs",
            value=True,
            help="Use this if you are ending early and going straight to playoffs.",
        )
        generate_playoffs = st.form_submit_button("Generate Playoffs", type="primary")
        if generate_playoffs:
            try:
                result = schedule_service.generate_playoff_round(
                    event_id,
                    clear_unplayed=clear_unplayed,
                )
                bump_data_version()
                msg = (
                    f"Generated finale round {result['round_number']} with "
                    f"{result['matches_created']} matches"
                )
                if result.get("finale_labels"):
                    msg += " (" + ", ".join(f"Finale - {x}" for x in result["finale_labels"]) + ")"
                msg += "."
                if result["unseeded_players"]:
                    msg += " Unseeded this round: " + ", ".join(result["unseeded_players"])
                st.success(msg)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.divider()
with st.expander("Export / Upload schedule", expanded=False):
    exp_col, up_col = st.columns(2)

    with exp_col:
        st.markdown("**Export rounds**")
        if schedule_df.empty:
            st.caption("No matches to export yet.")
        else:
            export_rounds = sorted(
                schedule_df["round_number"].dropna().astype(int).unique().tolist()
            )
            selected_export_rounds = st.multiselect(
                "Rounds to export",
                options=export_rounds,
                default=export_rounds,
                help="Pick one or more rounds. Export includes date, round, court, players, teams, winner, and scores.",
            )
            if selected_export_rounds:
                export_src = schedule_df[
                    schedule_df["round_number"]
                    .astype(int)
                    .isin([int(r) for r in selected_export_rounds])
                ].copy()
                export_src = export_src.sort_values(
                    ["round_number", "match_order", "match_id"]
                )

                def _winning_team(row: pd.Series) -> str:
                    if pd.isna(row.get("team_a_score")) or pd.isna(
                        row.get("team_b_score")
                    ):
                        return ""
                    team_a = f"{row['a1']} / {row['a2']}"
                    team_b = f"{row['b1']} / {row['b2']}"
                    a_score = int(row["team_a_score"])
                    b_score = int(row["team_b_score"])
                    if a_score > b_score:
                        return team_a
                    if b_score > a_score:
                        return team_b
                    return ""

                export_df = pd.DataFrame(
                    {
                        "event_date": str(event.event_date),
                        "round": export_src["round_number"].astype(int),
                        "court": export_src["court"],
                        "player_a1": export_src["a1"],
                        "player_a2": export_src["a2"],
                        "player_b1": export_src["b1"],
                        "player_b2": export_src["b2"],
                        "team_a": export_src["a1"].astype(str)
                        + " / "
                        + export_src["a2"].astype(str),
                        "team_b": export_src["b1"].astype(str)
                        + " / "
                        + export_src["b2"].astype(str),
                        "winning_team": export_src.apply(_winning_team, axis=1),
                        "team_a_score": export_src["team_a_score"],
                        "team_b_score": export_src["team_b_score"],
                    }
                )
                csv_bytes = export_df.to_csv(index=False).encode("utf-8")
                round_label = "-".join(str(r) for r in selected_export_rounds)
                st.download_button(
                    "Download CSV",
                    data=csv_bytes,
                    file_name=f"pickle-export-{event.event_date}-rounds-{round_label}.csv",
                    mime="text/csv",
                    type="primary",
                )
                st.caption(f"{len(export_df)} match(es) ready to export.")
            else:
                st.caption("Select at least one round to export.")

    with up_col:
        st.markdown("**Upload schedule**")
        st.caption(
            "CSV columns: `round`, `court`, `player_a1`, `player_a2`, `player_b1`, `player_b2`. "
            "Scores are optional and ignored. Players must already be attendees."
        )
        template_csv = (
            "round,court,player_a1,player_a2,player_b1,player_b2\n"
            "1,1,Alex,Jordan,Sam,Taylor\n"
            "1,2,Chris,Morgan,Riley,Casey\n"
        )
        st.download_button(
            "Download blank template",
            data=template_csv.encode("utf-8"),
            file_name="pickle-schedule-template.csv",
            mime="text/csv",
            key="schedule_template_dl",
        )
        uploaded = st.file_uploader(
            "Schedule CSV", type=["csv"], key="schedule_upload_csv"
        )
        replace_unscored = st.checkbox(
            "Replace unscored scheduled matches",
            value=True,
            help="Keeps completed/scored matches. Clears other scheduled matches before import.",
        )
        if uploaded is not None:
            try:
                from import_.parsers import normalize_schedule_upload_df

                raw_df = pd.read_csv(uploaded)
                parsed_df = normalize_schedule_upload_df(raw_df)
                st.dataframe(
                    parsed_df[
                        [
                            "round_number",
                            "court",
                            "player_a1",
                            "player_a2",
                            "player_b1",
                            "player_b2",
                        ]
                    ].rename(columns={"round_number": "round"}),
                    use_container_width=True,
                    hide_index=True,
                )
                if st.button(
                    "Import schedule", type="primary", key="import_schedule_btn"
                ):
                    result = schedule_service.import_schedule(
                        event_id,
                        parsed_df.to_dict(orient="records"),
                        replace_unscored=replace_unscored,
                        name_to_id=player_name_to_id,
                    )
                    bump_data_version()
                    st.success(
                        f"Imported {result['created']} match(es)"
                        + (
                            f" (cleared {result['cleared_unscored']} unscored)."
                            if result["cleared_unscored"]
                            else "."
                        )
                    )
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read schedule CSV: {exc}")
