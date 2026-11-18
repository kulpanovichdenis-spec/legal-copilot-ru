---
id: garant
kind: commercial_provider
jurisdictions: [RU]
capabilities: [legislation, court_practice, document_export, legal_news]
access: mcp
authority_level: professional_primary
adapter: remote_legal_mcp
connection_ref: garant
protocol_refs:
  - references/external-legal-databases.md
  - references/source-hierarchy.md
fallbacks: [local-legal-ru-sqlite, pravo-gov-ru, kad-arbitr]
health_probe: tools/list
rate_limits: monthly_quotas_see_garant_limits
auth: bearer_api_token
status: disabled
data_policy: abstracted_issue_only
verification_roles: [navigation]
coverage:
  document_types: [legislation, court_practice, legal_news]
  full_text: yes
  historical_versions: yes
  current_status: yes
  pinpoint: yes
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: [connected, authenticated, exact_document_topic_resolved, edition_topic_checked_via_redactions, current_status_checked_via_document_info, block_opened_via_export_block_html]
  verified_tools: []
  last_smoke_at: null
  limitations: [disabled_by_current_configuration, do_not_make_network_calls, historical_smoke_is_not_current_availability]
---

# ГАРАНТ

**Отключён. Не использовать для поиска, проверки нормы или судебной практики.**
Исторический профиль и параметры прошлого smoke сохранены только для возможного
будущего повторного подключения. Токен, если он сохранён, лежит только в gitignored
`profile/settings/secrets.env` (`GARANT_API_TOKEN`). **Единственный маршрут — через Overlay**
(`legal-overlay`, `garant_*`): прямой MCP `garant` в настройках Claude удалён, чтобы квота
экспорта не расходовалась мимо Overlay.

Поисковая карточка и snippet остаются навигацией. Основанием проверки нормы
служит раскрытый блок документа (`garant_export_block_html`) на нужной редакции
и со статусом из `garant_document_info` / `garant_document_redactions`.
Официальная публикация (Собрание законодательства, pravo.gov.ru) остаётся
усиленным маршрутом и нужна для реквизитов опубликования: ГАРАНТ их не возвращает.

## Что подтверждено смоуком

| Этап | Инструмент | Результат |
|---|---|---|
| Поиск акта | `garant_search` (`env=internet`) | ГК РФ найден как `topic` 10164072 |
| Статус | `garant_document_info` | «Действующие», активная редакция 10.06.2026–31.12.2026 |
| Редакции | `garant_document_redactions` | список редакций с датами и статусами `rs_Actual` / `rs_Old` / `rs_New` |
| Pinpoint | `garant_snippets(text="Статья 333")` | `entry` статьи и цепочка `ancestors` |
| Текст | `garant_export_block_html` | HTML статьи; на `topic` старой редакции возвращает старую |
| Практика | `garant_sutyazhnik` (`kind`: 301/302/303), `garant_search(env=arbitr)` | акты с датами до 5 дней давности, ссылки на абзац |
| Квоты | `garant_limits` | счётчики по семействам методов |

## Правила работы

- Порядок для нормы: `garant_search` → `topic` → `garant_document_info` (статус) → `garant_document_redactions` (редакция на дату) → `garant_snippets` (entry) → `garant_export_block_html` (текст). Один блок = один экспорт.
- `entry` статьи с точкой склеивается: 381.1 → 38011; части статьи имеют свои блоки (ст. 333: 33301, 33302, 3332). Номер блока брать из `garant_snippets` / ответа экспорта, не вычислять.
- Описания инструментов ссылаются на `garant_entry_text`, но на сервере его нет (18 инструментов). Текст статьи — только через HTML-экспорт, поэтому лимит экспорта расходуется на каждую проверку: без нужды не открывать статьи «на всякий случай», не использовать `garant_export_html` (весь документ), `garant_export_pdf/odt/rtf/image/formula` без прямой просьбы юриста.
- Практика: `garant_sutyazhnik(text=<фрагмент нормы>, kind=["302"], count=…)` даёт акты, применявшие норму; для поиска по фактам и темам — `garant_search(env="arbitr", sort=1)`. Реквизиты акта выводятся юристу после раскрытия карточки; карточка поиска — лид.
- Перед серией экспортов вызвать `garant_limits`. Поиск, snippets и редакции счётчиками не показаны; карточка документа расходует лимит 300/месяц.
- Кириллицу передавать через MCP-клиент, не через аргументы Git Bash: оболочка искажает запрос, поиск возвращает 0.
- Не смешивать: ГАРАНТ — только РФ. Конфиденциальные факты перед запросом абстрагируются (`data_policy: abstracted_issue_only`).

## Не проверялось

`garant_find_hyperlinks`, `garant_find_modified`, `garant_block_changed`,
`garant_prime_news`, `garant_export_html/pdf/odt/rtf/image/formula`, предел
20 запросов в секунду. До проверки в `verified_tools` не входят.
