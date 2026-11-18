# Case studies

Персональный конфиденциальный слой обезличенных карточек прошлых дел.

- `cards/claims/` — претензионные дела без подтверждённой судебной стадии.
- `cards/litigation/` — судебные и объединённые претензионно-судебные дела.

Карточка описывает конкретный спор и сохраняет provenance. Переиспользуемые выводы
из неё создаются отдельно в `profile/knowledge/candidates/` как
`type: practice_pattern`. Ни карточка, ни candidate не являются правовым основанием.

Правила: `references/case-knowledge-layer.md`.
Валидация: `python tools/case_knowledge/case_studies.py profile/knowledge/case-studies/cards`.
