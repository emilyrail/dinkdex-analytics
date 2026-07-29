# DinkDex Analytics

Local-first pickleball analytics for competitive game nights.

Built with **Python**, **Streamlit**, **DuckDB**, **Pandas**, **Plotly**, and optional **Ollama** for AI recaps. Everything runs on your laptop — no cloud services.

## Quick start

```bash
cd pickle
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## First-night setup

1. **Players** — add your roster (or use **Load demo roster** in the sidebar).
2. **Home** — create an event and select attendees (or set status to live).
3. **Schedule Builder** — save attendees/courts, then **Generate** a rotation schedule (or add matches manually).
4. **Score Entry** — enter scores; undo / edit corrections are available.
5. **Dashboard** — live standings, Elo, and recent results.

## Data

DuckDB file lives at `data/pickleball.duckdb` (gitignored). Back it up by copying that file.

## What's working now

- Players & events
- Manual schedule + social-rotation generator (equal games, sit-outs, partner rotation, optional Elo balance)
- Live score entry, undo, score edit
- Elo + event standings recompute
- Dashboard standings

## Coming next

- Deeper analytics (partners, H2H, SOS, trends)
- CSV historical import
- Ollama match/weekly recaps
