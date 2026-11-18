---
id: fas
kind: specialized_provider
jurisdictions: [RU]
capabilities: [administrative_practice, advertising, case_details, filter_options]
access: api
authority_level: derived_official_corpus
adapter: fas_search
connection_ref: fas
protocol_refs:
  - references/fas-search-mcp-setup.md
  - references/fas-ad-practice-methodology.md
fallbacks: [fas-public-web]
health_probe: get_filter_options
rate_limits: 20_per_minute_300_per_day_per_outbound_ip
auth: null
status: active
data_policy: public_only
verification_roles: [navigation, case_law_verification]
coverage:
  document_types: [administrative_practice, advertising_cases]
  full_text: conditional
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
  limitations: [administrative_practice_only, legislation_requires_separate_verification]
---

# ФАС России

Локальный adapter обращается к внешнему MCP через стабильные плоские инструменты
Overlay. Серверный `fas_search_proxy` отключён; если direct provider не отвечает,
gateway возвращает контролируемую ошибку, после чего применяется ручной web-fallback.

Прямой provider работает по Streamable HTTP без авторизации. Поиск и фильтры
выполняются на стороне provider; `limit` ограничен 15. Codex и Claude не должны
подключать FAS отдельным MCP рядом с Overlay, иначе возникнет дублирование tools.

База является производным поисковым корпусом официальных решений. Результат
поиска не получает уровень официального первоисточника: ключевую карточку,
реквизиты и ссылку необходимо сверять с публикацией ФАС.
