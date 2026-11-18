---
id: local-legal-doctrine-sqlite
kind: legal_corpus
jurisdictions: [RU]
capabilities: [legal_doctrine, civil_law, doctrine_sources]
access: local_files
authority_level: secondary_doctrine
adapter: sqlite_legal_doctrine
connection_ref: local-legal-doctrine-sqlite
protocol_refs:
  - tools/legal_overlay/README.md
  - references/source-hierarchy.md
  - references/query-cookbook.md
health_probe: sqlite_legal_doctrine_status
rate_limits: none_local_read_only
auth: null
status: active
data_policy: local_only
verification_roles: [navigation, doctrine]
coverage:
  document_types: [article_commentary_unit, legal_position, legal_literature_note]
  full_text: yes
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
  limitations: [doctrine_only, cited_norms_and_cases_require_separate_verification]
---

# Единый локальный корпус доктрины

Канонический локальный provider доктрины по российскому гражданскому праву.
Содержит постатейные комментарии, выделенные правовые позиции и литературные
заметки с provenance до произведения, страниц и текстовых offsets.

Все результаты имеют класс `doctrine_only`. Упомянутые нормы и судебные акты
нужно отдельно раскрывать и проверять по соответствующему первичному источнику.
