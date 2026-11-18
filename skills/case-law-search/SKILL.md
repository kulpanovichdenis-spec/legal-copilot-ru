---
name: case-law-search
description: "Подбирает и оценивает судебную практику РФ по правовому вопросу — ведёт поиск по внешним базам как юрист-исследователь, различает authority / forum relevance / argumentative value, определяет статус практики и ключевые акты. Верификацию первоисточника и подготовку заключения не заменяет."
---

# Case-Law Search

**Архитектура:** контроллер поиска, High freedom. Тонкий роутер к методу `references/case-law-search.md` и картам `references/case-law-cards/` (CL-1…CL-7); детерминированный счёт статуса практики — `tools/case_law/practice_status.py`, формальная проверка пула и coverage — `tools/case_law/research_check.py`. Ничего из методологии здесь не дублируется.

## Назначение

Skill управляет поиском судебной практики во внешних базах (`legal_search`, `search_positions`, kad.arbitr.ru, сайт ВС) как опытный юрист-исследователь: формирует несколько поисковых гипотез, оценивает выдачу, различает **authority ≠ похожесть ≠ forum relevance ≠ argumentative value**, определяет статус практики (сформированная / преобладающая / split / единичная) и возвращает ключевые акты с обоснованием. **Своего retrieval-движка не строит** — управляет чужим поиском.

Два способа вызова:
- **прямой запрос юриста** — «найди/подбери практику по…», «какая практика по…» (этот skill);
- **из другого workflow** — как шаг «Судебная практика» research-цикла (`legal-opinion`, `procedural-document-drafter`, `gov-response`, `position-critic`), через метод `references/case-law-search.md`.

## Когда использовать

Триггеры:
- «найди / подбери / поищи судебную практику по …», «какая практика по …», «есть ли практика по …»;
- «подбери судебные акты / позиции ВС по …», «сложилась ли практика по …», «как суды смотрят на …»;
- «практика по статье … / по делу № … / по такому спору».

## Когда не использовать

- **Разбор одного конкретного акта** (карточка) → метод `references/court-decision-analysis.md`.
- **Поиск практики ПРОТИВ позиции** (adverse) → субагент `adversarial-researcher` (он применяет эту же методологию).
- **Верификация текста/реквизитов найденного акта** → субагент `source-verifier`.
- **Готовое заключение / процессуальный документ** → `legal-opinion` / `procedural-document-drafter` (они вызывают этот поиск как шаг).
- **Дайджест или обзор практики для юриста** → `skills/legal-digest/SKILL.md`. Этот skill остаётся шагом поиска на маршруте `CASELAW_TREND`.

## Алгоритм

Полный метод — `references/case-law-search.md`. Костяк:

1. **Вход и цель.** Взять `legal_issue` + `research_goal` (из запроса юриста или вызывающего workflow) + известные факты/квалификации/forum. Цель влияет на отбор, не на authority.
2. **Гипотезы (CL-1).** Facts-first + qualification-first + альтернативные квалификации отдельными запросами; первый поиск короткий и широкий.
3. **Провайдер и выдача.** Локальный слой позиций первым (`legal_search(source_types=["case_law"])` / `search_positions`). Если его недостаточно — КонсультантПлюс (`consultant_search` → `consultant_get_text` / `consultant_get_document`) раньше Casus, ПравоТех и веб-агрегаторов; карточка К+ — навигация; ГАРАНТ отключён. Затем, если provider авторизован, ровно один релевантный Casus corpus (`main` / `sip` / `kas` / `kud`) через единые `casuslegal_*` tools, причём corpus должен быть разрешён после живого content-smoke; правила `references/external-legal-databases.md`. Реквизиты акта — после первоисточника (kad.arbitr.ru, сайт ВС). Provider routing — `references/source-profiles/`.
4. **Оценка (CL-2/CL-3/CL-6).** Authority по лестнице A1–B3, отказные исключить (X); ВАС — survival check; аналогия direct vs factual; rule/exception; argumentative value отдельно от authority.
5. **Статус практики (CL-4).** Подсчёт **округов, не решений**; пороги §13 — через `tools/case_law/practice_status.py`. `established=True` означает насыщение однотипной поддержки, а не полноту всего исследования.
6. **Синтез и coverage (CL-7).** Свести акты по issue/proposition, отделить позицию суда от доводов и нашего синтеза, проверить историю, независимость линий, режим права, targeted opposition и конфликты. Для сохраняемого manifest запустить `tools/case_law/research_check.py`.
7. **Развитие, передача или остановка.** Учиться терминологии у найденных актов; сужать только под конкретный пробел. Текущий проход завершать по coverage либо останавливать с видимыми gaps при cap/недоступности (`references/source-hierarchy.md`, «Ограничитель»). Supporting-проход передаёт незакрытый adverse вызывающему workflow, не подменяет его.
8. **Выход.** Отдать `practice_status` + `research_outcome` + `key_cases` + `coverage` + `search_summary` + `warnings` (схема — метод, раздел «Выход»). Реквизиты акта — только после разбора по `court-decision-analysis.md`; неоткрытый первоисточник → `[СВЕРИТЬ С ПЕРВОИСТОЧНИКОМ]`.

При прямом запросе юриста результат — черновик-сводка практики; если дальше нужен документ/заключение, передать выход соответствующему skill.

## Принципы

1. Внешняя база ищет — skill управляет поиском; своего retrieval нет.
2. Не одна строка: facts-first + qualification-first + отдельные альтернативные квалификации; сужать только под дефект выдачи.
3. Authority ≠ похожесть ≠ forum relevance ≠ argumentative value; качество мотивировки authority не повышает.
4. Сохраняющая силу позиция ВАС действует, пока не преодолена; отказные определения — не substantive authority; своя кассация не выше других, но важнее для прогноза.
5. «Сформированная практика» — кандидат-статус по CL-4; полнота текущего прохода, gaps и передача — отдельно по CL-7.
6. Adverse-поиск и верификация первоисточника — отдельные проходы; supporting-поиск явно передаёт им незакрытые проверки.
7. Результат — черновик; ничего не финализировать; не нашли — честный отказ, не выдумка.

## Связанные файлы

- `references/case-law-search.md` — метод (индекс-роутер, цикл, provider routing, stop-rule, выход, антипаттерны).
- `references/case-law-cards/` — CL-1…CL-7 (содержательный слой).
- `tools/case_law/practice_status.py` — классификатор статуса практики (§13–14).
- `tools/case_law/research_check.py`, `tools/case_law/README.md` — read-only проверка пула и coverage одного issue.
- `references/court-decision-analysis.md` — структурный разбор акта.
- `references/source-hierarchy.md`, `references/query-cookbook.md`, `references/source-profiles/`, `references/legal-opinion-subagents.md`, `references/citation-rules.md`.
- `references/external-legal-databases.md` — «Правила КонсультантПлюс» (основной внешний поиск, раньше Casus); единый Casus connector, corpus gate, открытие полного акта, adverse-поиск и запрет массового экспорта.
