# Слой знаний из прошлых претензионных и судебных дел

## Назначение и границы

Слой превращает проверенные разборы прошлых дел в два разных объекта:

1. **Case study** — обезличенная карточка конкретного дела с фактическим паттерном,
   стадиями, результатом, ограничениями и provenance.
2. **Knowledge object** — короткий переиспользуемый вывод. Для опыта практики
   используется `type: practice_pattern`.

Case study не является нормой права, судебным прецедентом или доказательством по
новому делу. Knowledge object не заменяет проверку фактов нового дела, действующей
нормы и актуальной судебной практики.

## Где хранится

- карточки: `profile/knowledge/case-studies/cards/claims/`,
  `profile/knowledge/case-studies/cards/litigation/` и
  `profile/knowledge/case-studies/cards/employment/`;
- кадровые процедуры и перечень шаблонов, без playbook:
  `profile/knowledge/case-studies/employment-library/`;
- атомарные объекты: общий lifecycle
  `profile/knowledge/candidates/` → `verified/` → `superseded/`;
- схема карточки и валидатор: `tools/case_knowledge/`;
- правила promotion: `references/local-verified-knowledge-protocol.md`.

Содержимое профиля конфиденциально и исключено из git. В репозитории хранится
только скелет, схема, валидатор и правила.

## Источники и доверие

Приоритет источников внутри разобранного дела:

1. мотивированный судебный акт;
2. подписанный договор, соглашение, первичный или исполнительный документ;
3. направленная претензия или процессуальный документ;
4. переписка и доказательство направления;
5. проект, внутренний расчёт или аналитический вывод.

Разбор другой сессии допустим как вход только когда он содержит source inventory,
provenance, неопределённости и QA. Он остаётся вторичным аналитическим источником:
для спорного или сильного вывода исходник проверяется точечно.

Не импортируются как знания: промежуточные JSON, служебные скрипты, дубли,
неподтверждённые проекты, персональные данные и коммерческие реквизиты.

## Контракт case study

Схема v2 (`schema_version: 2`). Обязательные поля: `case_study_id`, `matter_kind`,
`jurisdiction` (`RU`), `dispute_type`, `our_role`, `stages`, `matter_stage`,
`outcome` (объект: `merits_result`, `appeal_status`, `settlement_status`,
`enforcement_status`, `recovery_status`, `outcome_evidence`),
`evidence_chain_completeness`, `law_as_of`, `requires_current_law_check` (всегда
`true` для исторического дела), `topics`, `source_case_ids`, `source_refs`,
`anonymization`, `review_status`, `knowledge_candidate_ids`, `updated`.
Допустимые значения `matter_kind`, `matter_stage`, `our_role`, `dispute_type` —
`tools/case_knowledge/vocab/`. Необязательные: `court_case_numbers`,
`related_workflow`. Шаблон заполнения —
`templates/agent-notes/case-study-template.md`.

Markdown-карточка имеет YAML-frontmatter по
`tools/case_knowledge/case-study.schema.json` и минимум следующие разделы:

- краткий контекст и роли без наименований сторон;
- фактический паттерн и хронология;
- позиции и доказательственная модель;
- раздельный результат по существу, обжалованию, урегулированию и исполнению;
- что сработало, что не подтверждено и чего не хватает;
- кандидаты в переиспользуемые паттерны;
- границы вывода, вопросы ревью и provenance.

Один реальный спор получает один `case_study_id`, даже если он разобран в двух
корпусах. Источники объединяются в `source_case_ids` и `source_refs`.

## Контракт practice_pattern

Помимо общих полей knowledge object обязательны:

```yaml
type: practice_pattern
pattern_kind: evidence | drafting | procedure | settlement | enforcement | risk_antipattern
support_level: single_case | multi_case | court_confirmed
source_case_ids: []
review_questions: []
reuse_target: []
legal_dependencies: []
requires_current_law_check: true
```

`reuse_target` — куда приём должен попасть при использовании
(`procedural-document-drafter`, `counterparty-letter`, `contract-review`,
`contract-drafter`, `position-critic`, `legal-opinion`, `intake_checklist`,
`playbook:<имя>`). `legal_dependencies` — нормы, на которые приём опирается;
каждая со статусом `requires_current_law_check`, пока норма не проверена в момент
использования. `requires_current_law_check` по умолчанию `true`.

- `single_case` — наблюдение поддержано одним делом;
- `multi_case` — один узкий вывод подтверждается несколькими независимыми делами;
- `court_confirmed` — конкретный практический вывод прямо подтверждён мотивированным
  судебным актом. Наличие выигранного дела без мотивировки этого статуса не даёт.

`position` формулируется как операционный приём или риск, а не как универсальное
правило права. `applies_when` и `does_not_apply_when` обязательны по существу.

## Lifecycle

1. Источники инвентаризируются и дедуплицируются.
2. Из каждого уникального спора создаётся обезличенная case study со статусом
   `review_status: candidate`.
3. Повторяемые наблюдения дедуплицируются в атомарные `practice_pattern`.
4. Они создаются только в `profile/knowledge/candidates/` со статусом
   `machine_extracted` или `machine_reviewed`.
5. Юрист проверяет формулировку, применимость, поддержку и provenance.
6. Только явный promotion по hash переводит объект в `human_verified`.
7. Устаревший объект переводится в `superseded`, а не редактируется молча.

Нельзя автоматически повышать статус карточки или knowledge object по количеству
дел, успешному исходу либо прохождению технической валидации.

## Использование

В новой претензии, иске, отзыве, критике позиции или playbook сначала ищутся
только `human_verified` объекты по типу спора, проблеме и стадии. Найденный паттерн:

- помогает построить evidence checklist, структуру документа и список рисков;
- всегда сверяется с фактами текущего дела;
- при правовом тезисе запускает отдельную проверку нормы и практики;
- сопровождается ссылкой на knowledge object; case study открывается только когда
  нужен контекст происхождения вывода.

Кандидаты не используются в runtime как правило. Их можно показывать юристу лишь
в отдельном режиме ревью с явной маркировкой `candidate`.

## Чего нет в папке

Нет документа об итоге претензии — не вывод, что требование не удовлетворено: после претензии оно могло быть исполнено без суда. Нет платёжной отметки в судебной папке — не вывод, что деньги не получены: это кейс о суде, не о взыскании. Иное только если исполнительные документы есть в самом комплекте.

Кадровые процедуры и перечень шаблонов не становятся playbook и не идут в `candidates/`. Они лежат в `employment-library/`.

## Обезличивание

Порядок: `tools/pre_anonymize/prepare.py --profile full` → карточка пишется по
`.anon.md`, не по оригиналу разбора → regex-аудит валидатора. Номера судебных дел
сохраняются в provenance. `*.mapping.json` не читать и не передавать в контекст модели.

## Навигатор

`profile/knowledge/case-studies/index.md` собирается командой
`python tools/case_knowledge/case_studies.py build-index profile/knowledge/case-studies/cards`.
Агент читает навигатор первым. Полнотекст карточек — `rg --no-ignore`: карточки лежат
в `.gitignore`.

## Свежесть

`python tools/case_knowledge/case_studies.py stale-check profile/knowledge --months 12`
раз в месяц запускает юрист. Команда ничего не записывает: печатает список
объектов к ревалидации. Решение принимает юрист.

## Контроль качества

```powershell
python tools/case_knowledge/case_studies.py validate profile/knowledge/case-studies/cards
```

Проверяются: уникальность ID, схема, отсутствие прямых идентификаторов, provenance,
разделение исходов и отсутствие кандидатов в verified-поиске.
