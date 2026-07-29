# Pickle App - Agent Handoff

This file is the transfer document for future agents working on this project.

## Project Summary

- App: local-first pickleball analytics
- Stack: Python, Streamlit, DuckDB, Pandas, Plotly, requests (for Ollama)
- Runs fully offline on laptop; optional local Ollama endpoint for AI text
- One match = one game to 11, win by 2 (configurable)

## Current Status (Implemented)

### Core
- Players CRUD page (`pages/4_Players.py`)
- Event creation on Home; active-event selectors on Schedule Builder and Match Central
- Manual schedule builder + schedule generation (`pages/3_Schedule_Builder.py`)
- Social rotation scheduler (`scheduling/social_rotation.py` and related modules)
- Score entry with round table editor and round pagination (`pages/2_Score_Entry.py`)
- Undo/edit score logic (`services/score_service.py`)
- Recompute Elo + standings (`services/recompute_service.py`)
- Match Central (`pages/10_Live_Event_Dashboard.py`) is the consolidated live/event dashboard
  - game-night selector, KPIs, Live Rankings, leader charts, Winners Club/podium,
    partnerships, closest match, Win % vs SOS, Elo change, recent results, and recap
  - old `pages/1_Dashboard.py` was deleted and removed from navigation
- Player Profiles with visuals (`pages/5_Player_Profiles.py`)
- Overall Analytics (`pages/6_Analytics.py`) has game-night cohort selection, compact filters,
  combined Standings & Trends, scatterplots, heatmaps, and silly scouting notes
- Historical CSV import page and service (`pages/8_Data_Import.py`, `services/import_service.py`)
- LLM recap service via Ollama (`services/llm_service.py`, `llm/*`); the recap is on Match
  Central and is constrained to three fact-rooted bullets
- Event status controls (draft/scheduled/live/completed) live at the top of Schedule Builder

### Theme/UI
- Theme and sidebar styling set to green/tan palette
- Requested dark green: `#1A2421`

## Important Decisions

- Local DuckDB file path: `data/pickleball.duckdb`
- Event statuses: `draft`, `scheduled`, `live`, `completed`
- Match statuses: `scheduled`, `in_progress`, `completed`, `skipped`
- Elo starts at 1000 with normal K=24. A player is **Provisional** for fewer than 10
  completed games and uses 2x K (48) for each of those games. Per-player K is supported,
  so provisional and established teammates may receive different deltas.
- Finale matches always use dedicated round `99`.
- Finale seeding uses the same Live Rankings power score as Match Central:
  `win_pct*60 + avg_point_diff*4 + elo_delta_tonight*1.2 + wins*2`.
- Finale groups are ordered by power-rank places 1-4, 5-8, 9-12, etc. Pairing within
  each quartet is 1+4 vs 2+3. Labels are `Finale - Top Seed`, then `Finale - 2`,
  `Finale - 3`, etc.
- Live Rankings movement compares the current power rank with the snapshot immediately
  before the most recently completed match (not the previous round).
- Live SOS is average opponent-team pre-match Elo. The UI explicitly notes that the
  current power formula rewards who a player beat (Elo) more than winning margin (PD).
- Import canonical schema supports:
  - required: `event_date, player_a1, player_a2, player_b1, player_b2, score_a, score_b`
  - optional: `event_name, round_number, match_order, court`
- If Ollama is unavailable, app should degrade gracefully with an error message, not crash.
- There is intentionally no PDF download and no Live AI Feed on Match Central.

## Known DuckDB Constraint Caveat

DuckDB FK behavior caused issues when updating referenced player rows.

### Current workaround
- `PlayerRepository.update()` has:
  - fast path for active toggle only (in-place update)
  - re-key workflow for identity edits (name/display), with reference remap
  - may mark old player as hidden via `app_meta` key `hidden_player_<id>` if old row cannot be deleted

### Why this exists
- Direct parent updates can fail with FK constraints in this schema/runtime.

## Files Most Likely To Touch Next

- `repositories/players.py` (if further player-edit edge cases appear)
- `services/analytics_service.py` (expand metrics)
- `pages/2_Score_Entry.py` (faster data-entry UX)
- `pages/6_Analytics.py` (more visuals/filters)
- `pages/10_Live_Event_Dashboard.py` (Match Central UI)
- `pages/3_Schedule_Builder.py` (schedule/finale UI and event status)
- `services/import_service.py` (dedupe, better mapping, batch rollback)

## Runtime Commands

```bash
cd /Users/emilyrail/Desktop/pickle
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Data Import Workflow

1. Open Data Import page.
2. Download template or upload CSV.
3. Validate preview.
4. Click Import.
5. Import service writes events/matches/scores and rebuilds Elo/standings.

## Quick Smoke Checks

```bash
cd /Users/emilyrail/Desktop/pickle
source .venv/bin/activate
python -m compileall pages app.py services repositories scheduling
```

Full throwaway event flow:

```bash
python scripts/e2e_smoke.py
```

If DB lock errors appear:
- stop running Streamlit process first, then rerun scripts.

## Current App URL

Typically runs on one of:
- `http://localhost:8501`
- `http://localhost:8502`
- `http://localhost:8503`

Use terminal output for current port.

## Open Enhancements / TODO Ideas

- Add keyboard-first score table flow (enter-to-next-cell)
- Add true round pagination for >10 rounds (currently button strip is capped)
- Add robust name-merge tool for duplicate players
- Add import dedupe by event+match signature
- Add export backup/restore UI
- Add richer LLM prompts with event highlights and rivalry summaries

## If Something Looks Wrong

- Rebuild derived tables from Settings page: "Rebuild Elo & standings"
- Confirm the active event with the selector on Schedule Builder or Match Central
- Check score/match statuses in `matches` and `scores`
- Inspect `app_meta` for hidden-player markers

