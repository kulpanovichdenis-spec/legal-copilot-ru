# matter_model — структурный слой дела (timeline + factual layer)

Ядро структурного промежуточного слоя дела.
Даёт в папке дела три машиночитаемых артефакта и детерминированные тулы к ним
(по образцу `tools/deadline_tracker`):

- **`matter-timeline.yaml`** — хронология (факты-события) — тул `model.py`;
- **`matter-facts.yaml`** — factual layer (стороны / факты-состояния / пробелы) — тул `facts.py`.
- **`matter-positions.yaml`** — позиции сторон по спорным вопросам (как заявлены, не анализ) — тул `positions.py`.

**Правила использования агентом — [`references/matter-model-usage.md`](../../references/matter-model-usage.md)** (единый источник истины; этот README — техническая справка по CLI).

## Что это решает

Для мультидок-дел (10+ файлов) агент сейчас каждый раз пересобирает хронологию
рассуждением, а результат живёт прозой в `case-context.md` и не переиспользуется
между skills. Timeline выносит **факты-события** в yaml (как сроки уже ушли в
`deadlines.yaml`), с обязательной traceability к источнику, и даёт формальный
детект кандидатов противоречий / двойного счёта.

**Evidence-matrix** (`matter-evidence.yaml`, `required_elements`) и document-grid —
вне слоя (ТЗ 2026-09-01 §4/§12), решаются после замера пользы. Объекты
disputed-facts / evidence-map / contradictions — не отдельные файлы, а **производные
представления** `facts.py report` (один источник истины на данные).

## Разделение LLM vs код

- **Агент/юрист (LLM):** извлекает события из документов, квалифицирует факты,
  оценивает противоречия. Это НЕ делает скрипт.
- **Скрипт (детерминированное):** валидация схемы и traceability, сортировка по
  дате, формальный детект дубликатов / двойного счёта / расходящихся статусов,
  рендер markdown-сводки. Кандидат — лид для юриста, не утверждённый вывод.

## Схема события (`matter-timeline.yaml`)

| Поле | Обяз. | Значение |
|---|---|---|
| `event` | да | что произошло |
| `source_doc` | да | документ-источник (traceability) |
| `source_fragment` | да | пункт/лист/строка в источнике (traceability) |
| `fact_status` | да | `CONFIRMED` / `REPORTED` / `INFERRED` / `DISPUTED` / `UNKNOWN` / `ASSUMED` (fact-matrix, `references/legal-opinion-method.md`) |
| `date` | нет | `YYYY-MM-DD` или пусто |
| `date_status` | — | `confirmed` \| `needs_check` (confirmed требует `date`) |
| `participant` | нет | сторона/лицо |
| `location` | нет | место/склад (нужно для детекта двойного счёта) |
| `amount` | нет | сумма ₽ (нужно для детекта двойного счёта) |
| `claim_key` | нет | группировка событий одного факта (для детекта конфликта статусов) |
| `notes` | нет | заметка |

`id` (`T-001…`), `created`, `updated` — служебные, ведёт тул.

## CLI

```bash
# создать хронологию дела
python tools/matter_model/model.py init --file "workflow/<дело>/matter-timeline.yaml" --matter "<имя>"

# внести событие (source-doc + source-fragment + fact-status обязательны)
python tools/matter_model/model.py add --file "workflow/<дело>/matter-timeline.yaml" \
  --event "утрата товара, пожар" --date 2026-08-06 --date-status confirmed \
  --participant "ООО «Ромашка»" --location "Склад-1" --amount 105000 \
  --source-doc "Реестр атак" --source-fragment "стр. 3" \
  --fact-status REPORTED --claim-key loss-kotovsk

# проверить схему и traceability
python tools/matter_model/model.py validate --file "workflow/<дело>/matter-timeline.yaml"

# сводка: хронология + кандидаты противоречий/двойного счёта
python tools/matter_model/model.py report --file "workflow/<дело>/matter-timeline.yaml"

# автотест (TDD на данных условного дела)
python tools/matter_model/model.py selftest
```

## Детект кандидатов (формальный)

- `duplicate` — совпадают дата/событие/участник/место/сумма;
- `double_count` — одна `(location, amount)` в ≥2 разных событиях (кандидат
  двойного счёта, напр. Склад-1 ~105 тыс. ₽ из реестра и из расчёта размера);
- `status_conflict` — одна `claim_key` с расходящимся `fact_status` (напр.
  утрата `REPORTED` против «сохранности» `DISPUTED`).

Все — **кандидаты**; юридическую оценку даёт юрист.

## Factual layer (`matter-facts.yaml`, тул `facts.py`)

Три коллекции объектов рядом с timeline. Правила использования агентом —
[`references/matter-model-usage.md`](../../references/matter-model-usage.md),
раздел «Factual layer».

**`facts` (F-001…):** `statement` (обяз.), `fact_status` (обяз., тот же fact-matrix из
`model.py`), `source_doc`+`source_fragment` (обяз., traceability), `legal_relevance`
(`not_assessed`/`potentially_relevant`/`material`; дефолт `not_assessed`),
`contradicted_by[]`, `related_events[]` (`T-…`), `party_ref`, `status_history` (ведёт тул).

**`parties` (P-001…):** `name`+`role` (обяз.), `requisites`, `req_status`
(`verified`/`unverified` → `[ПРОВЕРИТЬ РЕКВИЗИТЫ]`), `source_doc`+`source_fragment` (обяз.).

**`gaps` (G-001…):** `unknown`+`why_relevant` (обяз.), `potential_evidence[]`,
`status` (`open`/`searching`/`resolved`/`unavailable`; дефолт `open`), `related[]`.

```bash
# создать factual layer дела
python tools/matter_model/facts.py init --file "workflow/<дело>/matter-facts.yaml" --matter "<имя>"

# сторона / факт / пробел
python tools/matter_model/facts.py add-party --file F --name "ООО «Альфа»" --role counterparty \
  --requisites "ИНН 7700000000" --req-status unverified --source-doc "договор" --source-fragment "преамбула"
python tools/matter_model/facts.py add-fact --file F --statement "оплата не поступила" \
  --fact-status REPORTED --source-doc "письмо" --source-fragment "абз.2" [--legal-relevance material] \
  [--contradicted-by F-002] [--related-event T-001]
python tools/matter_model/facts.py add-gap --file F --unknown "куда перечислены средства" \
  --why-relevant "определяет обязанного субъекта" --potential-evidence "данные эквайера"

# правка одного поля (принцип 1: повысить факт до CONFIRMED можно только с новым источником)
python tools/matter_model/facts.py update --file F --id F-001 --fact-status CONFIRMED \
  --source-doc "выписка банка" --source-fragment "стр.2"

# схема + traceability; сводка (стороны/факты/пробелы + evidence-map/disputed/contradictions,
# с автоподхватом соседней matter-timeline.yaml)
python tools/matter_model/facts.py validate --file F
python tools/matter_model/facts.py report   --file F

# автотесты
python tools/matter_model/facts.py selftest
```

`facts.py` импортирует `fact_status`-словарь и хелперы из `model.py` — **один источник
истины**, локально не переопределяет. Производные представления (evidence-map /
disputed-facts / contradictions) вычисляются в `report`, отдельными файлами не хранятся.

## Слой позиций (`matter-positions.yaml`, тул `positions.py`)

Третья коллекция рядом с timeline и factual layer: **что заявляют стороны** по спорным
вопросам. Это факт о деле («сторона утверждает X»), а не правовой анализ. Ведёт skill
`case-analysis` (Stage C); правила — [`references/matter-model-usage.md`](../../references/matter-model-usage.md),
раздел «Слой позиций».

**`issues` (I-001…):** `question` (обяз.), `status` (`proposed`/`confirmed`/`dropped`; дефолт
`proposed`), `depth` (`quick`/`standard`/`deep`; дефолт `standard`), `stance`
(`neutral`/`position_led`; дефолт `neutral`), `desired_position` (обяз. при `position_led`).

**`positions` (C-001…):** `party_ref` (обяз., сторона из соседнего `matter-facts.yaml`),
`issue_ref` (обяз.), `kind` (`claim`/`argument`/`defense`/`procedural_request`), `statement`
(обяз., как в документе), `evidence[]`, `stated_basis` (на что сослалась сторона, это не наша
проверка), `source_doc`+`source_fragment` (обяз., traceability).

```bash
python tools/matter_model/positions.py init --file P --matter "<имя>"
python tools/matter_model/positions.py add-issue --file P --question "Пропущен ли срок исковой давности?"
python tools/matter_model/positions.py add-position --file P --party-ref P-002 --issue-ref I-001 \
  --kind claim --statement "Взыскать 105 000 руб. долга" --source-doc "иск" \
  --source-fragment "просительная часть" --evidence "Иск_приложения/договор.pdf"
python tools/matter_model/positions.py update --file P --id I-001 --status confirmed --depth deep
python tools/matter_model/positions.py validate --file P
python tools/matter_model/positions.py report   --file P   # карта по вопросам + лиды
python tools/matter_model/positions.py selftest
```

Лиды `report` формальные, они нужны для чекпоинта юриста: `unanswered` (доводы других
участников без позиции нашей стороны; позиции суда не считаются), `no_evidence` (позиция без
доказательств), `empty_issue` (вопрос без позиций), `no_our_side` (в `matter-facts` нет
`role: our_side`). Снятые (`dropped`) вопросы лидов не дают. Реестр сторон и роли не
дублируются: они берутся из `matter-facts.yaml` (`facts.PARTY_ROLES`).

## Конфиденциальность

Файл живёт в `workflow/` (в `.gitignore`) — допустимы необезличенные данные.

## Статус

`model.py` (timeline) + `facts.py` (factual layer) + `positions.py` (позиции сторон), без внешних зависимостей кроме
`pyyaml`. Полноценный skill (`skills/matter-model/`) НЕ создаётся — по критерию «skill
не нужен, если хватает reference + тул» (architecture-audit): слой ведут агент/юрист
по правилам `references/matter-model-usage.md`, downstream-skills его читают.
Evidence-matrix (`matter-evidence.yaml`, `required_elements`) и document-grid — по
критерию «3 проверок» после замера пользы factual layer на реальных мультидок-делах.
