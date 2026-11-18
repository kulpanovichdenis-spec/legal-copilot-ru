---
id: sudact
kind: specialized_provider
jurisdictions: [RU]
capabilities: [court_practice_search, court_documents, public_full_text]
access: browser
authority_level: secondary_public_aggregator
adapter: null
connection_ref: null
protocol_refs:
  - references/web-research-tools.md
  - references/court-decision-analysis.md
fallbacks: [kad-arbitr, vsrf, sudrf]
health_probe: null
rate_limits: portal_dependent
auth: null
status: manual_only
data_policy: public_only
verification_roles: [navigation, web_discovery, case_law_verification]
coverage:
  document_types: [published_court_decisions]
  full_text: conditional
  historical_versions: no
  current_status: conditional
  pinpoint: yes
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [court_practice_only, public_aggregator_not_official_portal, procedural_history_may_be_incomplete, verify_case_status_in_official_card_when_available]
---

# СудАкт

Бесплатный публичный агрегатор судебных актов. Использовать как резервный поиск
и для раскрытия опубликованного полного текста, когда платная база отсутствует
или официальный портал временно неудобен. Сам сайт сообщает, что получает акты
с официальных сайтов судов и не редактирует их, однако он не является
официальным первоисточником.

Допустимо предварительно подтвердить существование акта, его реквизиты и текст
по открытой странице СудАкта. Прохождение по инстанциям, отмену/изменение и
актуальный статус дела по возможности сверять по КАД, сайту ВС РФ или порталу
соответствующего суда. Если официальный источник недоступен, разрешено сослаться
на СудАкт с явной пометкой `secondary_public_aggregator` и указанием, что
процессуальный статус независимо не проверен.
