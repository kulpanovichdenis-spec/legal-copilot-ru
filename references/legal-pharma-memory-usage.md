# Локальный vault / second-brain слой

> **Статус (2026-09-24): контент локальный, отдельный MCP не возвращался.** Оба харнеса обращаются к единому `legal-overlay`. Opinions, reviewed Telegram и MOC читаются из immutable `legal-memory.sqlite`; НПА, обзоры и судебные позиции — из `legal-ru.sqlite`; единая доктрина — из `legal-doctrine.sqlite`. `server-legal-kb` отключён.

## Рабочие инструменты

| Задача | Инструмент единого Overlay |
|---|---|
| НПА / комментарии / позиции | `search_legal_kb`, `search_comments`, `search_positions` |
| Раскрыть карточку RU-корпуса | `get_document`, `get_legal_text`, `get_comment_position` |
| Доктрина | `search_doctrine` → `get_doctrine_unit`; источники — `list_doctrine_sources` |
| Связи | `get_document_relations`, `get_legal_graph_neighbors`, `list_position_norm_links` |
| Собственные заключения | `search_legal_opinions` → `get_legal_opinion` |
| Reviewed Telegram | `search_telegram_reviewed` → `get_telegram_reviewed` |
| Тематические карты | `list_topic_maps` → `get_topic_map` |
| Проверка snapshot | `overlay_status(probe=true)` и `sqlite_legal_memory_status` |

## Курируемые слои в `legal-memory.sqlite`

Snapshot открывается только как `mode=ro&immutable=1` после проверки manifest, SHA-256, schema, `quick_check` и foreign keys.

- **`opinions`** — `search_legal_opinions` / `get_legal_opinion`. Собственные заключения юриста используются для согласованности позиции, но не цитируются как источник права.
- **`telegram_reviewed`** — `search_telegram_reviewed` / `get_telegram_reviewed` с фильтрами `channel` / `topic` / `status`. Без явного `status` поиск возвращает только `keep_commentary` и `keep_guideline`; `needs_source_review` и `delete_candidate` не использовать как подтверждённую опору.
- **MOC** — `list_topic_maps` / `get_topic_map`. Это курируемая карта входа в тему, отличная от автоматических `list_relation_hubs`; правовой тезис подтверждать лежащим под картой источником.

## Таксономия статусов карточек

Каждый статус = слой источника + допустимость использования:

| Статус | Что это | Как использовать |
|---|---|---|
| `active` | НПА / текст источника | Только discovery/snapshot; для финала проверить норму через `route_norm_verification(..., probe=true)` и `usable_now: true` |
| `source_approach_reviewed` | комментарии, доктрина, обзоры практики, заключения | Источник **подхода/аргумента**, не НПА; актуальность редакции не проверяется |
| `keep_commentary` / `keep_guideline` | проверенный Telegram/commentary слой | Низкоавторитетный **комментарий/ориентир**, не НПА и не судебная практика |
| `needs_source_review` | очередь проверки (auto-extracted) | Только для ревизии очереди; при использовании — предупреждение «источник не подтверждён» |
| `raw_archive` | сырой Telegram-архив | Только архив; **не цитировать** в обычных ответах |

## Правила цитирования локальных источников (без изменений)

- **Норма** — по стандартным правилам `references/citation-rules.md`; факт «получена из базы» в тексте документа не упоминается.
- **Разъяснение/комментарий** — ссылка на первоисточник (письмо ведомства и т. п.); аналитика **не заменяет норму**.
- **Заключение (`opinions`)** — собственная позиция юриста, во внешних документах **не цитируется** как источник; используется для согласованности позиции.
- **Telegram** любого слоя — **не самостоятельное правовое основание** (максимум низкоавторитетный комментарий).

## Связанные файлы

- `references/legal-kb-usage.md` — локальный структурированный корпус
- `references/source-hierarchy.md` — иерархия источников, Приоритет 0a
- `references/source-profiles/local-legal-memory-sqlite.md` — профиль provider
- `references/citation-rules.md` — правила цитирования
