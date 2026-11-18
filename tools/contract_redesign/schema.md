# Журнал изменений contract-redesign — схема YAML (schema_version 1)

Файл пишет агент (`skills/contract-redesign/SKILL.md`), проверяет и рендерит `tools/contract_redesign/changelog.py`. Хранится рядом с результатом: `workflow/<дело>/changelog.yaml` (рабочий материал агента; юристу — .docx через команду `docx`).

Смысл полей — `references/contract-design.md` раздел 12.

## Общая часть

```yaml
schema_version: 1
mode: legacy_redesign          # legacy_redesign | restatement
title: "Договор поставки — новая редакция на основе шаблона 2019"
sources:
  - id: S1                     # уникальный
    title: "Шаблон договора поставки (2019)"
    role: legacy_template      # legacy_template | prior_contract | counterparty_draft | main_contract | amendment | other
    date: 2019-03-01           # необязательно
    effective_from: 2024-06-01 # для role: amendment — дата вступления в силу; нет — предупреждение [ПРОВЕРИТЬ СРОК]
```

## mode: legacy_redesign — `entries`

Одна запись на каждое значимое положение исходника (включая удаляемые).

```yaml
entries:
  - id: C-001
    source: S1
    location: "п. 4.1.3"                 # где было
    legal_function: "передача документов о качестве вместе с товаром"
    business_function: "склад не принимает партию без паспорта"   # необязательно
    rd_category: A                       # только для пунктов из «Прав и обязанностей»: A | B | C | D; иначе не указывать
    level: A                             # A — структура/подача; B — язык; C — существо
    action: relocate                     # keep | relocate | merge | rewrite | delete
    target: "п. 4.2"                     # где стало; для delete — не указывать
    substantive: false                   # меняет ли юридический смысл
    equivalence_check: n/a               # passed | failed | n/a; для level B обязателен passed/failed
    conflict: false                      # формулировки источников расходятся
    reason: "процесс «Документы на товар»"
    lawyer_decision: not_needed          # not_needed | required | approved | rejected
```

Жёсткие правила (ошибка validate):

- `level: C` ⇒ `substantive: true`;
- `action: delete` + `rd_category: A|D` ⇒ `substantive: true`;
- `level: B` ⇒ `equivalence_check` ≠ `n/a`; `failed` ⇒ `substantive: true`;
- `substantive: true` или `conflict: true` ⇒ `lawyer_decision` ≠ `not_needed`;
- `delete` ⇒ без `target`; прочие действия ⇒ `target` обязателен.

## mode: restatement — `clauses`

Одна запись на пункт консолидированной редакции.

```yaml
clauses:
  - id: R-002
    location: "п. 3.2"                    # пункт в консолидированной редакции
    status: amended                       # original | amended | added | excluded
    history:                              # исходная редакция и все ДС, менявшие пункт, по возрастанию effective_from
      - {source: S0, location: "п. 3.2"}
      - {source: S1, location: "п. 1"}
    conflict: false                       # ДС противоречат друг другу / неясно, какая редакция действует
    lawyer_decision: not_needed
    note: ""
```

Жёсткие правила: `amended | added | excluded` ⇒ в `history` есть ДС (role `amendment`); `conflict: true` ⇒ решение юриста; нужен источник `main_contract`.
Предупреждения: ДС без `effective_from`; ДС, на которое не ссылается ни один пункт; история не по возрастанию дат.
