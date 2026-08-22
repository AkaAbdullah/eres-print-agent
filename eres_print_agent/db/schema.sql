CREATE TABLE IF NOT EXISTS print_jobs (
  job_id            TEXT PRIMARY KEY,
  printer_local_id  TEXT NOT NULL,
  document_type     TEXT NOT NULL,
  document_id       TEXT NOT NULL,
  document_url      TEXT NOT NULL,
  copies            INTEGER NOT NULL DEFAULT 1,
  status            TEXT NOT NULL,
  error_code        TEXT,
  error_message     TEXT,
  local_file_path   TEXT,
  attempts          INTEGER NOT NULL DEFAULT 0,
  received_at       TEXT,
  started_at        TEXT,
  completed_at      TEXT,
  failed_at         TEXT,
  cancelled_at      TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status);

CREATE TABLE IF NOT EXISTS agent_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
