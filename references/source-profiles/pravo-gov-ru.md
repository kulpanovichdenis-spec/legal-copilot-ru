---
id: pravo-gov-ru
kind: official_portal
jurisdictions: [RU]
capabilities: [legislation, exact_act_resolution, official_full_text]
access: api
authority_level: official_primary
adapter: pravo_gov_ru
connection_ref: pravo-gov-ru
protocol_refs:
  - references/pravo-gov-ru-search-protocol.md
  - references/web-research-tools.md
  - references/source-hierarchy.md
fallbacks: [consultant-plus]
health_probe: portal_root_expected_redirect
rate_limits: low_frequency_interactive
auth: null
status: active
data_policy: public_only
verification_roles: [navigation, norm_verification]
coverage:
  document_types: [russian_federal_legislation]
  full_text: yes
  historical_versions: conditional
  current_status: conditional
  pinpoint: yes
  provenance: yes
norm_verification:
  eligible: true
  mode: live_official
  requires: [connected, exact_identity_resolved, full_text_opened, target_date_checked, document_status_checked]
  verified_tools: [pravo_resolve_act, pravo_get_document, pravo_get_article]
  last_smoke_at: "2026-09-15"
  limitations: [federal_ru_scope, historical_edition_must_be_confirmed_in_document, ambiguous_resolution_is_never_auto_selected]
---

# pravo.gov.ru

Локальный read-only adapter предназначен для точного разрешения федерального акта
по номеру и дате и получения текста с provenance. При нескольких кандидатах он
возвращает неоднозначность, а не выбирает первый результат. Массовый сбор данных
не входит в назначение adapter.
