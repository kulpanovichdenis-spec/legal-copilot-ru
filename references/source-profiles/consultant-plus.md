---
id: consultant-plus
kind: commercial_provider
jurisdictions: [RU]
capabilities: [legislation, court_practice, commentary, navigation]
access: mcp
authority_level: professional_primary
adapter: remote_legal_mcp
connection_ref: consultant-plus
protocol_refs:
  - references/consultant-plus-automation.md
  - references/source-hierarchy.md
fallbacks: [pravo-gov-ru, kad-arbitr, vsrf]
health_probe: tools/list
rate_limits: server_managed
auth: corporate_network_or_vpn_no_user_credentials
status: active
data_policy: abstracted_issue_only
verification_roles: [navigation, norm_verification, doctrine]
coverage:
  document_types: [legislation, court_practice, commentary]
  full_text: yes
  historical_versions: conditional
  current_status: conditional
  pinpoint: yes
  provenance: conditional
norm_verification:
  eligible: true
  mode: live_professional
  requires: [connected, document_opened, title_edition_visible, supplier_status_category_visible, official_status_crosscheck]
  verified_tools: [consultant_search, consultant_get_document, consultant_get_text]
  last_smoke_at: "2026-10-09"
  limitations: [search_card_is_navigation_only, edition_date_is_derived_from_title, exact_status_requires_official_crosscheck, historical_edition_selection_not_exposed, official_publication_and_court_record_checked_separately]
---

# КонсультантПлюс

К+ подключён к Legal Overlay как основной внешний профессиональный источник
для поиска законодательства, комментариев и судебной практики. Подключение не
использует пользовательские логин, пароль, токены или HTTP-заголовки: доступен
только из корпоративной сети или VPN.

Разрешены только read-only инструменты `consultant_search`,
`consultant_get_text`, `consultant_get_document` и `consultant_status`. Поиск
остаётся навигацией; перед правовым выводом раскрывают полный текст и карточку.
К+ участвует в `route_norm_verification` как `live_professional`, но не заменяет
официальную проверку опубликования, точного статуса и реквизитов судебного акта.

Live-smoke 2026-10-09 на production `consultantplus-mcp` 0.2.0 подтвердил
`consultant_status`, `consultant_search`, `consultant_get_document` и
`consultant_get_text`. Карточка честно помечает дату редакции как производную из
заголовка; контракт поставщика не предоставляет точный индивидуальный статус и
выбор исторической редакции. Поэтому эти возможности остаются `conditional` и
закрываются официальным источником, а не догадкой или вызовом ГАРАНТа.
