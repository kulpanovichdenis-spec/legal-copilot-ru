---
name: case-analysis
description: "Анализирует мультидок-дело в интересах нашей стороны: карта позиций сторон, вывод по спорным вопросам, стратегия, справка и анализ в DOCX. Заключение по отдельному вопросу — legal-opinion, составление документа — procedural-document-drafter."
---

# Анализ дела в интересах нашей стороны (case-analysis)

Архитектурный паттерн: sequential + domain-intelligence, mixed freedom — позиции сторон, исследование, выводы и стратегию готовит агент (класс C); хранение карты позиций и сборку документов делают тулы (класс A): `tools/matter_model/positions.py`, `tools/case_analysis/case_docs.py`.

## Назначение

Stage C воронки анализа дела. Поверх разложенного (Stage A, `skills/case-intake/SKILL.md`) и прочитанного (Stage B, `skills/matter-knowledge/SKILL.md`) дела собирает анализ спора: что утверждает каждая сторона по каждому спорному вопросу, чья позиция сильнее и как строить позицию нашей стороны. Исследование по вопросу идёт методом `legal-opinion`; этот skill задаёт спорную рамку и порядок работы. Итог — два черновика `.docx` в корне папки дела: «Краткая справка по делу» и «Анализ дела и стратегия». Классы исполнения — `references/execution-profiles.md`.

## Когда использовать

- «проанализируй дело», «анализ в интересах нашей стороны», «какие у нас позиции / шансы по делу», «разбор позиций сторон», «стратегия по делу»;
- после `matter-knowledge`, когда юрист принял предложение перейти к Stage C.

## Когда не использовать

- Один правовой вопрос → `legal-opinion`.
- Иск, отзыв, ходатайство, жалоба → `procedural-document-drafter`.
- Критика готового документа или позиции → `position-critic`.
- Библиотека прошлых дел → `case-knowledge-builder`.

## Принципы

1. **Источники до вывода.** Discovery и практика — по `references/source-hierarchy.md` и `references/case-law-search.md` (практика — `search_positions`, связь позиции с нормой — `list_position_norm_links`). Норма подтверждается через `route_norm_verification(..., probe=true)` и маршрут `usable_now: true`; нет маршрута — `[ПРОВЕРИТЬ НОРМУ]`.
2. **Факт ≠ вывод.** Позиции сторон как заявлены — в `matter-positions.yaml` (`stated_basis` — на что сослалась сторона, не наша проверка). Выводы, оценки и стратегия — только в `_analysis/`.
3. **Один движок.** Исследование по вопросу — Шаги 3–5 и 7 алгоритма `skills/legal-opinion/SKILL.md` (метод — `references/legal-opinion-method.md`, §4–§10; метод не копировать): исследование (Шаг 3) → adverse-проход (Шаг 4) → rule synthesis + IRAC с adverse-подшагом и калибровкой §9 (Шаг 5) → claim-ledger (Шаг 7). Шаг 6 «Риски и рекомендация» заменяет стратегия дела (Шаг 5 этого skill); Шаг 8 (два продукта) не запускается.
4. **Чекпоинт до исследования.** Карту вопросов подтверждает юрист; без подтверждения исследование не начинается.
5. **Калибровка без абсолютов.** Шкалы §9 метода, честный отказ. В режиме `position_led` требуемая позиция — гипотеза: adverse-проход обязателен при любой глубине, «не подтверждается» говорится прямо.
6. **Стратегию проверяет `position-critic`.** Выбор линии — `[СТРАТЕГИЧЕСКОЕ РЕШЕНИЕ ЮРИСТА]`.
7. **Черновик.** Оба `.docx` — в корне папки дела; ничего не финализируется, не подаётся и не отправляется.

## Алгоритм

### Шаг 0 — Вход

Прочитать `case-context.md` дела и `deadlines.yaml`, если есть (процессуальные шаги стратегии зависят от сроков), и навигатор в `_knowledge/` (Stage B); работать по карточкам и кешу текста, исходники не перечитывать. Мультидок-дело без `_knowledge/` → предложить сначала `matter-knowledge`. Одно-двухдокументное дело → упрощённый путь: matter-слой завести по `references/matter-model-usage.md` (`model.py init`, `facts.py init`) и работать по документам.

### Шаг 1 — Наша сторона

Сторона с `role: our_side` в `matter-facts.yaml`. Нет — вопрос юристу на чекпоинте (Шаг 3); после ответа:

```bash
python tools/matter_model/facts.py update --file "workflow/<дело>/matter-facts.yaml" --id P-00N --role our_side
# стороны нет в реестре:
python tools/matter_model/facts.py add-party --file "workflow/<дело>/matter-facts.yaml" --name "..." --role our_side --source-doc "..." --source-fragment "..."
```

### Шаг 2 — Карта позиций

Выписать позиции каждой стороны (требования, доводы, возражения, процессуальные просьбы) с locator и сгруппировать в спорные вопросы (`status: proposed`). Судебные акты дела — по `references/court-decision-analysis.md`, раздел C.

```bash
python tools/matter_model/positions.py init --file "workflow/<дело>/matter-positions.yaml" --matter "<дело>"
python tools/matter_model/positions.py add-issue --file "workflow/<дело>/matter-positions.yaml" --question "..." [--depth quick|standard|deep]
python tools/matter_model/positions.py add-position --file "workflow/<дело>/matter-positions.yaml" --party-ref P-00N --issue-ref I-00N --kind claim|argument|defense|procedural_request --statement "как в документе" --source-doc "..." --source-fragment "стр./п." [--evidence "<файл или F-00N>" ...] [--stated-basis "..."]
python tools/matter_model/positions.py add-support --file "workflow/<дело>/matter-positions.yaml" --id C-00N --source-doc "..." --quote "дословно" [--quote-location "п. 5.1"] --stance supports|contradicts
python tools/matter_model/positions.py validate --file "workflow/<дело>/matter-positions.yaml"
```

Доказательства позиции — цитатами (`add-support`), опровергающие — рядом (`--stance contradicts`); состояние позиции считает код (`references/matter-model-usage.md`, «Слой позиций»).

### Шаг 3 — Чекпоинт (обязательный, единственный)

Показать юристу: нашу сторону; карту позиций по вопросам и лиды (`positions.py report`), карту доказательств с пробелами первым блоком (`positions.py report --chart`); предлагаемую глубину по каждому вопросу; режим — `neutral` (найти вариант самому) или `position_led` (искать обоснование требуемой позиции) и саму требуемую позицию. Ответ внести:

```bash
python tools/matter_model/positions.py update --file "workflow/<дело>/matter-positions.yaml" --id I-00N --status confirmed|dropped [--depth ...] [--stance position_led --desired-position "..."]
```

Без подтверждения к Шагу 4 не переходить. Лиды (`unanswered`, `no_evidence`, `empty_issue`, `no_our_side`) — повод посмотреть, не вывод. Краткую справку можно собрать уже здесь (Шаг 6, команда `brief`): она строится только из matter-слоя.

### Шаг 4 — Исследование по каждому подтверждённому вопросу

В начале и по мере исследования поддерживать структуру по `references/case-structure-method.md`: требование → основание → элемент → факт/пробел → источник, ответы на заявленные доводы и доказательственные проблемы. Сохранять в `workflow/<дело>/_analysis/case-analysis.yaml` как `case_structure`, `schema_version: 2` (схема — `tools/case_analysis/README.md`). Пробел факта направлять в уточнение, пробел подтверждения — в сбор доказательств, неопределённость права — в движок ниже; если состав неизвестен, сначала исследовать критерий, не выдумывать элементы. Условная достаточность утверждений не повышает fact_status. До чекпоинта правовую структуру под видом фактуры не строить; второй чекпоинт не вводить. Малые задачи и старые анализы — по границам метода.

Шаги 3–5 и 7 `skills/legal-opinion/SKILL.md` (метод — `references/legal-opinion-method.md`, §4–§10): исследование (Шаг 3) → adverse-проход (Шаг 4) → rule synthesis + IRAC с adverse-подшагом и калибровкой §9 (Шаг 5) → claim-ledger (Шаг 7). Глубина исследования = `depth` вопроса, позиция исследования = `stance`. Спорная рамка: правило применяется к позиции **каждой** стороны; каждый лид `unanswered` получает разбор. Субагенты — по матрице `references/legal-opinion-subagents.md` с глубиной вопроса (`depth`) вместо глубины заключения: `adversarial-researcher` при `standard`/`deep` и всегда при `position_led`; `source-verifier` — claim-ledger при `standard`/`deep` (в `quick` claim-ledger ведётся in-context по всем ссылкам); `consistency-checker` — порог уровня дела, а не одного заключения: при 3+ вопросах или любом вопросе `deep`, потому что «Анализ дела и стратегия» — один многочастный документ. Рабочий блок по вопросу (IRAC, источники, claim-ledger) — `I-00N.md` в `_analysis/`.

### Шаг 5 — Вывод по сторонам и стратегия

Заполнить `case-analysis.yaml` в `_analysis/` по схеме `tools/case_analysis/README.md`: по вопросу — сила нашей позиции, уверенность, значимость, правило, анализ, контраргументы, итог, зависимости, что доказать, ключевые источники; стратегия — линия по вопросам, что собрать, процессуальные шаги, следующий документ. «Чья позиция сильнее» не пишется — тул выводит её из `our_position_strength`. Стратегию проверить `skills/position-critic/SKILL.md`; находки — в `strategy.critic_findings` с приоритетом (блокирующее / высокое / среднее / низкое). Сверить стратегию с разделом «Стратегические решения юриста» `case-context.md`; противоречие не снимать молча, а показать юристу — `[СТРАТЕГИЧЕСКОЕ РЕШЕНИЕ ЮРИСТА]`.

### Шаг 6 — Пресейв и сборка

Пресейв — `references/skill-shared-steps.md`, «Пресейв перед workflow»: нормы через `route_norm_verification`, slop-чек текстов `case-analysis.yaml` по `references/anti-slop.md` (`python tools/slop_check/check.py`). Затем:

```bash
python tools/case_analysis/case_docs.py validate --case "workflow/<дело>"
python -m tools.case_analysis.structure --case "workflow/<дело>"
python tools/case_analysis/case_docs.py brief    --case "workflow/<дело>"
python tools/case_analysis/case_docs.py analysis --case "workflow/<дело>"
```

Отчёт юристу: пути к двум файлам, число вопросов, лиды без ответа, строка пресейва. Следующий документ — рекомендация; готовит его `procedural-document-drafter` по выбору юриста. Обновить `case-context.md` дела: стадия, решения юриста с чекпоинта.

## Что запрещено

- Писать выводы, оценки или стратегию в `matter-*.yaml`.
- Начинать исследование без подтверждённого чекпоинта.
- Подгонять анализ под `desired_position` или скрывать, что позиция не подтверждается.
- Готовить процессуальный документ — это `procedural-document-drafter`.
- Помечать документы как финальные.

## Связанные файлы

- `references/case-structure-method.md` — общий метод, структура и передача в процессуальный документ. Производные действия используются для плана сбора фактов/доказательств и исследования; при выборе следующего документа передать их вместе с case_structure в `procedural-document-drafter`, без повторного сбора фактуры.

- `skills/legal-opinion/SKILL.md` — алгоритм исследования по вопросу (Шаги 3–5 и 7).
- `references/legal-opinion-method.md` — метод исследования (§4–§10, калибровка §9).
- `references/legal-opinion-subagents.md` — матрица субагентов.
- `references/matter-model-usage.md` — matter-слой, включая карту позиций.
- `tools/matter_model/README.md` — CLI хронологии, фактов и позиций.
- `tools/case_analysis/README.md` — сборка документов и схема `case-analysis.yaml`.
- `skills/matter-knowledge/SKILL.md` — Stage B, предшествует.
- `skills/position-critic/SKILL.md` — проверка стратегии.
- `skills/procedural-document-drafter/SKILL.md` — следующий документ по выбору юриста.
