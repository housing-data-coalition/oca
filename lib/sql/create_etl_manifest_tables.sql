CREATE TABLE IF NOT EXISTS etl_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    schema_name TEXT NOT NULL,
    s3_prefix TEXT NOT NULL DEFAULT '',
    mode TEXT,
    reprocess_glob TEXT,
    force_reprocess BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL,
    selected_file_count INTEGER NOT NULL DEFAULT 0,
    processed_file_count INTEGER NOT NULL DEFAULT 0,
    skipped_file_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    error_details JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_etl_runs_schema_started
    ON etl_runs (schema_name, started_at DESC);

CREATE TABLE IF NOT EXISTS etl_files (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES etl_runs (run_id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    error_details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_etl_files_name_status
    ON etl_files (file_name, status);

CREATE TABLE IF NOT EXISTS etl_steps (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES etl_runs (run_id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    error_details JSONB,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, step_name)
);
