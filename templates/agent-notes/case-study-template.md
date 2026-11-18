---
schema_version: 2
case_study_id: cs_<dispute_type>_<год>_<буква>      # только [a-z0-9_], начинать с cs_
matter_kind: <из vocab/matter_kind.json>
jurisdiction: RU
dispute_type: <из vocab/dispute_type.json>
our_role: <из vocab/our_role.json>
stages: [<pretrial|first_instance|appeal|cassation|enforcement|settlement>]
matter_stage: <из vocab/matter_stage.json>
outcome:
  merits_result: unknown
  appeal_status: unknown
  settlement_status: unknown
  enforcement_status: unknown
  recovery_status: unknown
  outcome_evidence: []
evidence_chain_completeness: unknown
law_as_of: unknown
requires_current_law_check: true
topics: []
court_case_numbers: []
related_workflow: []
source_case_ids: []
source_refs:
  - source_id: <CASE_005 / C-035 / EMP-001>
    source_type: <analytical_case_card|cross_case_review|matter_analysis|...>
    source_path: workflow/<папка импорта>/_sources/<корпус>/<файл>.md
    sha256: <из manifest.json>
anonymization: verified
review_status: candidate
knowledge_candidate_ids: []
updated: <YYYY-MM-DD>
---

## 1. Контекст и роли
<2–4 предложения. Только роли: «Покупатель (наша сторона)», «Поставщик». Без наименований, ФИО, ИНН.>

## 2. Фактический паттерн и хронология
<5–12 строк «дата (или период) — событие — [SOURCE|COURT|PARTY POSITION] — locator из разбора». Даты можно оставлять; суммы — только если нужны для паттерна и без реквизитов.>

## 3. Позиции сторон как заявлены
<Наша сторона: … Оппонент: … Только то, что в разборе помечено PARTY POSITION.>

## 4. Доказательственная модель
<Что подтверждало ключевые факты; чего не хватало (из раздела разбора «Missing Critical Sources» / «главный пробел»).>

## 5. Результат раздельно
- По существу: <…> [COURT|SOURCE|unknown]
- Обжалование: <…>
- Урегулирование: <…>
- Исполнение и фактическое взыскание: <…>

## 6. Что сработало / что не подтверждено / чего не хватило
- Сработало: <…>
- Не подтверждено (нельзя выдавать за правило): <…>
- Не хватило: <…>

## 7. Кандидаты в приёмы
<Список ko_… из Шага 7 с одной строкой каждый. До Шага 7 — «заполняется на Шаге 7».>

## 8. Границы вывода и вопросы ревью
<Перенести из разбора блоки «Ограничения», «Human decisions needed», «Priority of manual review» — только относящиеся к этому делу.>

## 9. Provenance
<Повторить source_refs словами: какой разбор, какие разделы, дата разбора. Фраза: «Разбор — вторичный аналитический источник; исходники дела не перечитывались.»>
