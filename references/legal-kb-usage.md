# legal-kb — гайд по использованию

Structured runtime layer правовой базы (фарма-домен + общегражданская практика ВС РФ). Текущая маршрутизация:

- **Local SQLite — единственный corpus runtime внутри Overlay.** `local-legal-ru-sqlite`, `local-legal-uz-sqlite`, `local-legal-doctrine-sqlite` и `local-legal-memory-sqlite` читают проверенный snapshot только через `mode=ro&immutable=1`. Образцы и клаузы читаются из `profile/knowledge/` через Glob+Read, не из snapshot.
- **Серверный VPS выведен.** Провайдер `server-legal-kb` удалён из Overlay; корпус работает только локально.

Оба харнесса подключаются только к локальному Overlay под namespace `legal-overlay`; отдельная SQLite-конфигурация в Codex/Claude не создаётся. Машинный путь находится в `profile/settings/local.env`.

**Режим заморозки:** Docker / PostgreSQL / Hermes / серверный мониторинг на VPS **не трогать** без явной просьбы юриста. Штатное чтение выполняется локально.

## Слои данных

| Слой | Что внутри |
|---|---|
| **Норм-документы** (`norm`, `code`, `federal_law`, `government_decree`, `order`, `eaeu_decision`) | НПА, импортированные из `vault/norms` |
| **Комментарии и обзоры практики RU-корпуса** | материалы, не перенесённые в единый doctrine provider; legacy-доктрина исключена по префиксу `canonical_key` |
| **Единая доктрина** (`article_commentary_unit`, `legal_position`, `legal_literature_note`) | `legal-doctrine.sqlite`; произведения, страницы, offsets и provenance, только `doctrine_only` |
| **Судебные/правовые позиции** (`court_position`) | извлечённые позиции из обзоров практики ВС РФ |
| **Position enrichment JSON** | `backend/data/comment_position_enrichment.json` — обогащённые поля позиций |
| **Position→norm links JSON** | `backend/data/comment_position_norm_links.json` — связи позиция→норма |

JSON-слои — это **локальные machine-readable индексы**, а не источник истины по оригинальному тексту. Первоисточник текста — норм-документ/обзор через `get_legal_text`.

## Архитектура

`legal-overlay` — namespace единого локального gateway. Structured corpus находится в `legal-ru.sqlite`; UZ — в `legal-uz.sqlite`; доктрина — в `legal-doctrine.sqlite`; opinions, reviewed Telegram и MOC — в `legal-memory.sqlite`. Образцы и клаузы читаются из `profile/knowledge/`. Canonical-key official bridge локальный. Отдельного MCP `legal-pharma-memory` нет.

## Инструменты (`mcp__legal-overlay__*`)

### Судебные/правовые позиции — основной слой для практики

| Инструмент | Что делает |
|---|---|
| `search_positions(query, topic, keyword, article, law, case_number, link_status, limit)` | **Первый инструмент** по вопросам практики/позиций ВС РФ. Фильтры комбинируются. Возвращает `unit_id`, `case_number`, `decision_date_text`, `topic`, `unit_heading`, `key_thesis`, `links_summary` |
| `get_comment_position(unit_id)` | Одна обогащённая позиция по `unit_id` |
| `list_comment_positions(...)` | Перечень позиций |
| `list_position_norm_links(unit_id, status="all")` | Точные связи позиции с норм-документами. **Вызывать до утверждения, что позиция связана с конкретной локальной нормой** |

**Правильный порядок вызовов для поиска позиций:**

```
# 1. По номеру дела
search_positions(case_number="308-ЭС22-2960", limit=10)

# 2. По статье закона
search_positions(article="ст. 384 ГК РФ", limit=10)

# 3. По теме (тематический поиск)
search_positions(query="банкротство", limit=10)

# 4. Получить позицию по unit_id
get_comment_position(unit_id="...")

# 5. Проверить связи с нормами
list_position_norm_links(unit_id="...", status="all")

# 6. Отдельный поиск доктрины
search_doctrine(query="аренда", limit=10)
```

**Стабильные topic-ключи для `search_positions(topic=...)`:**

| Ключ | Тематика |
|---|---|
| `real_estate` | Недвижимость, аренда, регистрация |
| `contracts_obligations` | Договорное право, обязательства |
| `bankruptcy` | Банкротство, несостоятельность |
| `corporate` | Корпоративное право, ООО/АО |
| `ip` | Интеллектуальная собственность |

Пример: `search_positions(topic="real_estate", limit=10)`

**Правило расширения поиска.** Если узкий запрос по практике ничего не дал — не останавливаться. Расширять последовательно:
1. Убрать точный `article` → оставить только `query`
2. Добавить `topic` из стабильных ключей
3. Попробовать `keyword` (отдельное ключевое слово, не полная фраза)
4. Искать по `case_number`, если номер дела известен
Только после исчерпания всех вариантов в `search_positions` — переходить к `search_comments` для обзоров практики. Доктринальный слой ищется отдельно через `search_doctrine`.

### Поиск по НПА и текстам

| Инструмент | Что делает |
|---|---|
| `search_legal_kb(query, limit)` | Полнотекстовый поиск по RU/EAEU-индексу: НПА, обзоры и практика без legacy-копий единой доктрины. Возвращает `document_id`, `title`, `act_number`, `snippet` |
| `find_by_act_number(act_number)` | Точный поиск по реквизиту ("61-ФЗ") |
| `get_document(document_id)` | Метаданные документа: статус, источник, даты |
| `get_document_outline(document_id)` | Структура (главы, статьи) без полного текста |
| `get_legal_text(document_id, article)` | **Snapshot-текст** документа или статьи из локальной SQLite. Если нужна статья, передавать `article="24"` / `article="24.1"`. Это не live-подтверждение действующей редакции; учитывать snapshot freshness |
| `pravo_resolve_act(act_number, act_date)` → `pravo_get_document(nd)` | Локальный direct adapter к `pravo.gov.ru`: точное разрешение акта и bounded official text с URL/hash/provenance |
| `get_official_document` / `get_official_article` | Совместимые aliases direct pravo-provider; использовать как verification только если `route_norm_verification(..., probe=true)` вернул этот provider с `usable_now: true` |
| `check_norm_reference(reference_text)` | Разбор ссылки на норму и проверка через реестр федеральных актов; предупреждения вместо догадок |
| `get_comment(...)` | Текст/метаданные комментария-документа |
| `search_comments(query, limit)` | Совместимый поиск по оставшимся RU-комментариям и обзорам практики без legacy-копий единой доктрины |
| `search_all_legal_memory(query, limit)` | Совместимый широкий поиск только по RU-корпусу; единую доктрину не заменяет |

### Единая доктрина

| Инструмент | Что делает |
|---|---|
| `search_doctrine(query, source_family, unit_type, article, limit)` | Канонический полнотекстовый поиск доктрины; возвращает snippet, произведение, тип unit, статью, страницы/offsets, связанные нормы/дела и provenance |
| `get_doctrine_unit(unit_id, offset, limit)` | Постраничное чтение текста unit; длинные фрагменты не возвращаются целиком автоматически |
| `list_doctrine_sources(source_family, source_category, limit)` | Перечень source works и метаданных источников |
| `sqlite_legal_doctrine_status()` | SHA-256, read-only access, freshness и контроль количества sources/units/FTS rows |

Каждый результат имеет `authority_class = doctrine_only`. Упомянутые нормы и судебные акты раскрываются и проверяются отдельно; doctrine provider не является маршрутом `norm_verification`.

### Связи между документами

| Инструмент | Что делает |
|---|---|
| `get_document_relations(document_id, direction="both", limit)` | Входящие/исходящие связи норм-документа |
| `list_relation_hubs(limit)` | Узловые акты по входящим связям — каркас широкой темы |

**Номера актов.** Если запрос содержит реквизит акта (`61-ФЗ`, `127-ФЗ`, `N 462`, `№ 686`) — сначала использовать `find_by_act_number`. `search_legal_kb` допустим как fallback, когда нужен поиск по теме или смешанный запрос вида "61-ФЗ лекарственные средства". Не использовать широкий поиск только ради точного номера.

**Постатейный текст.** Если вопрос про конкретную статью (`ст. 24 ФЗ о рекламе`, `ч. 7 ст. 24`, `ст. 333 ГК РФ`) — после нахождения документа использовать `get_legal_text(document_id, article="24")`, а не полный `get_legal_text(document_id)`. Полный текст большого акта тянуть только если юрист явно просит весь документ или нужна проверка широкого контекста.

**Проверка текста и дословной цитаты нормы.** Сначала вызвать `route_norm_verification(jurisdiction=..., probe=true)`, затем использовать только маршрут `usable_now: true`. Если выбран direct pravo-provider, допустимы `get_official_article` / `get_official_document` либо native `pravo_*`; профессиональная база допустима в подтверждённом профилем объёме. Индексный `get_legal_text`, карточка и snippet остаются discovery. Проверить редакцию, статус, pinpoint и provenance; нет маршрута — `[ПРОВЕРИТЬ НОРМУ]`.

**Два слоя связей.** `position_norm_links` в JSON — основной граф "позиция → норма" для судебных/правовых позиций. `document_relations` в SQLite — отдельный runtime-граф "документ → документ" для НПА/подзаконки/верхнеуровневых комментариев. Если health показывает `document_relations = 0`, не обещать пользователю граф документных связей; использовать `position_norm_links` для позиций и прямо отмечать, если документная связь не построена.

### Состояние и обслуживание базы

| Инструмент | Что делает |
|---|---|
| `overlay_status(probe=true)` | Проверить все активные providers и увидеть отключённый server profile |
| `sqlite_legal_ru_status()` / `sqlite_legal_memory_status()` | Проверить hash, freshness, integrity и счётчики конкретной базы |
| `doctor()` / `kb_health_report()` / `get_storage_report()` | Read-only compatibility diagnostics для RU snapshot |

Обновление данных выполняется вне `legal-copilot`: генератор выпускает новый immutable snapshot, после чего здесь вручную переключается `LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR` и повторяется smoke обоих харнесов.

### Read-only / mutating

- **Read-only:** `search_positions`, `get_comment_position`, `list_comment_positions`, `list_position_norm_links`, `search_legal_kb`, `find_by_act_number`, `get_document`, `get_document_outline`, `get_legal_text`, `search_doctrine`, `get_doctrine_unit`, `list_doctrine_sources`, `get_official_document`, `get_official_article`, `check_norm_reference`, `find_federal_act`, `get_comment`, `search_comments`, `search_all_legal_memory`, `get_document_relations`, `list_relation_hubs`, `kb_health_report`, `get_storage_report`, `get_kb_status`.
- **Mutating tools не экспонируются.** Любая пересборка выполняется в исходном проекте базы и публикуется как новый snapshot.

## Маршрутизация по юрисдикции и узбекский корпус

`legal-kb` обслуживает **два корпуса**: РФ/ЕАЭС (основной) и **Узбекистан** (`uzbek-legal-memory`, отдельный проект).

**Маршрутизация по `route` (из `route_legal_query(query)` — вызывать, если юрисдикция не очевидна):**
- `russia_eaeu` / `default_main_corpus` → `search_legal_kb`;
- `uzbekistan` → `search_uzbek_legal_memory`; если router вернул `collections` — передать подходящую в параметр `collection`: `advertising`, `medicines`, `registration`, `liability`, `permits`;
- `needs_clarification` → **базы не смешивать**, уточнить юрисдикцию (исключение — юрист явно просит сравнение РФ vs Узбекистан).

**Узбекистан** (только для узбекских вопросов; вопрос не про Узбекистан → корпус не трогать): `search_uzbek_legal_memory(query, collection, include_not_verified=false, limit)`, `get_uzbek_legal_card(path, max_chars)`, `uzbek_legal_status()`.
- `not_verified` карточки **не использовать как право**; `include_not_verified` держать `false`.
- `verification_pending` — только **указатель на необходимость проверки** (`[ПРОВЕРИТЬ ИСТОЧНИК]`), не подтверждённая норма.
- **Санкции за рекламу в Узбекистане:** ст. 47 Закона о рекламе (Law on Advertising, art. 47 units) + ст. **178¹ КоАО**. **Ст. 189 — только порнографическая продукция**, не общая рекламная ответственность.
- **После поиска — раскрыть карточку** (`get_uzbek_legal_card` / `get_document` / `get_legal_text`), если нужен точный ответ.
- Узбекское право не смешивать с РФ/ЕАЭС.
- *(План разработчика базы: collections уже передаются в поиск; router 2-го уровня доводит выбор collection до автоматизма.)*

## Правила выбора инструмента

- **Вопрос про практику / позиции ВС РФ / по статье кодекса / по номеру дела / по теме / по ключевому слову** → `search_positions` **первым**. `search_positions` — для **уже выделенных** правовых/судебных позиций.
- **Доктрина / постатейные комментарии / доктринальные позиции и литература** → **`search_doctrine` первым**, затем `get_doctrine_unit`; при необходимости отдельно `search_positions` по судебной практике.
- **Обзоры практики и оставшиеся RU-комментарии** → `search_comments`; `search_all_legal_memory` остаётся compatibility alias только для RU-корпуса.
- **Не смешивать слои в выводе:** doctrine/comment-карточка — доктринальный подход (по доктринальному комментарию, именная доктринальная позиция), не НПА и не судебная практика; `court_position` — практика; НПА — норма. Каждый слой маркируется своим весом (см. «Иерархия уверенности» в `references/source-hierarchy.md`).
- Если `search_comments` возвращает `search_preview`, использовать его как навигационное резюме карточки. Не цитировать `search_preview` как правовой источник; для вывода по существу раскрывать карточку/текст через `get_comment`, `get_legal_text` или дочерние карточки.
- Legacy-контейнеры и `article_commentary_unit` с `canonical_key LIKE 'legacy-wiki:doctrine_commentary--%'` не должны появляться в пользовательской RU-выдаче. Если появились — это дефект дедупликации.
- `get_doctrine_unit` поддерживает `offset`/`limit`; продолжать чтение по `has_more`, не повышать лимит без необходимости.
- `kb_health_report.commentary_segments.status = NEEDS_REVIEW` не означает, что база сломана. Это очередь доразметки больших комментариев: `missing_offsets` закрывать как дефект, `oversized_segments` читать через `max_chars` и дробить только если реальные запросы показывают, что сегмент слишком тяжелый. Для обычной работы агента ориентироваться на общий `health-report.status`, `full_text.missing_count` и `warnings`.
- Для выпусков обзоров практики `list_comment_positions(document_id=<id выпуска>)` должен возвращать дочерние позиции (`court_practice_item`) этого выпуска. В ответе использовать `position_document_title` как карточку определения, а `source_document_title/source_document_id` как источник обзора для навигации и цитирования.
- **Поиск самого НПА** → `search_legal_kb` / `find_by_act_number`.
- **Перед утверждением, что позиция связана с конкретной локальной нормой** → `list_position_norm_links(unit_id)`.
- **Полный оригинальный текст** → `get_legal_text`, только когда он реально нужен.

## Стандартный workflow

**Практика/позиция:**
```
1. search_positions(topic|article|keyword|case_number)   ← найти позиции
2. get_comment_position(unit_id)                          ← обогащённая позиция (при необходимости)
3. list_position_norm_links(unit_id)                      ← точные связи с нормами (до заявления о связи)
4. get_legal_text(document_id, article="...")             ← конкретная статья, если известна
5. get_legal_text(document_id)                            ← полный оригинал только если нужен весь текст
```
**НПА:**
```
1. search_legal_kb(query) / find_by_act_number           ← найти НПА (+ узнать canonical_key)
2. get_legal_text(document_id, article="...")             ← индексный текст статьи
   └─ если вернулся только ЗАГОЛОВОК статьи → перейти к шагу 3, НЕ в веб
3. route_norm_verification(jurisdiction=..., probe=true)  ← выбрать usable_now provider
   provider-specific full text/article tool               ← проверить редакцию, статус, pinpoint, provenance
4. get_document_relations(document_id,"both")             ← связи / подзаконка / разъяснения
5. search_comments(query)                              ← добрать обзоры/оставшиеся RU-комментарии
6. search_doctrine(query) → get_doctrine_unit(...)     ← доктрина отдельным каноническим слоем
```
> Дословная цитата нормы в документе юристу — из шага 3 (официальный текст с провенансом), а не из веб-поиска. Веб (`references/web-research-tools.md`) — fallback только если шаги 1–3 не дали акт.

## Политика unresolved-связей

`unresolved` означает **только одно**: позиция ссылается на статью закона/кодекса, но целевой норм-документ сейчас отсутствует/не разрешается в локальной legal-kb.

- **Не** трактовать unresolved как задачу добавить недостающие НПА.
- **Не** формировать список НПА «к приобретению», пока юрист явно не попросит.
- В анализе unresolved-связь можно использовать как **текстовое доказательство**, но прямо указать, что целевая норма **не привязана к локальному документу**.
- Если `list_position_norm_links` возвращает `reason = "known external law not stored in local KB"` и `target_title` заполнен, это известный внешний закон (например `127-ФЗ`, `40-ФЗ`, `416-ФЗ`), но его текста нет в local-lite. Упоминать как ссылку из позиции, не как локально подтвержденный текст НПА.

## Правила ответа из слоя позиций

- Предпочитать `search_positions` широкому текстовому поиску.
- Цитировать позицию по `case_number`, `decision_date_text`, `unit_heading`; при пользе — `topic` и `key_thesis`.
- Упоминать связанные локальные нормы **только если `links_summary.resolved > 0`**.
- Если связь `unresolved` — **не** подразумевать, что локальная база содержит эту норму.
- Для высокой уверенности — `list_position_norm_links(unit_id)` до утверждения о связи с конкретным локальным норм-документом.
- Позиции ВС РФ — это практика; цитировать по `references/citation-rules.md`, при необходимости сверять первоисточник.
- Пленумы ВС/ВАС, Президиумы ВС/ВАС, информационные письма и обзоры судебной практики в `legal-kb` классифицируются как `court_practice`, даже если в названии есть "постановление" или номер. Не трактовать их как НПА; использовать как судебную практику/разъяснения.

## Обслуживание после новых материалов

`legal-copilot` snapshot не пересобирает и не изменяет. После получения нового каталога snapshot: (1) проверить migration reports; (2) переключить один путь в `profile/settings/local.env`; (3) вызвать `overlay_status(probe=true)` и три status-инструмента (`sqlite_legal_ru_status`, `uzbek_legal_status`, `sqlite_legal_memory_status`); (4) выполнить выборочные searches; (5) повторить smoke Codex и Claude.

**Raw-слои.** `inbox/` — входящие материалы, которые юрист только добавил и которые еще могут быть не обработаны. `source-files/` — архив использованных исходников после обработки. Не удалять оба слоя без отдельного решения юриста; дубли между ними допустимы до отдельной чистки архива.

## Если база/MCP ведёт себя странно

**Первым делом — `overlay_status(probe=true)`.** Затем вызвать status tool конкретного SQLite provider. `doctor()` оставлен как read-only compatibility alias для RU snapshot; он ничего не чинит и не пересобирает.

## MOC — карта входа, не правовое основание

MOC входят в `legal-memory.sqlite`. **MOC использовать только как карту входа** в тему, **не как правовое основание**. Их обновляет внешний генератор следующего snapshot.

## Deferred-проверки (не чинить без просьбы)

Если карточка snapshot содержит deferred/review статусы, они **не являются задачей к исправлению** внутри `legal-copilot`. Не предлагать менять immutable SQLite по своей инициативе.

## Что НЕ делать

- **Не** трогать server/VPS/Docker/PostgreSQL/Hermes/мониторинг без явной просьбы.
- **Не** трактовать unresolved-связи как список НПА к добавлению.
- **Не** чинить deferred-проверки (`missing_effective_date`, `missing_source_monitor`) по своей инициативе.
- **Не** цитировать как официальный источник права telegram-позиции / opinions / неформальные комментарии — это навигация и контекст (позиции ВС РФ из обзоров — это практика, цитируются как практика).
- **Не** читать массово vault вручную, если решается через `legal-overlay`.
- **Не** вызывать mutating-операции (`compact_db`, `enrich_*`, `build_*`, `run_quality_audit`) «на всякий случай» — только при реальном поводе.
- **Не** удалять/модифицировать `source-files/`, `inbox/`, `vault/norms/`, `vault/_texts/`, заметки, комментарии.

## Маркеры в ответах

Общий реестр маркеров — `references/citation-rules.md`, «Реестр маркеров неполноты». Ниже — маркеры, специфичные для работы с `legal-kb`:

- `get_legal_text` вернул `[INDEXED_STORAGE]` → vault-текст не найден/сломалась раскрутка: сообщить юристу, проверить `get_storage_report()`.
- Документ `needs_review` / открытые actionable-проверки → «источник проходит верификацию». Применимо к **НПА**.
- `last_checked` старше 6 мес. → `[ПРОВЕРИТЬ АКТУАЛЬНОСТЬ РЕДАКЦИИ]` + `route_norm_verification(jurisdiction=..., probe=true)` и раскрытие текста через `usable_now: true`. Применимо к **НПА**.
- **Комментарии, доктрина, обзоры практики, Telegram-позиции проверки «актуальности источника» не требуют** — это источник подхода/аргументации, не действующей редакции нормы; маркеры актуальности редакции и `check_currency` к ним не применяются. Юрист проверяет первоисточник и практику по факту задачи.

## Связанные файлы

- `references/source-hierarchy.md` — Приоритет 0a (объединённый слой)
- `references/legal-pharma-memory-usage.md` — локальный vault/second-brain слой в `legal-memory.sqlite`
- `references/web-research-tools.md` — capability-маршрут и прямой provider pravo.gov.ru (раздел 3.2)
- `references/citation-rules.md` — правила цитирования
- `CLAUDE.md` — рабочее правило, обслуживание, deferred-проверки
