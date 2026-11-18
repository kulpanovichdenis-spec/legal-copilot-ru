---
id: local-legal-ru-sqlite
kind: legal_corpus
jurisdictions: [RU, EAEU]
capabilities: [legal_corpus, legislation, case_positions, comments, relations]
access: local_files
authority_level: curated_corpus
adapter: sqlite_legal_ru
connection_ref: local-legal-ru-sqlite
protocol_refs:
  - tools/legal_overlay/README.md
  - references/legal-kb-usage.md
  - references/source-hierarchy.md
fallbacks: [pravo-gov-ru]
health_probe: sqlite_legal_ru_status
rate_limits: none_local_read_only
auth: null
status: active
data_policy: local_only
verification_roles: [navigation]
coverage:
  document_types: [legislation, case_positions, commentary, document_relations]
  full_text: conditional
  historical_versions: conditional
  current_status: no
  pinpoint: yes
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [immutable_snapshot, current_edition_requires_live_verification]
---

# Локальный корпус права РФ и ЕАЭС

Основной локальный provider для тематического поиска, норм, практики, комментариев
и связей. Snapshot открывается только как `mode=ro&immutable=1` после проверки
manifest, SHA-256, схемы и целостности. Корпусная карточка является навигацией:
действующую редакцию и дословный текст значимой нормы проверять через официальный
источник.
