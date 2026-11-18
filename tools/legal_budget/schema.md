# Budget state

Канон полей для `state/*.json`. Skill на этот файл ссылается.

`budget_context.json`: `run_id`, `budget_period.start`, `budget_period.end`, `reporting_currency`, `goal` (`create`, `review`, `cut`, `reforecast`), `industry`, `materiality_threshold`.

`budget_state.json`: `lines[]` с `id`, `category`, `monthly_amounts`, `annual_amount`, `source_refs`, `assumption_refs`, `material`; `actuals[]` и `accruals[]` с `invoice_id`; `history[]` с `tag`; `allocations[]`; `headcount_change`; `external_spend_change`; `workload_transfer`; `bridge`; `scenario_overlay`.

Существенная строка без `source_refs` и без `assumption_refs` — ошибка challenge `missing_provenance`.

Запись JSON — через `save_json`: временный файл, затем замена.
