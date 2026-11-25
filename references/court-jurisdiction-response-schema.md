# Court Jurisdiction Resolver — формат вывода

Единственный источник форматов человекочитаемого и машиночитаемого результата `court-jurisdiction-resolver`. По образцу `references/clause-review-response-schema.md`.

## 1. Definition of Done одного запуска (ТЗ §110)

Статус `CONFIRMED` — только если одновременно выполнены все четыре блока:

```
LEGAL CHECK       — судебная система; процессуальный режим; родовая подсудность; territorial rule; jurisdiction anchor
COURT CHECK       — конкретный суд; официальный источник; территория; адрес
STATE DUTY CHECK  — вид обращения; расчётная база; льготы; сумма либо освобождение
PAYMENT CHECK     — официальный источник; реквизиты; verification URL; timestamp
```

Не хватает провенанса хотя бы на один из вопросов «Почему этот суд? Откуда этот адрес? Откуда эти реквизиты? По какой норме рассчитана пошлина? Когда проверено?» (ТЗ §101) — `CONFIRMED` не ставится.

## 2. Human-readable вывод

```markdown
# Определение суда

## 1. Результат
Процессуальный режим: [АПК / ГПК / КАС]
Суд: [полное наименование или "требуется выбор истца — см. раздел 3а"]
Статус: [CONFIRMED / LEGAL_CONFIRMED_OPERATIONAL_UNVERIFIED / AMBIGUOUS / INSUFFICIENT_DATA / MANUAL_REVIEW_REQUIRED / BLOCKED]

## 2. Почему этот суд
Компетенция: [норма + вывод]
Родовая подсудность: [норма + вывод]
Территориальная подсудность: [применённое правило + приоритет P0-P9]
Jurisdiction anchor: [тип + значение + источник]

## 3. Конкретный суд
Полное наименование: ...
Официальный сайт: ...
Адрес: ...
Территориальная подсудность подтверждена: [да/нет + как]
Официальный источник: [ссылка]
Проверено: ДД.ММ.ГГГГ ЧЧ:ММ

## 4. Государственная пошлина
Статус: [PAYABLE / EXEMPT / PARTIALLY_EXEMPT / CANNOT_CALCULATE / MANUAL_REVIEW_REQUIRED]
Вид требования: ...
Цена иска: ...
Формула: ...
Расчёт: ...
Итого: ... руб.
Нормативное основание: ...

## 5. Реквизиты
[поля payment_details — см. court-online-resolver.md §5.1; если status ≠ PAYABLE/PARTIALLY_EXEMPT, раздел заменяется на "Оплата не требуется" со ссылкой на льготу]

## 6. Обязательная перепроверка
Официальная страница реквизитов: [ссылка]
Данные проверены: ДД.ММ.ГГГГ ЧЧ:ММ

## 7. Предупреждения
[WARNING по процессуальной форме (§6 playbook), расхождение адресов, конфликт источников, live-recon и т. п. — или "нет"]
```

### 2.1. Альтернативная подсудность (ТЗ §91)

Когда допустимо несколько судов — не одна секция «Суд», а:

```markdown
## Доступные варианты

### Вариант A
Основание: [норма]
Суд: [наименование / "определяется online по адресу X"]

### Вариант B
Основание: [норма]
Суд: ...

Выбор между указанными судами принадлежит истцу. Автоматический приоритет одному варианту не присваивался.
```

`recommended_court: null` всегда, если закон даёт выбор — skill отвечает «какие суды допустимы», не «какой лучше» (это отдельный workflow, не в scope).

## 3. Structured Output (JSON)

```json
{
  "status": "CONFIRMED",
  "procedural_form": "lawsuit",
  "procedural_regime": "APK",
  "court_system": "arbitration",
  "court_level": "arbitration_court_of_subject",

  "jurisdiction": {
    "type": "general",
    "selection_required": false,
    "priority_applied": "P9",
    "legal_basis": [
      {"act": "АПК РФ", "article": "27"},
      {"act": "АПК РФ", "article": "34"},
      {"act": "АПК РФ", "article": "35"}
    ]
  },

  "jurisdiction_anchor": {
    "type": "defendant_registered_address",
    "raw_value": "...",
    "normalized_value": "...",
    "source": "registry"
  },

  "court": {
    "name": "...",
    "official_url": "...",
    "address": "...",
    "territorial_verification_url": "...",
    "verified_at": "..."
  },

  "state_duty": {
    "status": "PAYABLE",
    "claim_amount": 7000000,
    "calculation_rule_id": "NK_333_21_PROPERTY_2024",
    "amount": 0,
    "legal_basis": [],
    "calculated_at": "..."
  },

  "payment_details": {
    "recipient_name": "...", "recipient_inn": "...", "recipient_kpp": "...",
    "bank_name": "...", "bik": "...",
    "beneficiary_account": "...", "treasury_account": "...",
    "kbk": "...", "oktmo": "...",
    "source_url": "...", "verified_at": "..."
  },

  "legal_status": "CONFIRMED",
  "court_status": "CONFIRMED",
  "territorial_status": "CONFIRMED",
  "state_duty_status": "PAYABLE",
  "payment_status": "CONFIRMED",

  "warnings": []
}
```

**Ошибка одного модуля не загрязняет другой (ТЗ §112)** — статусы `legal_status`/`court_status`/`territorial_status`/`state_duty_status`/`payment_status` хранятся раздельно. `payment_status: FAILED` не превращает `court_status` в `FAILED`.

### 3.1. Несколько судов — `court_options` (ТЗ §93)

```json
{
  "status": "CONFIRMED",
  "selection_required": true,
  "court_options": [
    {"basis": "по адресу ответчика — ст. 28 ГПК РФ", "court": {"...": "..."}},
    {"basis": "по месту жительства истца-потребителя — ст. 17 Закона о защите прав потребителей", "court": {"...": "..."}}
  ]
}
```

Не упаковывать несколько допустимых судов в один объект `court`.

## 4. Fail-safe (ТЗ §111)

Если нормативная часть отработала, а online resolver — нет, юридический результат **не теряется**:

```
Юридический вывод: Арбитражный суд Московской области.
Основание: [норма]
Operational verification: FAILED.
Адрес и платёжные реквизиты автоматически не подтверждены.
Не использовать непроверенные реквизиты для оплаты.
```

Structured output: `legal_status: "CONFIRMED"`, `court_status`/`payment_status: "FAILED"`, общий `status: "LEGAL_CONFIRMED_OPERATIONAL_UNVERIFIED"`.

## 5. Anti-Hallucination Policy (ТЗ §89) — итоговый чек-лист перед выдачей

Запрещено: придумывать суд или номер судебного участка; угадывать территорию по названию улицы без номера дома; генерировать URL суда и считать его проверенным; выдавать реквизиты из памяти модели; копировать реквизиты другого суда; заменять официальный источник поисковой выдачей; молча выбирать один суд при альтернативной подсудности; игнорировать jurisdiction/arbitration clause; путать государственный арбитражный суд и третейское разбирательство; считать любой IP-спор подсудным СИП; считать любой спор с госорганом административным по КАС; считать любой спор ООО-ООО арбитражным без анализа предмета; определять мирового судью только по цене иска; считать cache источником истины; рассчитывать пошлину по ставкам без проверки версии правила (`effective_from`/`effective_to`).

## 6. Reason Codes (ТЗ §99)

Для audit trail и последующей аналитики — фиксировать применённый код, не свободный текст:

```
ARBITRATION_ECONOMIC_DISPUTE · GENERAL_JURISDICTION_PRIVATE_LAW · KAS_PUBLIC_POWER
MAGISTRATE_PROPERTY_THRESHOLD · DISTRICT_RESIDUAL
EXCLUSIVE_REAL_ESTATE · CONTRACTUAL_JURISDICTION · ALTERNATIVE_CONSUMER
FOREIGN_ELEMENT · ARBITRATION_CLAUSE
COURT_OFFICIAL_CONFIRMED · TERRITORY_OFFICIAL_CONFIRMED
DUTY_EXEMPT · DUTY_PROGRESSIVE_RATE · DUTY_OFFICIAL_DETAILS_CONFIRMED
OFFICIAL_SOURCE_CONFLICT · MISSING_MATERIAL_FACT
```

## 7. Audit Trail (ТЗ §97-98)

Хранить факт → норму → результат применения → источник — **не** свободное рассуждение модели:

```yaml
rule: {id: GPK_30_1, matched: true}
fact: {property_location: "..."}
effect: {jurisdiction_type: exclusive}
```

Для этого skill audit trail — часть заметки юристу в конце ответа (какие правила/карточки сработали, какие факты использованы, какие отклонены как недостаточные), не отдельный файл — если юрист впоследствии попросит персистентный журнал по конкретному делу, использовать `workflow/<дело>/_llm/case-context.md` (раздел «Стратегические решения»/хронология), не создавать новый механизм.

## Связанные файлы

- `references/court-jurisdiction-playbook.md` — откуда берутся `procedural_regime`/`jurisdiction`/`priority_applied`.
- `references/court-online-resolver.md` — откуда берутся `court`/`payment_details`.
- `tools/court_jurisdiction/schema.md` — контракт калькулятора госпошлины (`state_duty`).
- `references/clause-review-response-schema.md` — образец структуры для другого skill (JSON-контракт).
