# tools/matter_knowledge — слой знаний по делу (Stage B)

Детерминированный тул (класс A) для документо-центричного слоя знаний «для модели».
Извлечение содержания (тезисы/факты/события) делает агент (skill `matter-knowledge`,
класс C); этот тул только **валидирует форму карточки** и **детерминированно
собирает навигатор**.

## Артефакты (в папке дела `workflow/<дело>/_knowledge/`)

- `<slug>.card.md` — карточка документа: YAML-frontmatter (`doc`, `doc_kind`, `role`,
  `parties`, `dates`, `matter_ids`, `card_status: draft`, `ocr`) + тело
  `## Ключевые тезисы` (каждый тезис с locator'ом «— источник, стр./фрагмент»,
  опц. `→ T-00N`/`F-00N`).
- `<slug>.txt.md` — кеш полного текста документа (ингест один раз).
- `index.md` — навигатор (собирается тулом).

## CLI

```bash
# Валидировать карточки (схема + traceability тезисов)
python tools/matter_knowledge/knowledge.py validate --dir workflow/<дело>/_knowledge

# Собрать навигатор index.md из карточек + matter-timeline/matter-facts
python tools/matter_knowledge/knowledge.py build-index --case "workflow/<дело>"

# Самопроверка
python tools/matter_knowledge/knowledge.py selftest
```

Реюз: `tools/matter_model/` (timeline/facts), `tools/doc_ingest/` (ингест+OCR).
Порог применения — мультидок-дело (см. `references/matter-model-usage.md`).
