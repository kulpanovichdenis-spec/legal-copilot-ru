# Content model — `content_model.yaml`

Единый объект, из которого рендерятся PPTX / DOCX / HTML (ТЗ §26). Пишет модель, проверяет и рендерит `tools/business_comm/comm.py`. Словари и дефолты — `tools/business_comm/bc_model.py` (источник истины; переименован из `model.py`, чтобы не конфликтовать с top-level модулем `tools/matter_model/model.py`).

## Верхний уровень

| Ключ | Обязательно | Содержимое |
|---|---|---|
| `project` | да | `title`, `mode` (BRIEFING / REPORT / RECOMMENDATION / TRAINING / CHANGE / INCIDENT), `secondary_mode`, `subtype`, `audience`, `output` (список из pptx / docx / html), `duration_or_length`, `prepared_at` |
| `objective` | да | `business_question`, `desired_outcome`, `desired_behavior`, `required_decision`, `learning_objectives[]` (TRAINING) |
| `minto` | да | `situation`, `complication`, `question`, `answer`, `supporting_arguments[]` |
| `content` | да | смысловые разделы (ниже); каждый — список элементов с уникальным `id` |
| `storyline` | да | `order`, `message`, `content_block`, `visual_hint`, `title_kind` (assertion / title / section / appendix / navigation), `layer` (main / appendix), `evidence_refs[]`, `talk_track` |
| `sources` | да | `id`, `type` (primary_law / court_or_regulator / internal_policy / reported / secondary_reliable / commentary), `title`, `reference`, `primary`, `checked_at`, `url` |
| `change` | CHANGE | `current`, `new`, `effective_date`, `affected_roles[]`, `affected_processes[]`, `owner`, `transition`, `enforcement`, `system_changes` |
| `incident` | INCIDENT | `status`, `next_update`, `decision_makers[]`, `notification_deadlines` |
| `render` | нет | `pptx: {template}`, `docx: {variant: memo / one_pager}` |
| `quality` | нет | `assumptions[]`, `open_questions[]`, `validation_results[]` |

## Разделы `content`

| Раздел | Поля элемента | claim_type по умолчанию |
|---|---|---|
| `business_context` | `text`, `source_refs` | fact |
| `facts` | `text`, `status` (verified / unverified), `source_refs` | fact |
| `timeline` | `date`, `text`, `status`, `source_refs` | fact |
| `legal_rules` | `text`, `detail`, `source_refs`, `calibrated` | legal_rule |
| `interpretations` | `text`, `detail`, `source_refs` | legal_interpretation |
| `cases` | `text`, `why`, `detail`, `source_refs` | fact |
| `internal_examples` | `kind` (case / wrong / better), `text`, `why`, `confidentiality`, `image`, `annotations[]` | fact (для wrong / better — нет) |
| `estimates` | `text`, `method`, `source_refs` | business_estimate |
| `metrics` | `label`, `value`, `unit`, `kind` (outcome / activity), `explains` (id эффекта) | — |
| `impacts` | `type`, `label`, `value`, `unit`, `value_class`, `method`, `source_refs`, `confidence` | — |
| `recommendations` | `text`, `why` | recommendation |
| `options` | `title`, `pros[]`, `cons[]`, `risk`, `recommended`, `fallback` | — |
| `risks` | `text`, `level` | — |
| `actions` / `next_steps` | `what`, `who`, `when`, `stop_condition` | — |
| `escalation_points` | `when`, `contact` | — |
| `triggers` / `checks` | `text` | — |
| `decision_nodes` | `question`, `if_yes`, `if_no` (текст; ключи yes/no в YAML 1.1 превращаются в bool — не использовать) | — |
| `faq` | `q`, `a` | — |

Любой элемент может переопределить `claim_type` (например, `assumption`) и нести `why` / `detail` — они уходят в раскрывающиеся блоки HTML, notes PPTX и приложение DOCX.

## Что проверяет код

`python tools/business_comm/comm.py validate <model>` — коды `S*` (схема), `M*` (Minto), `B*` (бизнес), `L*` (право), `C*` (коммуникация), `P*` (конфиденциальность), `T*` / `R*` / `D*` / `G*` / `I*` / `U*` (режимы TRAINING / REPORT / RECOMMENDATION / CHANGE / INCIDENT / BRIEFING). Любая ошибка блокирует рендер.

Отдельно, уже после рендера, каждый `render_*.inspect_*(path)` проверяет сам готовый файл (PPTX/DOCX/HTML) — коды `X01`–`X05`: `X01` нет метки черновика (`ЧЕРНОВИК — требует проверки юристом`), `X02` мусор шаблона в тексте/notes (`DEBRIS_RE`: click to add, lorem ipsum, todo, tbd, placeholder), `X03` запрещённая формулировка «финальный / готов к показу» (`FINAL_RE`), `X04` у слайда PPTX нет заголовка, `X05` HTML ссылается на внешний ресурс (страница должна быть самодостаточной). `comm.render_all` удаляет с диска файл, на котором сработала любая ошибка `X*`, и не включает его в список созданных.

## `<template>.layouts.yaml` — сайдкар для корпоративного шаблона PPTX

Файл с тем же именем, что и `--template`, но расширением `.layouts.yaml`, лежащий рядом с ним (например, `corporate.pptx` → `corporate.layouts.yaml`). Ключи — роли `title` / `content` / `section`, значения — точные имена layouts шаблона (`slide_layout.name`). Если сайдкара нет — роль подбирается эвристикой по типам плейсхолдеров (`render_pptx._title_layout` / `_content_layout` / `_section_layout`). Имя layout в сайдкаре, которого нет в шаблоне, — `ValueError` при рендере (список доступных имён — в тексте ошибки).
