PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  source_type TEXT NOT NULL,
  authority_level TEXT NOT NULL,
  publisher TEXT,
  url TEXT NOT NULL,
  source_date TEXT,
  effective_from TEXT,
  effective_to TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  notes TEXT
);

CREATE TABLE IF NOT EXISTS rules (
  rule_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  authority_type TEXT NOT NULL,
  rule_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  applicability TEXT,
  domain TEXT,
  source_id TEXT NOT NULL,
  source_locator TEXT,
  valid_from TEXT,
  valid_to TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  case_type TEXT NOT NULL,
  authority_body TEXT,
  decision_date TEXT,
  outcome TEXT,
  summary TEXT NOT NULL,
  primary_source_id TEXT NOT NULL,
  source_locator TEXT,
  foreign_pattern_only INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (primary_source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS patterns (
  pattern_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  pattern_type TEXT NOT NULL,
  jurisdiction_scope TEXT NOT NULL,
  domain TEXT NOT NULL,
  risk_dimension TEXT,
  severity_hint TEXT,
  description TEXT NOT NULL,
  legitimate_explanation TEXT,
  aggravating_factors TEXT,
  mitigating_factors TEXT,
  evidentiary_significance TEXT,
  russian_legal_relevance TEXT,
  foreign_pattern INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS controls (
  control_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  control_type TEXT NOT NULL,
  domain TEXT NOT NULL,
  description TEXT NOT NULL,
  expected_evidence TEXT,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS case_patterns (
  case_id TEXT NOT NULL,
  pattern_id TEXT NOT NULL,
  treatment TEXT,
  notes TEXT,
  PRIMARY KEY (case_id, pattern_id),
  FOREIGN KEY (case_id) REFERENCES cases(case_id),
  FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id)
);

CREATE TABLE IF NOT EXISTS pattern_controls (
  pattern_id TEXT NOT NULL,
  control_id TEXT NOT NULL,
  relation TEXT,
  PRIMARY KEY (pattern_id, control_id),
  FOREIGN KEY (pattern_id) REFERENCES patterns(pattern_id),
  FOREIGN KEY (control_id) REFERENCES controls(control_id)
);

CREATE TABLE IF NOT EXISTS entity_tags (
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  PRIMARY KEY (entity_type, entity_id, tag)
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
  entity_type UNINDEXED,
  entity_id UNINDEXED,
  title,
  body,
  tags,
  tokenize='unicode61'
);

CREATE INDEX IF NOT EXISTS idx_rules_domain ON rules(domain);
CREATE INDEX IF NOT EXISTS idx_rules_jurisdiction ON rules(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_cases_jurisdiction ON cases(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_patterns_domain ON patterns(domain);
CREATE INDEX IF NOT EXISTS idx_patterns_risk ON patterns(risk_dimension);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON entity_tags(tag);
