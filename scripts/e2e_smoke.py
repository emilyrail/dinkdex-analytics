"""End-to-end smoke test for tonight readiness."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from database.connection import close_connection, reset_connection
from database.migrate import init_db
from import_.parsers import normalize_schedule_upload_df
from models.enums import EventStatus
from services.analytics_service import AnalyticsService
from services.event_service import EventService
from services.player_service import PlayerService
from services.recompute_service import RecomputeService
from services.schedule_service import ScheduleService
from services.score_service import ScoreService

TEST_NAME = "__E2E_SMOKE_TEST__"


def cleanup(conn, event_id: int | None) -> None:
    if event_id is None:
        return
    mids = [
        int(r[0])
        for r in conn.execute("SELECT id FROM matches WHERE event_id=?", [event_id]).fetchall()
    ]
    for mid in mids:
        conn.execute("DELETE FROM scores WHERE match_id=?", [mid])
        conn.execute("DELETE FROM elo_history WHERE match_id=?", [mid])
        conn.execute("DELETE FROM match_summaries WHERE match_id=?", [mid])
        conn.execute("DELETE FROM matches WHERE id=?", [mid])
    conn.execute("DELETE FROM event_standings WHERE event_id=?", [event_id])
    conn.execute("DELETE FROM event_players WHERE event_id=?", [event_id])
    conn.execute("DELETE FROM events WHERE id=?", [event_id])
    print(f"cleaned event {event_id}")


def main() -> int:
    close_connection()
    conn = init_db()
    print("schema", conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone())

    event_service = EventService()
    player_service = PlayerService()
    schedule_service = ScheduleService()
    score_service = ScoreService()
    analytics = AnalyticsService()
    recompute = RecomputeService()

    leftovers = conn.execute("SELECT id FROM events WHERE name=?", [TEST_NAME]).fetchall()
    for (eid,) in leftovers:
        cleanup(conn, int(eid))

    players = player_service.list_players(active_only=True)
    if len(players) < 8:
        players = player_service.list_players(active_only=False)
    assert len(players) >= 8, f"Need >=8 players, found {len(players)}"
    attendee_ids = [p.id for p in players[:8]]
    print("attendees", [p.label for p in players[:8]])

    event = event_service.create_event(
        TEST_NAME,
        date.today(),
        player_ids=attendee_ids,
        num_courts=2,
    )
    event_service.set_status(event.id, EventStatus.LIVE)
    event_id = event.id
    print(f"created event {event_id}")

    errors: list[str] = []

    try:
        schedule_service.generate_schedule(
            event_id, num_rounds=3, seed=7, replace_existing=True, balance_elo=True
        )
        sched = schedule_service.schedule_df(event_id)
        assert not sched.empty, "schedule empty after generate"
        assert "round_number" in sched.columns, f"missing round_number cols={list(sched.columns)}"
        assert "status" in sched.columns, "missing status"
        n_matches = len(sched)
        print(
            f"schedule OK: {n_matches} matches, rounds="
            f"{sorted(sched['round_number'].astype(int).unique().tolist())}"
        )

        for rnd, g in sched.groupby("round_number"):
            ids: list[int] = []
            for _, row in g.iterrows():
                ids.extend(
                    [int(row["a1_id"]), int(row["a2_id"]), int(row["b1_id"]), int(row["b2_id"])]
                )
            if len(ids) != len(set(ids)):
                errors.append(f"duplicate players in round {rnd}")

        matches = schedule_service.list_matches(event_id)
        saved = 0
        for i, match in enumerate(matches):
            a = 11
            b = 5 + (i % 5)
            if i % 7 == 0:
                a, b = 9, 11
            score_service.submit_score(
                match.id, a, b, game_to=11, win_by=2, strict=True, rebuild=False
            )
            saved += 1
        print(f"submitted {saved} scores (rebuild deferred)")

        recompute.rebuild_all()
        print("rebuild_all OK")

        reset_connection()
        conn = init_db()
        event_service = EventService()
        schedule_service = ScheduleService()
        score_service = ScoreService()
        analytics = AnalyticsService()
        recompute = RecomputeService()

        ev = event_service.get_event(event_id)
        assert ev is not None and ev.name == TEST_NAME, "get_event failed after reconnect"
        print("get_event after reset OK")

        sched2 = schedule_service.schedule_df(event_id)
        assert "round_number" in sched2.columns and "status" in sched2.columns
        completed = sched2[sched2["status"] == "completed"]
        assert len(completed) == n_matches, f"expected {n_matches} completed, got {len(completed)}"
        print(f"schedule reload OK: {len(completed)} completed")

        standings = recompute.standings_df(event_id)
        assert not standings.empty, "standings empty"
        assert len(standings) >= 8, f"standings rows {len(standings)}"
        view = standings.copy()
        view["Player"] = view["display_name"].fillna(view["name"])
        print("standings OK:")
        print(view[["Player", "wins", "losses", "point_diff", "elo"]].head(8).to_string(index=False))

        live = analytics.live_event_player_metrics(event_id)
        assert not live.empty, "live metrics empty"
        needed = {"rank", "player", "wins", "point_diff", "elo_delta_tonight", "momentum"}
        assert needed.issubset(live.columns), f"live missing {needed - set(live.columns)}"
        leader = live.sort_values(["wins", "point_diff"], ascending=False).iloc[0]["player"]
        print(f"live metrics OK: {len(live)} players, leader={leader}")

        scatter = analytics.live_event_scatter(event_id)
        assert not scatter.empty
        print(f"scatter OK: {len(scatter)} points")

        upset = analytics.live_event_biggest_upset(event_id)
        closest = analytics.live_event_closest_match(event_id)
        print(f"upset={'set' if upset else 'none'} closest={'set' if closest else 'none'}")
        if closest:
            assert "team_a" in closest and "score" in closest

        partners = analytics.event_best_partners(event_id)
        print(f"best partners rows={len(partners)}")

        playoff = schedule_service.generate_playoff_round(event_id, clear_unplayed=True)
        assert playoff["round_number"] == 99, f"finale round expected 99 got {playoff['round_number']}"
        assert playoff["matches_created"] >= 1
        print(
            f"playoffs OK: round={playoff['round_number']} matches={playoff['matches_created']} "
            f"labels={playoff.get('finale_labels')}"
        )
        assert playoff.get("finale_labels"), "expected finale labels"
        assert playoff["finale_labels"][0] == "Top Seed"
        if len(playoff["finale_labels"]) > 1:
            assert playoff["finale_labels"][1] == "2"

        finale = schedule_service.schedule_df(event_id)
        finale = finale[finale["is_finale"].astype(bool)]
        assert len(finale) == playoff["matches_created"]
        assert set(finale["round_number"].astype(int).unique().tolist()) == {99}
        print("finale flags OK")

        finale_matches = [m for m in schedule_service.list_matches(event_id) if m.is_finale]
        for i, m in enumerate(finale_matches):
            score_service.submit_score(m.id, 11, 6 + (i % 3), rebuild=False)
        recompute.rebuild_all()
        reset_connection()
        conn = init_db()
        schedule_service = ScheduleService()
        analytics = AnalyticsService()
        event_service = EventService()
        recompute = RecomputeService()

        assert event_service.get_event(event_id) is not None
        final_sched = schedule_service.schedule_df(event_id)
        assert "round_number" in final_sched.columns
        assert (final_sched["status"] == "completed").all()
        print("post-finale reload OK")

        player_service = PlayerService()
        labels = {p.id: p.label for p in player_service.list_players(active_only=False)}
        a, b, c, d = [labels[i] for i in attendee_ids[:4]]
        upload = normalize_schedule_upload_df(
            pd.DataFrame(
                [
                    {
                        "round": 1,
                        "court": 1,
                        "player_a1": a,
                        "player_a2": b,
                        "player_b1": c,
                        "player_b2": d,
                    },
                ]
            )
        )
        assert int(upload.iloc[0]["round_number"]) == 1
        print("schedule upload parser OK")

        for _ in range(3):
            recompute.rebuild_all()
            reset_connection()
            conn = init_db()
            event_service = EventService()
            recompute = RecomputeService()
            assert event_service.get_event(event_id) is not None
        print("rebuild/reset stress OK")

    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            reset_connection()
            conn = init_db()
            leftovers = conn.execute("SELECT id FROM events WHERE name=?", [TEST_NAME]).fetchall()
            for (eid,) in leftovers:
                cleanup(conn, int(eid))
            RecomputeService().rebuild_all()
            print("final elo rebuild after cleanup OK")
        except Exception as cleanup_exc:
            errors.append(f"cleanup: {cleanup_exc}")
            import traceback

            traceback.print_exc()

    if errors:
        print("\nFAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("\nPASS: end-to-end smoke test succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
