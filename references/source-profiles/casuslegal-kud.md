---
id: casuslegal-kud
kind: commercial_provider
jurisdictions: [RU]
capabilities: [criminal_procedure, supreme_court]
access: mcp
authority_level: secondary_navigation
adapter: remote_legal_mcp
connection_ref: casuslegal-kud
protocol_refs:
  - references/external-legal-databases.md
  - references/case-law-search.md
fallbacks: [vsrf]
health_probe: tools/list
rate_limits: account_and_offer_dependent
auth: oauth_user_login
status: auth_required
data_policy: abstracted_issue_only
verification_roles: [navigation]
coverage:
  document_types: [criminal_court_decisions, supreme_court_decisions]
  full_text: conditional
  historical_versions: no
  current_status: conditional
  pinpoint: conditional
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [court_practice_only, corpus_scope_is_criminal_procedure]
---

# Casus: уголовное судопроизводство

Специализированный корпус уголовной коллегии и президиума ВС РФ. Не смешивать
с административным или гражданским поиском; цитаты сверять по полному акту.
