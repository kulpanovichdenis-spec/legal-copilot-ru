---
name: court-jurisdiction-resolver
description: Используется для определения компетентного суда первой инстанции по спору РФ (арбитраж/СОЮ/КАС, родовая и территориальная подсудность), online-подтверждения конкретного суда/адреса/реквизитов и расчёта госпошлины перед иском, административным иском или заявлением — когда юрист спрашивает «в какой суд подавать», «куда подсудно», «сколько пошлины», «реквизиты для оплаты», либо перед составлением искового/административного заявления. Результат — вывод о суде + расчёт пошлины + реквизиты, черновик для юриста. Не для апелляции/кассации, составления самого иска (procedural-document-drafter) или сроков давности.
---

# Court Jurisdiction Resolver

Архитектурный паттерн: **domain-intelligence (нормативная классификация) + Low-freedom (расчёт пошлины) + context-aware online-first (подтверждение конкретного суда/адреса/реквизитов)**. Модель классифицирует спор и оговорки; `tools/court_jurisdiction/state_duty.py` считает сумму пошлины; конкретный суд/адрес/реквизиты подтверждаются online, не по памяти модели.

## Назначение

По фактам спора построить воспроизводимую цепочку: факты → компетенция → процессуальный режим → родовая подсудность → территориальная подсудность → jurisdiction anchor → конкретный суд (online) → госпошлина → реквизиты (online) → итог с явным статусом и источниками на каждом шаге. Полная нормативная и online-логика, 16 карточек спецкомпетенции, форматы вывода — в связанных reference-файлах ниже; этот SKILL.md — только оркестрация и принципы.

## Принципы

1. **Не начинать с общего знания модели.** Каждый шаг pipeline опирается на `references/court-jurisdiction-playbook.md` (нормативная часть) и `references/court-online-resolver.md` (online-часть), а не на «примерно известную» норму или адрес суда. Общее знание — обвязка, не замена базе/официальному источнику.
2. **Четыре разных утверждения не смешиваются** (ТЗ §121): «спор относится к этой системе судов» ≠ «компетентен суд такого уровня на такой территории» ≠ «эту территорию сейчас обслуживает такой-то суд» ≠ «сейчас опубликованы такие-то реквизиты». Первые два — нормативные; последние два — динамические, требуют online-подтверждения даже из валидного по TTL cache.
3. **Не восполнять недостающий факт молча.** Не хватает jurisdiction-material факта (адрес ответчика с номером дома, природа правоотношения, цена иска, наличие оговорки) → `INSUFFICIENT_DATA` с явным перечнем `missing`, не «наиболее вероятный» суд. Правильный отказ — не брак (Fact Sufficiency Gate, playbook §2).
4. **Госпошлина считается кодом, не арифметикой модели.** Любая сумма — только через `tools/court_jurisdiction/state_duty.py`. Модель определяет `regime`/`claim_type`/льготы и передаёт их в калькулятор; сама не складывает проценты.
5. **Альтернативная подсудность — все варианты, не один.** Закон даёт истцу выбор → возвращать все юридически допустимые суды (`recommended_court: null`), не выбирать «более удобный» — это отдельный workflow вне scope.
6. **CONFIRMED — только по Definition of Done.** Все четыре блока (LEGAL / COURT / STATE DUTY / PAYMENT — `references/court-jurisdiction-response-schema.md` §1) выполнены одновременно; иначе — `LEGAL_CONFIRMED_OPERATIONAL_UNVERIFIED`/`AMBIGUOUS`/`MANUAL_REVIEW_REQUIRED` и т. п., не натянутый `CONFIRMED`.
7. **Human review.** Результат — черновик для проверки юристом перед подачей. Не маркировать как «готово к подаче», не подавать и не оплачивать самостоятельно.

## Порядок работы

1. **Fact extraction + provenance** — собрать модель дела (стороны, предмет, сумма, адреса, оговорки, спецпризнаки) по `references/court-jurisdiction-playbook.md` §2; каждый существенный факт — с источником (`user`/`document`/`registry`/`inferred`).
2. **Fact Sufficiency Gate** — playbook §2. Не хватает material fact → `INSUFFICIENT_DATA`, дальше не идти.
3. **Procedural Form Gate** — playbook §3. Признаки приказного/особого/третейского/банкротного производства → WARNING, продолжить определение суда для избранной формы.
4. **Foreign Element Gate** — playbook §4. Иностранный элемент → сначала международная компетенция (карточки `foreign_parties`, `sanctions`), только потом территория внутри РФ.
5. **Court System Router + Procedural Regime** — playbook §5, без упрощённой логики по статусу сторон.
6. **Special Competence** — playbook §6, таблица триггеров → открыть только сработавшие карточки из `references/court-jurisdiction-cards/` (обычно 1-3 из 16).
7. **Родовая подсудность** — playbook §7 (отдельные цепочки для ГПК/КАС/АПК).
8. **Территориальная подсудность** — priority engine P0-P9, playbook §8-9; jurisdiction anchor + нормализация адреса — playbook §10.
9. **Online Court Resolver** — `references/court-online-resolver.md`: конкретный суд, официальный сайт, адрес, территориальная верификация. Cache ускоряет, не заменяет online-подтверждение критических полей.
10. **State Duty** — вызвать `tools/court_jurisdiction/state_duty.py calculate` (или `calculate_multiple` для нескольких требований) с `regime`/`claim_type`/льготами, определёнными на предыдущих шагах. Читать `tools/court_jurisdiction/schema.md` за контрактом и известными пробелами калькулятора.
11. **Payment Details** — `references/court-online-resolver.md` §5, только online, никогда из памяти модели.
12. **Итог** — собрать ответ по `references/court-jurisdiction-response-schema.md` (human-readable + structured JSON), со статусом по Definition of Done и явными предупреждениями.

## Что запрещено

Полный anti-hallucination чек-лист — `references/court-jurisdiction-response-schema.md` §5. Ключевое: не придумывать суд/участок/URL/реквизиты; не путать государственный арбитражный суд и третейское разбирательство; не считать любой IP-спор подсудным СИП, любой спор с госорганом — КАС, любой спор ООО-ООО — арбитражным без анализа предмета; не определять мирового судью только по цене иска; не считать cache источником истины; не рассчитывать пошлину без проверки версии правила; не выбирать молча один суд при альтернативной подсудности.

## Куда сохранять результат

Если по делу есть папка `workflow/<дело>/` — ответ (аналитическая заметка + при необходимости .docx-резюме для юриста) сохраняется туда, `case-context.md` обновляется по общему правилу CLAUDE.md. Разовый запрос без открытого дела — результат в чат, `.docx` в `workflow/` только по просьбе юриста (сборка — `references/docx-generation.md`, оформление — `references/document-formatting.md`).

## Связанные файлы

- `references/court-jurisdiction-playbook.md` — нормативный resolver: gates, court system router, родовая/территориальная подсудность, priority engine, confidence model.
- `references/court-jurisdiction-cards/` — 16 карточек спецкомпетенции (corporate, bankruptcy, ip, real_estate, consumer, labor, family, inheritance, military, public_law, foreign_parties, sanctions, arbitration_agreements, multiple_defendants, connected_claims, branches).
- `references/court-online-resolver.md` — online-resolver суда, адреса, реквизитов; Tier-иерархия источников; cache policy; известные пробелы (live-recon форм).
- `tools/court_jurisdiction/` — калькулятор госпошлины (`state_duty.py`, versioned rules, `schema.md`).
- `references/court-jurisdiction-response-schema.md` — форматы вывода, Definition of Done, reason codes, anti-hallucination policy.
- `references/procedural-playbook.md`, `skills/procedural-document-drafter/SKILL.md` — составление самого иска/заявления после того, как суд определён (чек-лист перед подачей уже требует «госпошлина рассчитана» — источник расчёта теперь этот skill).
- `references/web-research-tools.md`, `references/agent-browser-cheatsheet.md` — общий инструментальный слой для online-части.
- `references/citation-rules.md`, `references/source-hierarchy.md` — маркеры неполноты и иерархия источников, общие для проекта.
- `templates/agent-notes/case-context-template.md` — контекст дела в `workflow/<дело>/`.

## История

