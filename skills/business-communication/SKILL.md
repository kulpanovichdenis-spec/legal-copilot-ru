---
name: business-communication
description: Используется, когда юристу нужно донести результат работы Legal до бизнеса — презентация для руководства или правления, обучение сотрудников, отчёт Legal, записка на управленческое решение, коммуникация нового порядка, срочное информирование об инциденте («сделай презентацию для бизнеса», «объясни маркетингу», «подготовь обучение», «отчёт Legal за квартал», «брифинг для CEO»). Готовит content model, storyline и черновики PPTX / DOCX / HTML из одного источника с меткой черновика. Не финализирует и не показывает бизнесу сам. Не используется для правового заключения (legal-opinion), документов в суд, госорган или контрагенту (procedural-document-drafter, gov-response, counterparty-letter) и проверки рекламного креатива (fas-ad-practice-search) — их результаты служат входом.
---

# Business Communication

**Архитектура:** sequential + domain-intelligence, High freedom для суждения (intake, business question, storyline) и Low freedom для механики: content model, валидация и рендер PPTX / DOCX / HTML — код `tools/business_comm/comm.py`. Индекс-роутер к карточкам режимов `references/business-communication-cards/`; методика — `references/business-communication-method.md`; поля — `tools/business_comm/schema.md`. Ничего из этого не дублируется здесь.

## Назначение

Перевести правовое знание и результат работы Legal в продукт, после которого бизнес понимает ситуацию и знает, что решить или сделать: `legal content → business question → business meaning → decision / action / behavior → communication product`.

## Принципы

1. Business first, answer first: главный вывод — в начале; право — обоснование, а не структура (метод §2, §9). Если вывод зависит от неизвестного decisive fact, сначала дать зависимость и ветви по `references/business-legal-writing.md`, а не ложную определённость.
2. Minto + SCQA — обязательный каркас; storyline согласуется до продукта; содержательные заголовки — выводы (метод §2, §5).
3. Спрашивать только недостающее: сначала прочитать материалы, интервью короткими блоками (метод §3).
4. Не выдумывать эффект: у каждой суммы `value_class`; `exposure` — не экономия; activity-метрики не ведут отчёт (метод §7).
5. Правовая часть — из проверенного источника или готового результата профильного skill; тезис без источника — маркер; тип источника назван честно (метод §8, `references/source-hierarchy.md`).
6. Один content model — все форматы; рендер только через `tools/business_comm/comm.py` после валидации без ошибок (метод §6, §14).
7. Черновик для юриста: три чекпоинта, метка «ЧЕРНОВИК», конфиденциальность внутренних кейсов, ничего не показывается бизнесу без юриста (метод §12, §13).

## Когда использовать

- «презентация / слайды для бизнеса, руководства, правления»; «брифинг для CEO»;
- «обучение / тренинг / памятка для сотрудников, маркетинга, закупок»;
- «отчёт Legal», «итоги дела для руководства», «что дал бизнесу проект»;
- «записка на решение», «варианты для руководства», «go / no-go»;
- «новый порядок / политика — как донести», «разослать сотрудникам»;
- «срочно проинформировать руководство» об проверке, иске, инциденте;
- «переведи это заключение / анализ на язык бизнеса».

## Когда не использовать

- Правовой вопрос ещё не исследован и нужен вывод для юриста → `skills/legal-opinion/SKILL.md` (потом его вывод — вход сюда).
- Разбор переданного пакета документов и сборка содержания дайджеста → `skills/legal-digest/SKILL.md`. Если адресат бизнес, он передаёт сюда содержание, источники, условия и пробелы в рамках той же задачи; адаптация, storyline и продукт собираются здесь без повторного запроса материалов. Готовый обзор можно принять напрямую. Содержательные ограничения и статус проверки источников при адаптации сохраняются.
- Документ в суд, госорган, контрагенту → `skills/procedural-document-drafter/SKILL.md`, `skills/gov-response/SKILL.md`, `skills/counterparty-letter/SKILL.md`.
- Проверка рекламного материала → `skills/fas-ad-practice-search/SKILL.md`.
- Короткий ответ бизнесу в чате без продукта — отвечать напрямую по `references/house-style.md`.

## Классификация (индекс-роутер)

Определить основной режим (и вторичный при смешанной задаче), назвать юристу одной строкой, открыть **только** сработавшие карточки.

| Смысл | Режим | Карточка |
|---|---|---|
| что произошло / изменилось | BRIEFING | `references/business-communication-cards/01-briefing.md` |
| что сделали / какой результат | REPORT | `references/business-communication-cards/02-report.md` |
| что выбрать / решить | RECOMMENDATION | `references/business-communication-cards/03-recommendation.md` |
| чему научить | TRAINING | `references/business-communication-cards/04-training.md` + `references/business-communication-cards/07-training-patterns.md` |
| что теперь делать иначе | CHANGE | `references/business-communication-cards/05-change.md` |
| что делать прямо сейчас | INCIDENT | `references/business-communication-cards/06-incident.md` |

Аудитория — не режим: всегда `references/business-communication-cards/08-audience.md`.

Режимы этой таблицы описывают **содержание коммуникационного продукта** и не подставляются в
поле `business_writing.v1.mode`. Общий writing-check применяется только когда конкретный
reader-facing выход естественно соответствует его жанру:

- письмо/рассылка → `BUSINESS_EMAIL`;
- записка на решение руководству → `BOARD_NOTE`;
- информационная записка/briefing/digest → `LEGAL_DIGEST`;
- risk note → `RISK_NOTE`;
- короткий ответ → `SHORT_ANSWER`.

Для PPTX, TRAINING, CHANGE, INCIDENT и иного продукта без точного соответствия режим не
выдумывать: использовать `comm.py validate`, чекпоинты и смысловой checklist
`references/business-legal-writing.md`; `business_writing.v1` запускать для сопутствующего
handout/email/note, если такой файл действительно создаётся.

## Алгоритм

**Шаг 0 — Контекст.** Прочитать переданные материалы (`references/document-ingestion.md`), `profile/INDEX.md`, `case-context.md` дела при наличии; проверить прошлый опыт по `workflow/` послойно (CLAUDE.md, «Контекст дела»). Извлечь аудиторию, тему, цифры, реальные примеры, источники, пробелы. Если правовой базы нет и она нужна — сначала результат профильного skill или обычный цикл по базам.

**Шаг 1 — Режим.** По таблице выше; одна строка юристу: «Режим: TRAINING (+ CHANGE), аудитория: …».

**Шаг 2 — Adaptive intake.** Core intake (метод §3) + intake режима из карточки; только недостающее, блоками по 2–4 вопроса; `required` отдельно от `nice to have`.

**Шаг 3 — Business question и SCQA.** Сформулировать `business_question`, `minto.situation / complication / question / answer` и поддерживающие аргументы. Записать черновой `content_model.yaml` в папку пакета (метод §16). **Чекпоинт 1:** `python tools/business_comm/comm.py checkpoint 1 <model>` — показать юристу, дождаться согласия.

**Шаг 4 — Storyline.** По карточке режима и аудитории выстроить `storyline` с `content_block`, `visual_hint`, `evidence_refs`; storyline test (метод §5). **Чекпоинт 2:** `comm.py checkpoint 2 <model>`.

**Шаг 5 — Наполнение и источники.** Заполнить `content` и `sources`: факты и нормы — с источниками (метод §8); эффект — с `value_class` и методом (метод §7); внутренние кейсы — с подтверждённым `confidentiality` (метод §12). Existence-check ссылок на ФЗ / ФКЗ / кодексы — `references/source-hierarchy.md`, шаг 6. Нет опоры — маркер из `references/citation-rules.md` вплотную к реквизиту.

**Шаг 6 — Валидация.** `python tools/business_comm/comm.py validate <model>` — исправить все ошибки в модели (не ослаблять правило); предупреждения разобрать; пройти смысловые проверки метода §14. Для выхода, который точно соответствует одному из writing-жанров выше, заполнить `business_writing.v1` и запустить `python tools/business_writing/final_check.py <manifest.json>`: decisive gaps, uncertainty, ownership, risk chains и фактический lawyer trace должны пройти до рендера. Для PPTX/TRAINING без такого соответствия полный manifest не имитировать; применить смысловой checklist вручную и зафиксировать `not_applicable` с причиной. Результат кратко записать в `quality.validation_results`. Checker не подтверждает право, факты или рекомендацию.

**Шаг 7 — Чекпоинт 3 и рендер.** `comm.py checkpoint 3 <model>` → после согласия `python tools/business_comm/comm.py render <model> --out-dir <папка пакета>` (если у пользователя есть корпоративный шаблон `profile/templates/business-communication/corporate.pptx` — добавить `--template` с этим путём) и `comm.py write-support <model> --out-dir <папка пакета>`. Для небольших задач чекпоинты 1–3 объединяются в один показ. Если рядом с шаблоном лежит сайдкар `<template>.layouts.yaml` (ключи `title` / `content` / `section` = точные имена layouts шаблона), `render_pptx` берёт роли layouts из него вместо эвристики; неизвестное в сайдкаре имя layout — ошибка (`tools/business_comm/schema.md`).

**Шаг 8 — Проверка и отчёт.** Открыть результат (для PPTX — растр слайдов, для DOCX — извлечённый текст) и сверить с storyline и `references/business-legal-writing.md`. В бизнес-копии служебный marker преобразован в понятную развилку, допущение, вопрос или source-status note; в `sources.md`/support-файле исходный marker и trace сохранены. Перечислить юристу файлы, маркеры и открытые допущения; обновить `case-context.md`, если есть дело.

## Куда сохранять

`workflow/<подпапка>/<YYYY-MM-DD>_<slug>/` — `content_model.yaml`, `storyline.md`, `sources.md` (технические) и `.pptx` / `_handout.docx` / `.html` (для юриста). PPTX и HTML — утверждённое исключение из правила «.docx для человека» (CLAUDE.md, «Формат результата»). В worktree-сессии — основной `workflow/` по абсолютному пути.

## Что запрещено

- Придумывать факты, суммы, эффект, вероятность риска, нормы, практику, реальные примеры.
- Подавать `exposure` или `estimated` как экономию; вести отчёт activity-метриками.
- Строить основную часть как пересказ закона; прятать вывод в конце; ставить темы вместо выводов.
- Создавать PPTX / DOCX / HTML в обход `tools/business_comm/comm.py` или при ошибках валидации.
- Показывать внутренние кейсы без подтверждённого статуса конфиденциальности; публиковать HTML как Artifact.
- Маркировать результат «финальным / готовым к показу».

## Связанные файлы

- `references/business-communication-method.md` — методика (единственный содержательный источник).
- `references/business-legal-writing.md` — общий reader-facing метод: answer-first, uncertainty, action ownership, risk communication и mode-specific final check.
- `references/business-communication-cards/` — 6 режимов, шаблоны обучения, аудитория.
- `tools/business_comm/schema.md` — content model; `tools/business_comm/comm.py` — проверка и рендер.
- `tools/business_writing/README.md` — границы `business_writing.v1` и read-only final checker.
- `references/source-hierarchy.md`, `references/citation-rules.md` — источники и маркеры.
- `references/house-style.md` — стиль для бизнеса; `references/anonymization-procedure.md` — обезличивание примеров.
