# DISCOVER

Читать, когда `current_phase` = `discover`.

## Цель

Понять, какую работу делает Legal и как выбранный процесс идёт сейчас.

## Карта работы

Категории, которые встречаются чаще всего: договоры, консультации, споры, корпоративное, регуляторика, compliance. Список не закрытый. По категории, если известно: объём, частота, трудозатраты, ожидание, сложность, важность для бизнеса, риск, повторяемость, системы, готовность данных и знаний. Нет цифры — `UNKNOWN`, не оценка «на глаз».

## Метод

Минимально достаточный метод из `references/legal-ops/methods-registry.md`. Не поднимать BPMN (Business Process Model and Notation), если хватает SIPOC (Suppliers, Inputs, Process, Outputs, Customers).

## Карточка процесса

Поля и правило `UNKNOWN` — `tools/legal_ops/schema.md`. Проверка: `python tools/legal_ops/ops.py validate --folder <папка> --card <process_card.yaml>`.

## DONE WHEN

Известны trigger, inputs, outputs; видны роли, handoffs и approvals; шаги подтверждены; baseline есть или явно `UNKNOWN`; противоречия вынесены в open questions.

## Выходы

- `artifacts/work_inventory.md`
- `processes/<id>/process_card.yaml`
- `processes/<id>/as_is.md`
