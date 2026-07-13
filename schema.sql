CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    panes TEXT NOT NULL,
    vault_config TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC);

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT,
    tier TEXT,
    owner TEXT,
    body TEXT,
    use_case TEXT,
    cost_per_run_usd REAL,
    tokens_prompt_body INTEGER,
    default_model TEXT,
    eval_status TEXT,
    file TEXT,
    notes TEXT,
    composes TEXT,
    tested_on TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS evals (
    id TEXT PRIMARY KEY,
    directive TEXT,
    date TEXT,
    prompt_under_test TEXT,
    headline_finding TEXT,
    file TEXT,
    data_file TEXT,
    models_tested TEXT
);

-- Phase 5 slice 2: one DISTINCT custodial ThreadHub identity per studio writer
-- (DR-phase5-topology 5.2). Custodial: the hub holds keys; only the id lives here (5.5).
CREATE TABLE IF NOT EXISTS writers (
    name TEXT PRIMARY KEY,
    threadhub_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    custodial INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL,
    version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    opened_at TEXT NOT NULL,
    window_hours REAL NOT NULL DEFAULT 24,
    closes_at TEXT NOT NULL,
    resolved_at TEXT,
    evidence_json TEXT,
    thread_slug TEXT,
    citation_hash TEXT,
    sealed INTEGER NOT NULL DEFAULT 0,
    seal_error TEXT,
    waive_reason TEXT
);

CREATE TABLE IF NOT EXISTS promotion_objections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL,
    raised_at TEXT NOT NULL,
    body TEXT NOT NULL,
    resolution TEXT,
    resolution_body TEXT
);
