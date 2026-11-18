# Спецификации артефактов

Каждый существенный вывод помечать одним статусом: `FACT`, `ASSUMPTION`, `INFERENCE`, `OPTION`, `RECOMMENDATION`, `DECISION`, `OPEN QUESTION`, `UNKNOWN`.

`DECISION` в тексте артефакта допустим только если id уже есть в `decisions.md`.

След доказательства, если вывод влияет на выбор:

```yaml
evidence_id:
source:
date:
owner:
observation:
reliability:
supports:
```

Мнение одного человека так и называть. Не повышать его до FACT без проверки, если от него зависит решение.

Имена файлов и минимум содержания:

| Файл | Минимум |
|---|---|
| `artifacts/business_alignment.md` | цели, touchpoints, боли, результаты, границы риска, shortlist, open questions |
| `artifacts/work_inventory.md` | категории работы и что по ним UNKNOWN |
| `processes/<id>/process_card.yaml` | поля из `tools/legal_ops/schema.md` |
| `processes/<id>/as_is.md` | шаги, роли, согласования, baseline или UNKNOWN |
| `artifacts/problem_analysis.md` | узкое место, причина, что убрать, что упростить, что стандартизировать |
| `processes/<id>/target_model.md` | задача, паттерн, уровень контроля |
| `artifacts/automation_options.md` | варианты и почему отложены более сложные |
| `artifacts/business_case.md` | откуда цифры; пустые поля скрипта не заполнять |
| `outputs/decision_pack.md` | problem, evidence, alternatives, recommendation, risks, controls |
| `pilots/<id>.yaml` | scope и критерии успеха и провала |
| `artifacts/implementation_plan.md` | владелец, роли, запасной путь |
| `artifacts/metrics.md` | baseline и факт через compare |
| `artifacts/post_implementation_review.md` | отклонения и следующие действия |

Артефакты трека оценки AI перечислены в `references/legal-ops/ai-evaluation.md`.
