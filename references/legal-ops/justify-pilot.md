# JUSTIFY и пилот

Читать, когда `current_phase` = `justify`.

## Приоритет

Смотреть ценность (время, цикл, стоимость, риск, эффект для бизнеса), осуществимость (зрелость процесса, данные, знания, интеграции), риск (ошибка, конфиденциальность, privilege, регуляторика, контроль) и масштаб (объём, пользователи, повторяемость).

Не ставить числовые баллы без основания. Допустимые ярлыки, каждый с объяснением: Quick Win, Strategic Bet, Foundation Required, Do Not Automate Yet.

## Business case

Не сводить к «часы × ставка». Арифметика только через `python tools/legal_ops/ops.py capacity` и `python tools/legal_ops/ops.py roi`. Нет чисел — case помечен как гипотеза, скрипт вернёт `missing` и пустые суммы.

## Решение

Для существенного выбора оформить: Problem, Evidence, Assumptions, Alternatives, Recommendation, Expected effect, Cost, Risks, Controls, Reconsideration trigger. В `decisions.md` писать только после подтверждения пользователя командой `python tools/legal_ops/ops.py decide`.

## Пилот

`pilots/<id>.yaml`: scope, users, use_cases, dataset, baseline, success_metrics, failure_criteria, human_review, escalation, duration, owner. Сравнение с фактом — `python tools/legal_ops/ops.py compare`.

## DONE WHEN

Приоритет выбран осознанно, альтернативы названы, case прозрачен, допущения видны, пилот ограничен, критерии успеха и провала заданы, пакет можно защищать.

## Выходы

- `artifacts/business_case.md`
- `decisions.md`
- `pilots/<id>.yaml`
- `outputs/decision_pack.md`

Материал для адресата (executive summary, one-pager, IT, security, procurement, возражения) собирается из evidence, assumptions и decisions этого проекта. Новый тезис без опоры не добавлять. Слайды для руководства — skill `skills/business-communication/SKILL.md`, входом служит decision pack.
