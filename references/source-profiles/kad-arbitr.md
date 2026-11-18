---
id: kad-arbitr
kind: official_portal
jurisdictions: [RU]
capabilities: [arbitration_cases, court_documents]
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
auth: local_browser_session_if_required
status: manual_only
data_policy: abstracted_issue_only
verification_roles: [navigation, case_law_verification]
coverage:
  document_types: [arbitration_case_cards, arbitration_court_decisions]
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

# Картотека арбитражных дел

Использовать для проверки карточки дела и судебных актов. Реквизиты выводятся как
подтверждённые только после открытия первоисточника; материалы дела не отправляются
во внешние сервисы без отдельного разрешения.
