---
id: local-legal-uz-sqlite
kind: legal_corpus
jurisdictions: [UZ]
capabilities: [legal_corpus, legislation, uzbekistan]
access: local_files
authority_level: curated_corpus
adapter: sqlite_legal_uz
connection_ref: local-legal-uz-sqlite
protocol_refs:
  - tools/legal_overlay/README.md
  - references/source-hierarchy.md
fallbacks: []
health_probe: uzbek_legal_status
rate_limits: none_local_read_only
auth: null
status: active
data_policy: local_only
verification_roles: [navigation]
coverage:
  document_types: [uzbekistan_legislation, legal_cards]
  full_text: conditional
  historical_versions: no
  current_status: no
  pinpoint: yes
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [immutable_snapshot, lex_uz_live_verification_required, not_verified_status_must_be_preserved]
---

# Локальный корпус права Узбекистана

Использовать только для юрисдикции UZ. Adapter сохраняет `verification_status`
каждого документа; записи `not_verified` не выдаются за проверенный официальный
текст. Для правового вывода существенную формулировку сверять с `lex.uz`.
