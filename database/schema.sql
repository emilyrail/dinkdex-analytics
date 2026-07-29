-- Pickleball analytics schema (version 1)

CREATE TABLE IF NOT EXISTS app_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    display_name VARCHAR,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    current_elo DOUBLE NOT NULL DEFAULT 1000.0,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS players_id_seq START 1;
ALTER TABLE players ALTER COLUMN id SET DEFAULT nextval('players_id_seq');

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'draft',
    game_to INTEGER NOT NULL DEFAULT 11,
    win_by INTEGER NOT NULL DEFAULT 2,
    num_courts INTEGER NOT NULL DEFAULT 2,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS events_id_seq START 1;
ALTER TABLE events ALTER COLUMN id SET DEFAULT nextval('events_id_seq');

CREATE TABLE IF NOT EXISTS event_players (
    event_id INTEGER NOT NULL REFERENCES events(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    PRIMARY KEY (event_id, player_id)
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    player1_id INTEGER NOT NULL REFERENCES players(id),
    player2_id INTEGER NOT NULL REFERENCES players(id),
    UNIQUE (player1_id, player2_id),
    CHECK (player1_id < player2_id)
);

CREATE SEQUENCE IF NOT EXISTS teams_id_seq START 1;
ALTER TABLE teams ALTER COLUMN id SET DEFAULT nextval('teams_id_seq');

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    source_filename VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'committed',
    row_count INTEGER NOT NULL DEFAULT 0,
    notes VARCHAR,
    imported_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS import_batches_id_seq START 1;
ALTER TABLE import_batches ALTER COLUMN id SET DEFAULT nextval('import_batches_id_seq');

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id),
    round_number INTEGER NOT NULL DEFAULT 1,
    match_order INTEGER NOT NULL DEFAULT 1,
    court INTEGER,
    team_a_id INTEGER NOT NULL REFERENCES teams(id),
    team_b_id INTEGER NOT NULL REFERENCES teams(id),
    status VARCHAR NOT NULL DEFAULT 'scheduled',
    import_batch_id INTEGER,
    scheduled_at TIMESTAMP,
    is_finale BOOLEAN DEFAULT FALSE,
    finale_label VARCHAR,
    CHECK (team_a_id <> team_b_id)
);

CREATE SEQUENCE IF NOT EXISTS matches_id_seq START 1;
ALTER TABLE matches ALTER COLUMN id SET DEFAULT nextval('matches_id_seq');

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL UNIQUE,
    team_a_score INTEGER NOT NULL,
    team_b_score INTEGER NOT NULL,
    winner_team_id INTEGER NOT NULL,
    submitted_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS scores_id_seq START 1;
ALTER TABLE scores ALTER COLUMN id SET DEFAULT nextval('scores_id_seq');

CREATE TABLE IF NOT EXISTS elo_history (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    elo_before DOUBLE NOT NULL,
    elo_after DOUBLE NOT NULL,
    delta DOUBLE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS elo_history_id_seq START 1;
ALTER TABLE elo_history ALTER COLUMN id SET DEFAULT nextval('elo_history_id_seq');

CREATE TABLE IF NOT EXISTS event_standings (
    event_id INTEGER NOT NULL REFERENCES events(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    points_for INTEGER NOT NULL DEFAULT 0,
    points_against INTEGER NOT NULL DEFAULT 0,
    point_diff DOUBLE NOT NULL DEFAULT 0,
    win_pct DOUBLE NOT NULL DEFAULT 0,
    elo DOUBLE NOT NULL DEFAULT 1000.0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, player_id)
);

CREATE TABLE IF NOT EXISTS match_summaries (
    match_id INTEGER PRIMARY KEY,
    summary_text VARCHAR NOT NULL,
    model_name VARCHAR,
    generated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    entity_type VARCHAR NOT NULL,
    entity_id INTEGER,
    action VARCHAR NOT NULL,
    before_json VARCHAR,
    after_json VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE SEQUENCE IF NOT EXISTS audit_log_id_seq START 1;
ALTER TABLE audit_log ALTER COLUMN id SET DEFAULT nextval('audit_log_id_seq');

CREATE INDEX IF NOT EXISTS idx_matches_event_order
    ON matches (event_id, match_order);
CREATE INDEX IF NOT EXISTS idx_scores_match
    ON scores (match_id);
CREATE INDEX IF NOT EXISTS idx_elo_player_created
    ON elo_history (player_id, created_at);
CREATE INDEX IF NOT EXISTS idx_event_players_event
    ON event_players (event_id);
CREATE INDEX IF NOT EXISTS idx_matches_import_batch
    ON matches (import_batch_id);
