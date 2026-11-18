---
id: tavily
kind: specialized_provider
jurisdictions: [GLOBAL]
capabilities: [web_search, web_extract, deep_research]
access: api
authority_level: discovery_only
adapter: tavily
connection_ref: tavily
protocol_refs:
  - references/web-research-tools.md
  - references/trademark-search-automation.md
fallbacks: [browser-web-research]
health_probe: null
rate_limits: account_plan_dependent
auth: api_key_from_local_secret_store
status: active
data_policy: public_only
verification_roles: [navigation, web_discovery]
coverage:
  document_types: [public_web_pages, search_results, extracted_pages]
  full_text: conditional
  historical_versions: no
  current_status: unknown
  pinpoint: conditional
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [web_discovery_only, extracted_page_is_not_automatically_authoritative]
---

# Tavily

Локальный adapter обращается прямо к `https://api.tavily.com` и предоставляет
`tavily_search`, `tavily_extract`, асинхронную пару `tavily_research` →
`tavily_get_research`. Серверный `legal-kb` в этом маршруте не участвует.

Передавать можно только публичные или обезличенные запросы и публичные URL.
Результаты Tavily являются поисковыми лидами, а не официальным источником права.
Пустой health-probe не выполняется, поскольку API-вызовы расходуют кредиты.
