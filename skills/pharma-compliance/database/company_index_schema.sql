PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS company_manifest (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_documents (
  document_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  document_type TEXT,
  version TEXT,
  status TEXT NOT NULL,
  effective_from TEXT,
  effective_to TEXT,
  authority_rank INTEGER,
  owner_function TEXT,
  original_path TEXT NOT NULL,
  source_hash TEXT
);

CREATE TABLE IF NOT EXISTS company_cards (
  card_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  card_type TEXT NOT NULL,
  title TEXT NOT NULL,
  normalized_rule TEXT NOT NULL,
  scope_json TEXT,
  conditions_json TEXT,
  exceptions_json TEXT,
  approvals_json TEXT,
  thresholds_json TEXT,
  documentation_json TEXT,
  escalation_json TEXT,
  related_domains_json TEXT,
  related_patterns_json TEXT,
  source_locator TEXT,
  effective_from TEXT,
  effective_to TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  FOREIGN KEY (document_id) REFERENCES company_documents(document_id)
);

CREATE TABLE IF NOT EXISTS coverage (
  category TEXT PRIMARY KEY,
  loaded INTEGER NOT NULL,
  current INTEGER,
  verified INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS local_conflicts (
  conflict_id TEXT PRIMARY KEY,
  card_id_a TEXT NOT NULL,
  card_id_b TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  description TEXT,
  FOREIGN KEY (card_id_a) REFERENCES company_cards(card_id),
  FOREIGN KEY (card_id_b) REFERENCES company_cards(card_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS company_fts USING fts5(
  card_id UNINDEXED,
  title,
  normalized_rule,
  tags,
  tokenize='unicode61'
);
