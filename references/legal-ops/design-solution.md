# DESIGN

Читать, когда `current_phase` = `design`.

## Цель

Разбить очищенный процесс на задачи и выбрать способ исполнения каждой.

Крупная этикетка вроде «проверка договора» — не единица автоматизации. Единица — задача с входом, действием, решением и выходом.

Поля задачи: `task`, `input`, `action`, `decision`, `output`, `owner`, `repeatability`, `rule_clarity`, `judgement_intensity`, `risk`, `reversibility`, `data_readiness`, `knowledge_readiness`, `volume`, `integration_need`, `candidate_pattern`, `human_control`.

Паттерн брать из `references/legal-ops/technology-patterns.md` в том порядке, в каком файл их перечисляет. Уровень контроля — из `references/legal-ops/governance-controls.md`.

Для каждого шага целевой модели указать: человек, автоматизация или AI, система, знание, контроль.

## DONE WHEN

Процесс разложен на задачи; у кандидата на автоматизацию есть паттерн и уровень контроля; видны предпосылки; To Be записан; неизвестное не спрятано.

## Выходы

- `processes/<id>/target_model.md`
- `artifacts/automation_options.md`
