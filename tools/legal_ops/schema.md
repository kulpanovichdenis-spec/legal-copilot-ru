# Legal Ops project state

Единственный источник полей `project_state.yaml`. SKILL.md на эту схему ссылается и не копирует её.

Верхний уровень, и только он:

| Поле | Тип | Смысл |
|---|---|---|
| `schema_version` | int | сейчас `1` |
| `project_name` | str | имя проекта |
| `objective` | str | зачем меняется функция |
| `current_phase` | str | `align` / `discover` / `redesign` / `design` / `justify` / `implement` |
| `track` | str | `transformation` или `ai_evaluation` |
| `completed` | list | id закрытых фаз |
| `active_processes` | list | id процессов |
| `facts` | list | подтверждённые факты, без полного текста документов |
| `assumptions` | list | явные допущения |
| `open_questions` | list | открытые вопросы |
| `decisions` | list | `{id, date, title}` — только после `ops.py decide` |
| `next_actions` | list | ближайшие шаги |
| `blocked_by` | list | что блокирует |
| `artifact_refs` | list | пути относительно папки проекта; файл обязан существовать |
| `related_budget_run` | str | путь к папке бюджетного запуска; цифры бюджета сюда не копируются |
| `last_updated` | date | проставляет `save_state` |

Полные документы в state не копируются.

Карточка процесса (`processes/<id>/process_card.yaml`) обязана содержать ключи:

`process`, `business_goal`, `owner`, `customers`, `trigger`, `inputs`, `outputs`, `volume`, `cycle_time`, `work_time`, `wait_time`, `roles`, `systems`, `data_sources`, `knowledge_sources`, `as_is_steps`, `pain_points`, `handoffs`, `rework`, `approvals`, `baseline_metrics`, `open_questions`.

Метрики `volume`, `cycle_time`, `work_time`, `wait_time` — число или строка `UNKNOWN`. Пустая строка — ошибка.
