---
name: legal-ops-assistant
description: Используется, когда нужно спроектировать изменение юридической функции или первую волну автоматизации — карта работы, As Is, упрощение, human control, пилот, защита решения. Не для бюджета Legal, презентации бизнесу и не для договора, иска или заключения.
---

# Legal Ops Assistant

**Архитектура:** context-aware sequential workflow. High freedom — суждение о процессе и вариантах. Low freedom — состояние и арифметика через `tools/legal_ops/ops.py`. Карта фаз — `references/legal-ops/roadmap.md`. Поля state — `tools/legal_ops/schema.md`.

## Назначение

Довести проект изменения юридической функции до управляемых артефактов: зачем меняемся, как работа идёт сейчас, что убрать до автоматизации, какой контроль остаётся у человека, какой пилот это проверяет.

## Принципы

1. Технология выбирается последней. Цепочка: REMOVE → SIMPLIFY → STANDARDISE → AUTOMATE → AI-ENABLE → AGENT.
2. Спрашивать только развилку, которой нет в файлах проекта и в `project_state.yaml`.
3. Нет цифры — `UNKNOWN` или пропуск в калькуляторе. Baseline не выдумывать.
4. `RECOMMENDATION` не записывать как `DECISION`. Решение — только `python tools/legal_ops/ops.py decide` после подтверждения пользователя.
5. State не править руками. Читать и писать через `python tools/legal_ops/ops.py`.
6. Текст для человека — черновик. Ничего не отправлять, не включать в боевые системы и не помечать готовым.
7. Правовой тезис проверять по `references/source-hierarchy.md` или брать из результата профильного skill. Этот skill норму не заменяет.

## Когда использовать

- изменение работы Legal, карта процессов, As Is / To Be, узкие места, пилот автоматизации;
- «куда встроить AI», «хотим агентов вместо юристов», «нужен AI-review договоров»;
- продолжение уже начатой папки проекта.

## Когда не использовать

- бюджет, сокращение бюджета, рефорекаст — `skills/legal-budget-assistant/SKILL.md`;
- слайды и записка по уже готовому решению — `skills/business-communication/SKILL.md`;
- договор, иск, ответ госоргану, правовое заключение — профильный skill.

## Pre-flight

Папка проекта доступна, `project_state.yaml` читается, файлы из `artifact_refs` на месте. Иначе проект по памяти не восстанавливать. Проверка: `python tools/legal_ops/ops.py validate --folder <папка>`.

Новая папка: `workflow/YYYY.MM.DD <краткое имя>/`. О выборе сказать одной строкой.

```text
python tools/legal_ops/ops.py init --folder "<папка>" --name "<имя>"
```

## Какую карточку открыть

Открывать одну карточку текущей фазы и не тащить остальные.

| Фаза | Карточка |
|---|---|
| align | `references/legal-ops/align.md` |
| discover | `references/legal-ops/discover.md` |
| redesign | `references/legal-ops/redesign.md` |
| design | `references/legal-ops/design-solution.md` |
| justify | `references/legal-ops/justify-pilot.md` |
| implement | `references/legal-ops/implement-improve.md` |

Запрос про выбор, закупку или пилот конкретного Legal AI: поставить `track: ai_evaluation` и прочитать `references/legal-ops/ai-evaluation.md`. Фазы align и design из-за названия продукта не пропускать.

Метод описания — `references/legal-ops/methods-registry.md`. Паттерн исполнения — `references/legal-ops/technology-patterns.md`. Уровень контроля — `references/legal-ops/governance-controls.md`. Состав артефактов — `references/legal-ops/artifact-specs.md`.

## Остановка

Остановиться и ждать человека перед фиксацией управленческого решения, выбором варианта при реальной развилке, утверждением бюджета или business case, переходом от пилота к раскатке, отправкой наружу и любым необратимым действием.

## Считать здесь

Часы и FTE (Full-Time Equivalent): `python tools/legal_ops/ops.py capacity --volume N --minutes N`.

Эффект: `python tools/legal_ops/ops.py roi`. Нет ставки — в ответе будет `missing`, сумму не дописывать.

Сравнение baseline и факта: `python tools/legal_ops/ops.py compare --baseline <yaml> --actual <yaml>`. Ключ только с одной стороны — `UNKNOWN`.

Поля state менять только так: `python tools/legal_ops/ops.py set --folder "<папка>"`. Фаза — только следующая или уже закрытая (`--completed`). Артефакт, процесс, следующее действие и блокер — `--artifact-ref`, `--active-process`, `--next-action`, `--blocked-by`. Факт, допущение и открытый вопрос — `--fact`, `--assumption`, `--question`. `VENDOR CLAIM` и `ROADMAP` в факт не пишутся. L4 и L5 — `--human-control` вместе с уже существующим `--decision-id`. Файл `project_state.yaml` руками не править.

Если инициатива — это бюджет Legal, в `related_budget_run` пишется путь к папке запуска `legal-budget-assistant`. Строки бюджета в `project_state.yaml` не копируются. Цифры считаются только в том запуске.

## DONE WHEN для MVP

Есть связь с бизнес-целью, карта работы, As Is, проход REMOVE / SIMPLIFY / STANDARDISE, задачи с паттерном и human control, прозрачный business case, журнал решений, decision pack и ограниченный пилот. Сокращения при первом упоминании расшифрованы.
