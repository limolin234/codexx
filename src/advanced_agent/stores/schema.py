from __future__ import annotations

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;



CREATE TABLE IF NOT EXISTS runtime_hooks (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  wake_at_ms INTEGER NOT NULL,
  payload_json TEXT,
  repeat_ms INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_hooks_due ON runtime_hooks(enabled, wake_at_ms);
CREATE INDEX IF NOT EXISTS idx_runtime_hooks_target ON runtime_hooks(target, kind);

CREATE TABLE IF NOT EXISTS runtime_events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_json TEXT,
  created_at_ms INTEGER NOT NULL,
  mono_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_type_created ON runtime_events(type, created_at_ms);
CREATE INDEX IF NOT EXISTS idx_runtime_events_source_created ON runtime_events(source, created_at_ms);

CREATE TABLE IF NOT EXISTS semantic_events (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  payload_json TEXT,
  content_hash TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  compacted INTEGER NOT NULL DEFAULT 0,
  consumed_by_small_ms INTEGER,
  consumed_by_big_ms INTEGER,
  UNIQUE(session_id, seq),
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semantic_summaries (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  from_seq INTEGER NOT NULL,
  to_seq INTEGER NOT NULL,
  summary TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  model_name TEXT,
  prompt_version TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semantic_tasks (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  kind TEXT NOT NULL,
  reason TEXT NOT NULL,
  from_seq INTEGER NOT NULL,
  to_seq INTEGER NOT NULL,
  input_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  locked_at_ms INTEGER,
  started_at_ms INTEGER,
  finished_at_ms INTEGER,
  error TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(session_id, kind, from_seq, to_seq, input_hash),
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semantic_memory_candidates (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  summary_id TEXT NOT NULL,
  candidate_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  content TEXT NOT NULL,
  explanation TEXT NOT NULL,
  evidence_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  importance REAL NOT NULL,
  confidence REAL NOT NULL,
  approved_memory_id TEXT,
  model_name TEXT,
  error TEXT,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(summary_id, candidate_type, evidence_hash),
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_semantic_events_session_seq ON semantic_events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_semantic_events_active ON semantic_events(session_id, compacted, seq);
CREATE INDEX IF NOT EXISTS idx_semantic_tasks_status ON semantic_tasks(status, updated_at_ms);
CREATE INDEX IF NOT EXISTS idx_semantic_candidates_status ON semantic_memory_candidates(status, updated_at_ms);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  status TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  compacted_into TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  seq INTEGER,
  created_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  compacted INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS interaction_streams (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  writer TEXT NOT NULL,
  authority TEXT NOT NULL,
  delta TEXT NOT NULL,
  supersedes_seq INTEGER,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS main_decisions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  intent TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  internal_summary TEXT NOT NULL,
  user_visible_instruction TEXT NOT NULL,
  task_requests_json TEXT,
  audit_status TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_main_decisions_request ON main_decisions(session_id, request_id, created_at_ms);

CREATE TABLE IF NOT EXISTS main_visible_state (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  status TEXT NOT NULL,
  visible_summary TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS interaction_state (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  status TEXT NOT NULL,
  last_sent_seq INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  role TEXT NOT NULL,
  backend TEXT NOT NULL,
  model TEXT,
  status TEXT NOT NULL,
  pid INTEGER,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  last_heartbeat_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS agent_processes (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  pid INTEGER,
  command TEXT,
  cwd TEXT,
  status TEXT,
  started_at_ms INTEGER,
  stopped_at_ms INTEGER,
  exit_code INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  owner_agent_id TEXT,
  backend TEXT NOT NULL,
  goal TEXT NOT NULL,
  workdir TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT,
  priority INTEGER NOT NULL DEFAULT 0,
  created_at_ms INTEGER NOT NULL,
  started_at_ms INTEGER,
  updated_at_ms INTEGER NOT NULL,
  finished_at_ms INTEGER,
  last_progress_at_ms INTEGER,
  last_heartbeat_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS task_state (
  task_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  stage TEXT,
  elapsed_ms INTEGER,
  idle_ms INTEGER,
  latest_summary TEXT,
  need_attention INTEGER NOT NULL DEFAULT 0,
  can_stop INTEGER NOT NULL DEFAULT 1,
  can_kill INTEGER NOT NULL DEFAULT 0,
  updated_at_ms INTEGER NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_events (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT,
  created_at_ms INTEGER NOT NULL,
  mono_ms INTEGER NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_output_chunks (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  stream TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_summaries (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  important_events_json TEXT,
  risks_json TEXT,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS control_commands (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  command TEXT NOT NULL,
  priority INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at_ms INTEGER NOT NULL,
  handled_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS interrupt_state (
  scope TEXT PRIMARY KEY,
  interrupt_enabled INTEGER NOT NULL DEFAULT 1,
  user_interrupt_enabled INTEGER NOT NULL DEFAULT 1,
  cooldown_until_ms INTEGER NOT NULL DEFAULT 0,
  window_started_at_ms INTEGER NOT NULL DEFAULT 0,
  interrupt_count INTEGER NOT NULL DEFAULT 0,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_reviews (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  action TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  request_payload_json TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  priority INTEGER NOT NULL,
  created_at_ms INTEGER NOT NULL
);


CREATE TABLE IF NOT EXISTS user_profiles (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  summary TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  confidence REAL NOT NULL,
  max_chars INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_overlays (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  target_agent TEXT NOT NULL,
  category TEXT NOT NULL,
  content TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  source TEXT,
  updated_at_ms INTEGER NOT NULL,
  max_chars INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_overlays_scope_agent ON prompt_overlays(scope, target_agent, status, priority);

CREATE TABLE IF NOT EXISTS memory_items (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT,
  summary TEXT NOT NULL,
  content TEXT,
  confidence REAL NOT NULL,
  importance REAL NOT NULL,
  status TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  source_ref TEXT,
  source_strength TEXT NOT NULL DEFAULT 'unknown',
  stability TEXT NOT NULL DEFAULT 'normal',
  usage_count INTEGER NOT NULL DEFAULT 0,
  last_used_at_ms INTEGER,
  last_evidence_at_ms INTEGER,
  supersedes_id TEXT,
  superseded_by TEXT,
  archived_at_ms INTEGER,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS memory_vectors (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  label_kind TEXT NOT NULL,
  vector_collection TEXT NOT NULL,
  vector_id TEXT NOT NULL,
  embedding_model TEXT,
  label_text TEXT,
  content_hash TEXT,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_facets (
  memory_id TEXT NOT NULL,
  facet_name TEXT NOT NULL,
  facet_text TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  created_at_ms INTEGER NOT NULL,
  PRIMARY KEY(memory_id, facet_name),
  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED,
  scope UNINDEXED,
  type UNINDEXED,
  summary,
  content,
  facets
);

CREATE TABLE IF NOT EXISTS session_injection_ledger (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  caller_session_id TEXT NOT NULL DEFAULT '',
  item_kind TEXT NOT NULL,
  item_id TEXT NOT NULL,
  item_version TEXT,
  source_tool TEXT NOT NULL,
  injected_at_ms INTEGER NOT NULL,
  UNIQUE(session_id, caller_session_id, item_kind, item_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at_ms);
CREATE INDEX IF NOT EXISTS idx_stream_request_seq ON interaction_streams(request_id, seq);
CREATE INDEX IF NOT EXISTS idx_tasks_session_updated ON tasks(session_id, updated_at_ms);
CREATE INDEX IF NOT EXISTS idx_task_output_task_seq ON task_output_chunks(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_control_status_priority ON control_commands(status, priority, created_at_ms);
CREATE INDEX IF NOT EXISTS idx_memory_scope_type ON memory_items(scope, type, status);
CREATE INDEX IF NOT EXISTS idx_memory_facets_name ON memory_facets(facet_name, memory_id);
CREATE INDEX IF NOT EXISTS idx_injection_ledger_session ON session_injection_ledger(session_id, caller_session_id, item_kind);
"""
