# case_analysis — документы Stage C (справка и анализ дела)

Детерминированная сборка двух черновиков `.docx` для юриста по итогам skill
`case-analysis`.

Модуль ничего не пишет от себя: текст берётся из файлов папки дела, от себя добавляются
только заголовки разделов и подписи полей. Оформление — профиль `NoteDoc`
(`tools/docx_style/profiles.py`), маркеры неполноты подсвечиваются.

## Вход (папка дела)

| Файл | Откуда | Нужен для |
|---|---|---|
| `case-context.md` | агент / юрист | номер дела и статус (frontmatter), стадия (строка «Стадия:» или раздел `## Стадия` — формат Stage A); нет данных → `[ПРОВЕРИТЬ ФАКТ]` в справке; файл необязателен |
| `matter-timeline.yaml` | `tools/matter_model/model.py` | справка, анализ |
| `matter-facts.yaml` | `tools/matter_model/facts.py` | справка, анализ (стороны, наша сторона, пробелы) |
| `matter-positions.yaml` | `tools/matter_model/positions.py` | справка, анализ |
| `case-analysis.yaml` в `_analysis/` | skill `case-analysis`, шаг 5 | только анализ |

## Выход

В корне папки дела, дата подготовки в имени, существующий файл не перезаписывается
(коллизия → ` (2)`):

- `ГГГГ-ММ-ДД Краткая справка по делу.docx` — только из matter-слоя: дело; стороны;
  фактические обстоятельства (события по хронологии, непроверенное — с маркерами); что хотят
  стороны; что хотим мы; чего не хватает (наши пробелы и наши позиции без доказательств);
  позиции других участников без доказательств — отдельным списком. Если анализ уже есть,
  первым идёт абзац «Коротко» из `brief_summary`.
- `ГГГГ-ММ-ДД Анализ дела и стратегия.docx` — выводы кратко; карта позиций сторон;
  мотивировка по вопросам; стратегия; риски и замечания `position-critic`; заметка юристу;
  источники.

Снятые (`dropped`) вопросы в документы не попадают.

## Схема `case-analysis.yaml`

```yaml
schema_version: 1
matter: "<дело>"
our_side: P-001                      # = сторона role: our_side в matter-facts
brief_summary: ""                    # опц.: абзац «Коротко» для справки
issues:                              # каждый подтверждённый (confirmed) вопрос matter-positions
  - issue_ref: I-001
    our_position_strength: moderately_strong  # strong | moderately_strong | balanced | moderately_weak | weak
    certainty: medium                          # high | medium | low
    impact: high                               # low | medium | high | critical
    rule: "..."                      # обязательно
    analysis: "..."                  # обязательно: правило применено к позиции каждой стороны
    counterarguments: "..."
    conclusion: "..."                # обязательно
    dependencies: ["..."]
    mitigation: ["..."]
    to_prove: ["..."]
    key_sources: ["..."]             # обязательно непусто
strategy:
  summary: "..."                     # обязательно
  per_issue: [{issue_ref: I-001, line: "..."}]
  evidence_to_collect: ["..."]
  procedural_steps: ["..."]
  next_document: "..."               # рекомендация; документ готовит procedural-document-drafter
  critic_findings: [{priority: высокое, text: "..."}]   # блокирующее | высокое | среднее | низкое
lawyer_notes: ["..."]
```

Шкалы — `references/legal-opinion-method.md` §9. «Чья позиция сильнее» не хранится, её
выводит `stronger_side` при сборке: strong / moderately_strong → наша сторона; balanced →
равные шансы; moderately_weak / weak → оппонент.

## CLI

```bash
python tools/case_analysis/case_docs.py validate --case "workflow/<дело>"
python tools/case_analysis/case_docs.py brief    --case "workflow/<дело>" [--date ГГГГ-ММ-ДД]
python tools/case_analysis/case_docs.py analysis --case "workflow/<дело>" [--date ГГГГ-ММ-ДД]
python tools/case_analysis/case_docs.py selftest
```

`validate` проверяет справку, а если `case-analysis.yaml` уже есть или повреждён — и анализ:
наша сторона задана; matter-слой валиден; структура `case-analysis.yaml` (типы полей, списки
строк без пустых элементов, `strategy` — объект, без дублей `issue_ref`); `issue_ref`
существует и подтверждён; каждый подтверждённый вопрос разобран; хотя бы один вопрос
`confirmed` и ни одного оставшегося `proposed`; значения шкал допустимы; непусты `rule`,
`analysis`, `conclusion`, `key_sources`, `strategy.summary`; приоритеты находок допустимы.
`brief` и `analysis` перед сборкой делают ту же проверку и при ошибке файл не создают;
битый `case-analysis.yaml` не блокирует справку — она строится только из matter-слоя.

## Конфиденциальность

Папки дел живут в `workflow/` (в `.gitignore`). Демо-дело `write_demo_case` — обезличенная
фикстура для `selftest` и тестов.

## Версия 2: структура требований (2026-10-15)

Для новых анализов требований использовать `schema_version: 2`. Поля v1 выше
сохраняются; добавляется обязательный `case_structure`. Версия 1 (в том числе
старый файл без номера версии) читается без изменения; DOCX явно отмечает
«Структура элементов не проверялась». Неизвестная версия отклоняется.
v1 с добавленным case_structure отклоняется: выбрать версию явно, не скрывать проверку.
Повреждение нового блока не блокирует справку, построенную из фактуры.

Все показанные ниже поля обязательны, кроме `owner` действия. Пустые списки допустимы,
если прямо не требуется непустое содержимое. Строка означает непустую строку.
Метод и границы — `references/case-structure-method.md`.

```yaml
case_structure:
  objective:
    legal_outcome: "Требуемое последствие"
    business_goal: "Цель бизнеса или явно: неизвестна"
    stage: "Стадия по контексту"
  excluded_claims: []   # либо [{position_ref: C-003, reason: "Зависимая просьба об отказе"}]
  claims:              # непустой список
    - id: R-001
      position_ref: C-001       # kind claim/procedural_request
      issue_ref: I-001          # confirmed, совпадает с issue позиции
      outcome: "Запрошенное правовое последствие"
      bases:                   # непустой список; альтернативы внутри одного требования
        - id: B-001
          role: primary        # primary | alternative | subsidiary | exclusive
          rule:
            text: "Правило, критерий и существенные исключения"
            source: "Точный источник/locator либо [ПРОВЕРИТЬ НОРМУ]"
            status: UNVERIFIED # UNVERIFIED | OPENED | VERIFIED
          sufficiency: complete
          assessment: "Почему эта оценка основания обоснована"
          next_steps: []        # действия по неопределённости основания в целом
          elements:            # непустой список обязательных элементов
            - id: E-001
              criterion: "Условие требуемого последствия"
              fact_refs: [F-001] # F или T, должны существовать в текущем деле
              gap_refs: []       # G из matter-facts
              allegation_status: present
              assessment: "Что заявлено; состояние подтверждения оценивается отдельно"
              next_steps: []
  responses: []
  proof_issues: []
```

`sufficiency`: complete / missing_facts / structural_failure / legal_uncertainty /
qualification_uncertainty. `allegation_status`: present / missing / structural_failure /
legal_uncertainty / qualification_uncertainty. COMPLETE относится к утверждениям,
не к доказанности или выигрышу. PRESENT требует fact_refs; MISSING требует gap_refs.
Неполный элемент не совместим с complete основания.

Неразрешённый элемент требует next_steps с соответствующим типом:
missing → request_fact; legal_uncertainty → research_law; qualification_uncertainty →
compare_bases; structural_failure → compare_bases/research_law/lawyer_decision.
Общая оценка не заменяет сохранение разных проблем элементов.

Любое неразрешённое основание требует соответствующего действия в собственных next_steps
или next_steps его элементов. missing_facts требует элемента с отсутствующим тезисом;
если тезис есть, но нет подтверждения, это proof gap. Действия основания тоже включаются в очереди.

Каждое требование/процессуальная просьба по confirmed issue должно быть разобрано
или названо в excluded_claims с причиной. Это формальная полнота охвата позиций,
не проверка полноты выбранного материального состава. Альтернативы не дублируют позицию C.

Ответы:

```yaml
responses:
  - id: D-001
    position_ref: C-002
    target_ref: E-001 # R/E/D; цепочка D не должна образовывать цикл
    kind: legal_disagreement # factual_denial | alternative_facts | legal_disagreement | independent_defense | rhetoric | supporting_argument
    material: true
    assessment: "Как меняется результат, если довод верен"
    state: open      # open | answered | closed
    next_steps:
      - kind: research_law
        action: "Проверить спорный критерий по источникам"
        owner: "Юрист" # необязательно; неизвестного ответственного не сочинять
```

Положительный argument в поддержку требования получает kind supporting_argument;
его не переклассифицируют в возражение или риторику для прохождения проверки.
Несущественный ответ (`material: false`) закрывается с объяснением. Существенный open
требует действия. Гипотетические adverse-доводы остаются в контраргументах анализа;
каждая заявленная позиция argument/defense по confirmed-вопросу должна получить запись
responses, включая закрытую запись для несущественного довода. Неподтверждённый вопрос
не используется как источник ответа. strong_support требует непустого support_refs.
фиктивная позиция стороны ради position_ref не создаётся.

Доказательственные проблемы:

```yaml
proof_issues:
  - id: PF-001
    element_ref: E-001
    fact_refs: [F-001] # из ссылок этого элемента; fact_refs или gap_refs непусто
    gap_refs: []
    trigger: missing_support # factual_dispute | missing_support | source_conflict | admissibility
    party_position: unknown  # disputed | agreed | unknown; независимо от fact_status
    materiality: "Почему доказательственная проблема влияет на элемент"
    burden: {text: "Кто доказывает, специальные правила/презумпции", source: "[ПРОВЕРИТЬ НОРМУ]", status: UNVERIFIED}
    support_refs: []          # F/T; источник/цитата разрешаются из matter-слоя
    counter_refs: []          # F/T
    problems: "Что не подтверждено, вопросы допустимости и достоверности"
    availability: "Можно ли получить недостающее"
    nonproof_consequence: "Как отсутствие подтверждения влияет на исход"
    state: incomplete_support
    next_steps: [{kind: request_evidence, action: "Запросить документ"}]
```

`state`: strong_support / incomplete_support / material_contradiction /
counter_evidence_significant / unavailable_source / unable_to_assess. Незавершённая
проблема требует действия. factual_dispute требует позиции disputed; при source_conflict
или missing_support допустима unknown. При structural_failure основания глубокий proof
этого основания отклоняется; другие требования/альтернативы этим не блокируются.

ID R/B/E/D/PF глобально уникальны внутри блока; F/T/G/C/I существуют только в исходном
matter-слое. Поля rule/burden одинаковы: text/source/status. VERIFIED заявляет агент после
штатной проверки источника, код не присваивает этот статус. OPENED/UNVERIFIED в DOCX
сохраняют маркер проверки. Проверка совпадения цитаты не подтверждает истинность факта.

Действие next_steps: kind из request_fact / request_evidence / research_law / compare_bases /
lawyer_decision, непустой action, опциональный owner. Производные очереди не сохраняются
отдельно и не попадают в watcher. DOCX содержит действия и нерешённые вопросы; CLI отдаёт
их вместе с исходными ID для исследования/сбора доказательств и передачи в drafting:

```bash
python -m tools.case_analysis.structure --case "workflow/<дело>"
```

CLI читает и валидирует весь анализ, ничего не записывает. Для v1 возвращает legacy warning.
Код проверяет типы, ссылки, циклы и формальные зависимости. Значимость факта, полный состав,
правильность нормы и бремени, причинность и допустимость остаются оценкой агента/юриста
через прежние gates. Одних зелёных тестов недостаточно для вывода о юридической корректности.
