---
id: casuslegal-unified
kind: commercial_provider
jurisdictions: [RU]
capabilities: [constitutional_court, supreme_court, supreme_arbitration_court, intellectual_property, administrative_procedure, criminal_procedure]
access: mcp
authority_level: secondary_navigation
adapter: remote_legal_mcp
connection_ref: casuslegal-unified
protocol_refs:
  - references/external-legal-databases.md
  - references/case-law-search.md
fallbacks: [local-legal-ru-sqlite, vsrf, kad-arbitr]
health_probe: tools/list
rate_limits: account_and_offer_dependent
auth: oauth_user_login
status: auth_required
data_policy: abstracted_issue_only
verification_roles: [navigation, case_law_verification]
coverage:
  document_types: [constitutional_court_decisions, supreme_court_decisions, supreme_arbitration_court_decisions, intellectual_property_court_decisions, administrative_case_decisions, criminal_case_decisions]
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
  limitations: [court_practice_only, paid_corpora_depend_on_user_subscription, official_cross_check_required]
---

# Casus: единый коннектор

Единая точка доступа к оплаченным пользователем корпусам CasusLegal. Корпус
выбирается параметром tool-вызова; отсутствие корпуса в активной подписке нельзя
подменять выводом об отсутствии практики. Поисковую карточку раскрывать до полного
текста, adverse-поиск проводить отдельно, реквизиты и цитаты сверять с официальной
публикацией. Массовый экспорт через Overlay запрещён.
