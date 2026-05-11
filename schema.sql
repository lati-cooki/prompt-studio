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
