-- Unified Schema for Prompt Studio

-- 1. Sessions (Sandbox)
-- Stores the live iteration state from the Sandbox.
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pane_count INTEGER DEFAULT 1, -- 1 or 2 (A/B compare)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    data TEXT NOT NULL -- JSON blob: { panes: [...], vault: {...}, topK: 5, etc. }
);

-- 2. Registered Prompts (Registry)
-- Stores production-ready prompts and their metadata.
CREATE TABLE IF NOT EXISTS registered_prompts (
    id TEXT NOT NULL, -- snake_case identifier (e.g., "consensus_protocol")
    version TEXT NOT NULL, -- semver (e.g., "1.1.0")
    status TEXT CHECK(status IN ('draft', 'production', 'active', 'deprecated')) DEFAULT 'draft',
    tier TEXT CHECK(tier IN ('audit', 'advisory', 'reference', 'utility')),
    owner TEXT,
    body TEXT NOT NULL,
    use_case TEXT,
    eval_status TEXT DEFAULT 'pending',
    
    -- Contract, Dependencies, Context Profile, and Value Surface as JSON
    contract TEXT, -- JSON blob (input_schema, output_schema, etc.)
    dependencies TEXT, -- JSON blob (tools, model_class, composition, etc.)
    context_profile TEXT, -- JSON blob (token counts, costs, etc.)
    value_surface TEXT, -- JSON blob (invocations, attributed_value, etc.)
    
    metadata TEXT, -- JSON blob for 'tags', 'purpose', etc.
    file_path TEXT, -- Optional pointer to the .md file in the repo
    notes TEXT,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, version)
);

-- 3. Evaluation Batches
-- Groups evaluation runs.
CREATE TABLE IF NOT EXISTS eval_batches (
    id TEXT PRIMARY KEY, -- e.g. "eval_batch_001"
    name TEXT NOT NULL,
    directive TEXT, -- The input directive used for the batch
    headline_finding TEXT,
    file_path TEXT, -- Pointer to evals/eval_batch_001.md
    data_file_path TEXT, -- Pointer to evals/eval_batch_001_data.json
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4. Evaluation Results (Evaluations)
-- Individual runs of a prompt against a model in a batch.
CREATE TABLE IF NOT EXISTS evaluation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    score REAL, -- Could be delta score or grade numeric mapping
    grade TEXT, -- A, B, C, F
    output TEXT, -- The raw output from the model
    notes TEXT,
    raw_data TEXT, -- JSON blob for detailed signals/metrics
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prompt_id, prompt_version) REFERENCES registered_prompts(id, version),
    FOREIGN KEY (batch_id) REFERENCES eval_batches(id)
);

-- 5. Models
-- Known models and their specs.
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY, -- e.g. "claude-opus-4.7"
    name TEXT NOT NULL,
    provider TEXT,
    endpoint TEXT,
    context_window INTEGER,
    model_class TEXT CHECK(model_class IN ('frontier', 'mid', 'budget', 'any')),
    metadata TEXT, -- JSON blob
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
