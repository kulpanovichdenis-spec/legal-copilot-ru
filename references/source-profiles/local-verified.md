---
id: local-verified
kind: internal_curated
jurisdictions: [RU, UZ, KZ]
capabilities: [verified_knowledge, knowledge_lifecycle]
access: local_files
authority_level: internal_human_verified
adapter: local_verified
connection_ref: local-verified
protocol_refs:
  - references/local-verified-knowledge-protocol.md
fallbacks: [local-curated]
health_probe: local_knowledge_counts
rate_limits: null
auth: null
status: active
data_policy: local_only
verification_roles: [navigation, internal_context]
coverage:
  document_types: [verified_knowledge_objects]
  full_text: yes
  historical_versions: no
  current_status: conditional
  pinpoint: conditional
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [internal_reusable_knowledge, underlying_sources_require_live_verification]
---

# Локальное проверенное знание

Provider хранит schema-validated reusable knowledge objects в личном профиле.
Поиск возвращает только объекты, прошедшие отдельный ручной promotion в
`human_verified`; кандидаты и superseded-объекты из активной выдачи исключены.
