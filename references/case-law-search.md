# Управление поиском судебной практики (case-law-search)

Индекс-роутер метода: как вести поиск судебной практики РФ во внешних базах **как юрист-исследователь** — формировать гипотезы, оценивать выдачу, определять authority и статус практики, решать следующий шаг и когда остановиться. Содержательные правила — в тонких картах `references/case-law-cards/` (подгружать только нужные). Тонкий skill-обёртка для прямого запроса юриста — `skills/case-law-search/SKILL.md`.

**Что это и что НЕ это.** Метод НЕ реализует legal retrieval: корпус, полнотекстовый/семантический поиск, reranking — задача внешних провайдеров (`legal_search`, `search_positions`, kad.arbitr.ru, сайт ВС). Ценность метода — **управлять** поиском базы, а не повторять его. Не входит (делают другие): полный research plan и решение, нужна ли практика/adverse (research skill — `legal-opinion` / `procedural-document-drafter`); adverse/contrary search как обязанность (субагент `adversarial-researcher`); верификация первоисточника (субагент `source-verifier`); подготовка заключения/документа; окончательная квалификация фактов.

## Кто вызывает

Горизонтальный метод шага «Судебная практика» (`references/source-hierarchy.md`, Рабочий цикл, шаг 2). Потребители: `legal-opinion` (Шаг 3 практика + Шаг 4 adverse), `procedural-document-drafter` (Adverse Case Search + обоснование позиции), `gov-response`, `position-critic`, субагент `adversarial-researcher` (применяет эту методологию при поиске против позиции), и прямой запрос юриста через `skills/case-law-search/SKILL.md`.

## Вход

`legal_issue`, проверяемый `proposition`, `research_goal` (приходит извне — от вызывающего skill или из запроса юриста, §4.1), критерий применимости и условия опровержения, `known_facts` / `decisive_facts`, `known_legal_qualification` / `alternative_qualifications`, `claim_or_remedy`, применимый во времени режим, `procedural_context`, `forum`, роль прохода (`standalone` / `supporting` / `adverse`), доступные/предпочтительные providers, ограничения. Не все поля известны сразу: неизвестное остаётся gap. Цель влияет на отбор и оценку, но **не меняет иерархию authority**.

## Цикл

```
issue + proposition + goal → гипотезы (CL-1) → запросы → провайдер → оценка
   → кандидат-статус пула (CL-4) → синтез/coverage (CL-7)
                                  → достаточно → передать результат
                                  → точечный пробел → следующее действие (CL-1 §7.3)
                                  → cap/недоступность → STOP с видимыми gaps
```

Фиксированного числа циклов нет. `established=True` по CL-4 — критерий насыщения однотипной поддержки, а не автоматическое завершение исследования. Готовность текущего прохода оценивается по CL-7; гейт версий и tool-call cap из `references/source-hierarchy.md` останавливают бесплодный поиск с пробелами, не превращая их в подтверждённую позицию.

## Таблица: сигнал → карта (подгружать только сработавшие)

| Сигнал в задаче | Карта |
|---|---|
| нужно построить запросы, выдача пустая/шумная, «как искать» | [CL-1 Планирование запросов](case-law-cards/CL-1-query-planning.md) |
| оценить вес найденного акта; есть отказное определение ВС/ВАС | [CL-2 Иерархия authority](case-law-cards/CL-2-authority-ladder.md) |
| среди источников — позиция ВАС (Пленум/Президиум/письмо/обзор) | [CL-3 ВАС survival check](case-law-cards/CL-3-vas-survival.md) |
| «есть ли сформированная практика», подсчёт округов, статус практики | [CL-4 Статус практики + классификатор](case-law-cards/CL-4-practice-status.md) |
| дело привязано к конкретному округу; кассации расходятся; прогноз | [CL-5 Своя кассация: authority vs forum](case-law-cards/CL-5-own-cassation.md) |
| оценить релевантность/аналогию дела; исключение vs правило; сила мотивировки | [CL-6 Аналогия и характер решения](case-law-cards/CL-6-analogy-and-character.md) |
| свести линию; проверить историю, атрибуцию, независимость, adverse и готовность прохода | [CL-7 Синтез и coverage](case-law-cards/CL-7-synthesis-and-coverage.md) |
| структурный разбор конкретного акта (карточка) | `references/court-decision-analysis.md` (метод, не карта) |

Типовая связка: CL-1 (поиск) → CL-2 (+CL-3 если есть ВАС) → CL-5/CL-6 (оценка) → CL-4 (кандидат-статус) → CL-7 (синтез, coverage, передача/остановка).

## Provider routing

Не хардкодить «provider X всегда первый», кроме явно зафиксированного текущего состояния: ГАРАНТ отключён, а КонсультантПлюс — основной внешний профессиональный источник. Провайдеры и их capabilities живут в `references/source-profiles/` и `references/source-hierarchy.md`; их и использовать. Практика: сначала локальный слой позиций (`legal_search(source_types=["case_law"])`, `search_positions`); при пробеле — КонсультантПлюс (`consultant_search` → раскрытие результата) раньше Casus, ПравоТех и веб-агрегаторов; затем один подходящий и разрешённый после живого smoke Casus corpus (`main` / `sip` / `kas` / `kud`) через единые `casuslegal_*` tools; реквизиты акта — после официального первоисточника kad.arbitr.ru или сайта ВС. Карточка К+ остаётся навигацией. Решения контроллера: `same_provider_refine` / `different_provider` / `specialized_source` / `official_source` / `stop`. Provider capability ≠ юридический authority: смена провайдера не значит, что он «сильнее».

## Оценка выдачи (независимые измерения, §9)

Не сводить к одному `case_score`. Оценивать раздельно: `authority` (CL-2/CL-3), `current_status`, `issue_fit`, `factual_fit`, `legal_qualification_fit`, `claim_or_remedy_fit`, `procedural_fit`, `proposition_role`, `acceptance`/practice_status (CL-4), `forum_relevance` (CL-5), `rule_character` и `argumentative_value` (CL-6).

## Stop-rule и передача

- `established=True` разрешает прекратить добор однотипных подтверждений. До передачи проверить CL-7: later history, режим права, issue fit, targeted opposition, существенные конфликты и независимость линий. Прямая действующая позиция высшего суда с выполненными проверками не требует квоты нижестоящих дел.
- Незакрытая конкретная проверка при доступном бюджете → точечный следующий поиск. Supporting-проход не проводит внутри себя независимый adverse: он передаёт его вызывающему workflow как `caller_pending`.
- Сработал cap или недоступен источник → STOP с gaps. **Не** начинать новый круг, не задавать «найди минимум N решений», фиксированное число итераций или механический exhaustive search. Не нашли → только «в пределах проведённого исследования не обнаружено» с описанием targeted-поиска.
- Ожидание source-verifier или human gate → передача, не дополнительный retrieval. Классификатор и checker не присваивают `VERIFIED_*`.

## Выход для вызывающего workflow (§24)

```yaml
legal_issue:
research_goal:
practice_status: {classification: <CL-4 статус>, consistency: <…>, explanation: …}
research_outcome: READY_FOR_HANDOFF | CONTINUE_TARGETED | STOP_WITH_GAPS | HANDOFF_REQUIRED
key_cases:
  - {case_ref, proposition_ref, dispute_ref, authority_level, current_status, attribution, relevance_reason, analogy_mode, forum_relevance, citation_lineage}
coverage: {checks, targeted_opposition, unresolved_conflicts, caller_pending, constraints}
search_summary: {queries_used, providers_used, material_gaps, stop_reason}
warnings:
```

Реквизиты каждого ключевого акта — только после разбора по `references/court-decision-analysis.md`; неоткрытый первоисточник → `[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]`, в документ юриста не выносится (`references/source-hierarchy.md`, Рабочий цикл, шаг 5). Извлечённую позицию проверяет отдельный проход `source-verifier` — здесь не дублируется.

## Чего не делать (§22, антипаттерны)

Один огромный запрос со всеми фактами/нормами/квалификациями; восемь свободных перефразирований без обучения на выдаче; жёсткая лестница «ВС→кассация→апелляция→первая» независимо от выдачи; «найди минимум N»; самое похожее дело считать самым сильным; новое решение считать автоматически сильнее сохраняющей силу позиции ВАС (CL-3); отказное определение ВС считать позицией ВС (CL-2 X); свою кассацию считать выше других (CL-5); любое множество нижестоящих решений звать «устоявшейся практикой» (CL-4); считать `established` доказательством полного исследования; складывать инстанции одного дела или копирующие цитаты как независимые голоса; одинаковые факты считать достаточными для direct legal analogy без проверки квалификации/remedy (CL-6); принимать довод стороны/пересказ нижестоящего суда за позицию текущего суда (`court-decision-analysis.md`); оценивать authority по качеству мотивировки (CL-6); строить свой retrieval engine.

## Связанные файлы

- `references/case-law-cards/` — CL-1…CL-7 (единственный содержательный слой метода).
- `tools/case_law/practice_status.py` — детерминированный классификатор статуса практики (§13–14); тесты рядом.
- `tools/case_law/research_check.py`, `tools/case_law/README.md` — read-only consistency/coverage contract одного issue.
- `references/court-decision-analysis.md` — структурный разбор акта (карточка A–I).
- `references/source-hierarchy.md` — иерархия источников, Рабочий цикл (шаг 2 практика), «Ограничитель» (гейт версий + tool-call cap).
- `references/query-cookbook.md` — маршрутизация запросов + query expansion.
- `references/external-legal-databases.md` — выбор Casus corpus, безопасные tools и правила раскрытия/сверки акта.
- `references/legal-opinion-subagents.md` — `adversarial-researcher` (adverse) и `source-verifier` (верификация) — отдельные проходы, не часть этого метода.
- `references/citation-rules.md` — цитирование судебных актов.
