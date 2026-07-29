"""Application configuration defaults."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "pickleball.duckdb"

INITIAL_ELO = 1000.0
ELO_K = 24.0
# Newer players use a higher K until they finish this many games.
PROVISIONAL_GAMES = 10
PROVISIONAL_K_MULTIPLIER = 2.0
DEFAULT_GAME_TO = 11
DEFAULT_WIN_BY = 2
DEFAULT_NUM_COURTS = 2

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"

SCHEMA_VERSION = 3
