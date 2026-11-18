---
name: matter-knowledge
description: "Собирает слой знаний по мультидок-делу: doc-карточки с traceable-тезисами + навигатор index.md, попутно наполняет matter-model (timeline/facts) и кеширует текст. Только фактура, правовых выводов нет."
---

# Слой знаний по делу (matter-knowledge)

Архитектурный паттерн: per-case проход, mixed freedom — извлечение содержания делает модель (класс C), персист фактуры и сборку навигатора делегируем `tools/matter_model/` и `tools/matter_knowledge/`.

## Назначение

Один проход по разобранному Stage A делу читает каждый документ **один раз** и собирает документо-центричный слой «для модели»: карточка на документ + навигатор, попутно наполняя matter-model и кешируя полный текст (Stage C не перечитывает). Границы классов — `references/execution-profiles.md`; слой фактуры — `references/matter-model-usage.md`.

## Принципы

1. **Правовых выводов нет.** Только фактура, позиции сторон **как они заявлены** (petitum иска, возражения отзыва — факт «что просят», не оценка правоты), пробелы фактические. Квалификация/прогноз — Stage C.
2. **Traceability обязательна.** Каждый тезис карточки — с locator'ом (источник после «—»); факт/событие/сторона в matter-model — с `source_doc`+`source_fragment`. Тезис без разделителя-источника «—» тул отклоняет; но реальную traceability (что источник настоящий) обеспечивает агент, не тул.
3. **Не выдумывать.** Тезис/факт/дата/сумма — только из документа; чего нет — маркер (`references/citation-rules.md`) или не вносить.
4. **Не дублировать matter-model.** Содержание фактов/событий живёт в `matter-timeline.yaml`/`matter-facts.yaml`; карточка **ссылается** на `T-…`/`F-…`, не копирует их.
5. **Черновик.** Карточки и навигатор — `card_status: draft`; ничего не финализируется.
6. **Порог.** Только мультидок-дело; одно-двухдокументное → не заводить слой (хватает `case-context`).

## Алгоритм

### Шаг 0 — Предусловие и порог

Дело разобрано Stage A (есть ролевые папки в `workflow/<дело>/`). Документов мало (1–2) → сказать юристу, что слой не нужен, и остановиться.

### Шаг 1 — Инициализировать matter-model (если нет)

```bash
python tools/matter_model/model.py init --file "workflow/<дело>/matter-timeline.yaml" --matter "<дело>"
python tools/matter_model/facts.py init --file "workflow/<дело>/matter-facts.yaml" --matter "<дело>"
```

### Шаг 2 — По каждому документу дела

0. **Карточка приёма.** Если есть `workflow/<дело>/_knowledge/intake/<документ>.intake.json` (Stage A), взять из неё классификацию, стороны, дату и OCR-метаданные. `text_head` там может быть усечён (`text_truncated`), поэтому полный текст всё равно кешируется ингестом ниже.
1. **Ингест полного текста** через `doc_ingest` (локальный OCR для сканов) и **кеш**:
   `python -m tools.doc_ingest.router "<путь-к-документу>" -o "workflow/<дело>/_knowledge/<slug>.txt.md" --quiet`
   Низкое доверие OCR (`[ОЦР НЕ УВЕРЕН]` в warnings) → отметить в поле `ocr` карточки и не выдавать текст как надёжный.
2. **Извлечь фактуру** (класс C, по кешу текста) и внести в matter-model:
   - события → `python tools/matter_model/model.py add --file .../matter-timeline.yaml --event "..." --source-doc "<имя>" --source-fragment "стр./п." --fact-status STATUS [--date YYYY-MM-DD --date-status confirmed|needs_check] [--quote "дословно из документа" --quote-location "п./стр."]`;
   - стороны → `facts.py add-party --file .../matter-facts.yaml --name "..." --role our_side|counterparty|opponent|court|gov_body|third_party --source-doc ... --source-fragment ...`;
   - факты-утверждения → `facts.py add-fact --file ... --statement "..." --fact-status STATUS --source-doc ... --source-fragment ... [--quote "дословно" --quote-location "п./стр."] [--related-event T-00N] [--party-ref P-00N]`;
   - `CONFIRMED` — только с `--quote`: код сверит цитату с документом и без найденной цитаты внесёт запись как `REPORTED` (`references/matter-model-usage.md`, инвариант 6).
   - пробелы → `facts.py add-gap --file ... --unknown "..." --why-relevant "..."`.
   Запомнить возвращённые `T-…`/`F-…`/`P-…`.
3. **Написать карточку** `workflow/<дело>/_knowledge/<slug>.card.md`: frontmatter (`doc`, `text_cache`, `doc_kind`, `role` = ролевая папка, `parties`, `dates`, `matter_ids` = собранные id, `card_status: draft`, `ocr`) + `## Ключевые тезисы` (каждый тезис с locator'ом, где есть — `→ T-…`/`F-…`).

### Шаг 3 — Собрать навигатор и провалидировать

```bash
python tools/matter_knowledge/knowledge.py build-index --case "workflow/<дело>"
python tools/matter_knowledge/knowledge.py validate --dir "workflow/<дело>/_knowledge"
python tools/matter_model/model.py validate --file "workflow/<дело>/matter-timeline.yaml"
python tools/matter_model/facts.py validate --file "workflow/<дело>/matter-facts.yaml"
```

### Шаг 4 — Отчитаться юристу

Одна строка: сколько карточек, событий, фактов, сторон, пробелов; путь к навигатору `workflow/<дело>/_knowledge/index.md`. Предложить Stage C — `case-analysis` (анализ в интересах нашей стороны). Правовых выводов не давать.

## Что запрещено

- Правовые выводы, оценка перспектив, квалификация — это Stage C.
- Готовить `.docx`/материалы для человека — в Stage B их нет (Stage C).
- Копировать содержание фактов/событий в карточку вместо ссылки на `T-…`/`F-…`.
- Повышать `fact_status` до `CONFIRMED` без источника (инвариант matter-model).
- Заводить слой для одно-двухдокументного дела.

## Связанные файлы

- `references/matter-model-usage.md` — слой фактуры (timeline/facts), порог, инварианты.
- `references/execution-profiles.md` — классы исполнения.
- `tools/matter_knowledge/README.md` — тул (валидация карточки, сборка навигатора).
- `tools/matter_model/README.md` — CLI хронологии/фактов.
- `tools/doc_ingest/README.md` — ингест + локальный OCR.
- `skills/case-intake/SKILL.md` — Stage A (раскладка), предшествует.
