---
id: vsrf
kind: official_portal
jurisdictions: [RU]
capabilities: [supreme_court_practice, court_documents, reviews]
access: browser
authority_level: official_primary
adapter: null
connection_ref: null
protocol_refs:
  - references/web-research-tools.md
  - references/court-decision-analysis.md
fallbacks: [commercial-legal-systems]
health_probe: null
rate_limits: portal_dependent
auth: null
status: manual_only
data_policy: public_only
verification_roles: [navigation, case_law_verification]
coverage:
  document_types: [supreme_court_decisions, supreme_court_reviews]
  full_text: yes
  historical_versions: no
  current_status: yes
  pinpoint: yes
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [court_practice_only, not_a_normative_act_source]
---

# Верховный Суд Российской Федерации

Использовать как официальный источник актов и обзоров по правилам иерархии
источников. Поиск является навигацией; точные реквизиты сверяются по открытому
документу.
