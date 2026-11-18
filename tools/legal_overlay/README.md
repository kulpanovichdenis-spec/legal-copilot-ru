# Local Legal Overlay gateway

Локальная MCP-точка для Codex, Claude Desktop и будущих harness. Основные корпуса
RU/EAEU, UZ, единая доктрина и legal memory подключаются как локальные immutable
SQLite providers. Серверный legal-kb выведен и удалён; внешние источники работают
через отдельные локальные adapters.

## Запуск

```powershell
python -m tools.legal_overlay
```

Проектные `.mcp.json` и `.codex/config.toml` запускают именно этот gateway. Для
глобального Claude Desktop предусмотрен отдельный безопасный preview ниже.

## Настройки

Основной файл — `profile/settings/connections.yaml` (gitignored). Значения
секретов в него не записываются: только имена переменных в `secret_refs`.
Машинный путь к snapshot задаётся один раз в `profile/settings/local.env` как
`LEGAL_COPILOT_SQLITE_SNAPSHOT_DIR`; Codex и Claude получают его через общий
gateway, а не через отдельные harness-конфиги.

Порядок разрешения значений:

1. переменные процесса;
2. `profile/settings/secrets.env`;
3. `profile/settings/local.env`;
4. корневой `.env` как временная legacy-совместимость.

Gateway не возвращает значения секретов через диагностические инструменты;
известные секреты вычищаются из ошибок.

## Инструменты

- `overlay_status` — состояние providers, опционально read-only probe;
- `list_legal_sources` / `get_source_profile` — возможности и локальные правила;
- `route_norm_verification(jurisdiction, probe=true)` — список кандидатов и
  единственный текущий маршрут, который одновременно подтверждён профилем и
  живым probe; snapshot/search card/snippet никогда не получают `usable_now`;
- `legal_search` — provider-neutral запрос и единый `EvidenceBundle`; автоматический
  официальный fallback требует точные `act_number` + `act_date`, а
  `official_verification=true` запрашивает оба работающих provider; для
  непубличного запроса используются локальные SQLite/verified/curated providers
  без обращения к remote providers;
- `search_legal_kb`, `find_by_act_number`, `get_document`, `get_legal_text`,
  `search_positions`, `search_comments` и graph tools теперь первично обслуживает
  `local-legal-ru-sqlite`;
- `search_doctrine` / `get_doctrine_unit` / `list_doctrine_sources` обслуживает
  отдельный `local-legal-doctrine-sqlite`; выдача всегда маркируется
  `doctrine_only`, чтение длинных units постраничное, а нормы и судебные акты из
  доктрины требуют отдельной проверки;
- `search_uzbek_legal_memory` / `get_uzbek_legal_card` обслуживает отдельный
  `local-legal-uz-sqlite` с сохранением `verification_status`;
- образцы и клаузы читаются из `profile/knowledge/` через Glob+Read
  (`references/legal-document-samples-usage.md`, `skills/clause-library/SKILL.md`).
  Адаптер `sqlite_document_samples` и его инструменты сняты 2026-09-22 (BL-037);
- `search_legal_opinions` / `get_legal_opinion`, `search_telegram_reviewed` /
  `get_telegram_reviewed`, `list_topic_maps` / `get_topic_map` обслуживает
  `local-legal-memory-sqlite`; Telegram по умолчанию исключает
  `needs_source_review` и `delete_candidate`, MOC остаются navigation-only;
- `search_official_labor_guidance` / `get_official_labor_guidance` читает слой
  `labor_official` из того же `legal-memory.sqlite`, возвращает полный текст,
  официальный URL и provenance и маркирует материал как официальное
  ненормативное разъяснение; применимая норма проверяется отдельно;
- `pravo_resolve_act` / `pravo_get_document` — независимый read-only доступ к
  legacy-ИПС `pravo.gov.ru` с CP1251, проверкой URL, provenance и пагинацией;
- `get_official_document` / `get_official_article` — локальный canonical-key bridge:
  identity берётся из `legal-ru.sqlite`, live-текст — напрямую с `pravo.gov.ru`,
  без обращения к серверному `legal-kb`;
- `tavily_search` / `tavily_extract` / `tavily_research` / `tavily_get_research` —
  прямой локальный Tavily adapter; research работает асинхронно, а health не
  расходует credits;
- `dadata_party` — прямой локальный вызов DaData `findById/party`, принимающий
  только ИНН/ОГРН/ОГРНИП; произвольный текст и данные дела блокируются до сети;
- `search_local_curated` / `get_local_curated` — поиск и постраничное чтение
  канонических локальных playbook/cards по фиксированному allowlist, с SHA-256;
  эти материалы имеют уровень `internal_methodology` и не являются источниками права;
- `search_verified_knowledge` / `get_verified_knowledge` — только объекты из
  `profile/knowledge/verified/`; candidates и superseded в эту выдачу не попадают;
- `propose_knowledge_candidate` — создаёт только machine-кандидата;
  `verify_knowledge_candidate` и `supersede_verified_knowledge` работают в режиме
  preview по умолчанию, сверяют SHA-256 и требуют два явных флага для применения;
- `search_fas_ad_practice` / `get_fas_case` / `list_fas_filter_options` — стабильный
  flat contract для практики ФАС; gateway вызывает прямой provider, серверный
  fallback отключён, при недоступности применяется ручной web-fallback;
- Glossa, единый и четыре legacy Casus connectors, ПравоТех и ГАРАНТ зарегистрированы через единый
  `remote_legal_mcp` adapter. В стартовом пакете они имеют статус
  `disabled_no_network`; локальный setup разрешает включение только после
  credential. Разрешённые provider-native
  tools появляются в namespace `legal-overlay`; прямое подключение к harness не нужно;

Карточки источников находятся в `references/source-profiles/`; они ссылаются на
существующие канонические методики и не дублируют их.
Каждый профиль содержит обязательные `verification_roles`, `coverage` и
`norm_verification`. `eligible: true` валидируется только вместе с активным
статусом, полным набором coverage, проверенными tools и датой capability-smoke.
Назначение внешних баз, auth gates и переработанные правила из provider skills —
`references/external-legal-databases.md`.

## Snapshot lifecycle

Для следующего immutable snapshot не редактировать путь вслепую. Канонический порядок — `status` → `preflight` → `preview` → `apply --confirm-write`; возврат — `rollback --confirm-write`:

```powershell
python -m tools.legal_overlay.snapshot_lifecycle status
python -m tools.legal_overlay.snapshot_lifecycle preflight --snapshot 'C:\path\to\snapshot-v3'
python -m tools.legal_overlay.snapshot_lifecycle preview --snapshot 'C:\path\to\snapshot-v3'
python -m tools.legal_overlay.snapshot_lifecycle apply --snapshot 'C:\path\to\snapshot-v3' --confirm-write
```

Команда валидирует четыре базы и проводит автономный MCP smoke Codex + Claude до и после атомарной смены общего пути. Предыдущий путь и backup `local.env` остаются в gitignored `profile/settings/`. Полный протокол — `references/sqlite-snapshot-lifecycle.md`.

## Claude Desktop

Preview ничего не записывает и не выводит значения существующих секретов:

```powershell
python -m tools.legal_overlay.bootstrap_claude_desktop
```

Запись требует одновременно `--apply --confirm-write`. При замене существующего
файла создаётся timestamped backup, другие MCP-серверы и верхнеуровневые настройки
сохраняются. Применять запись следует только после просмотра preview.
