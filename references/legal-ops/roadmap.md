# Дорожная карта Legal Ops

Читать этот файл при старте проекта. Карточку фазы открывать только когда `current_phase` совпал. Трек оценки Legal AI — `references/legal-ops/ai-evaluation.md`, не этот файл.

Порядок, который нельзя перескакивать ради инструмента:

`REMOVE → SIMPLIFY → STANDARDISE → AUTOMATE → AI-ENABLE → AGENT`

Технология выбирается последней. Если шаг можно убрать или упростить, автоматизация этого шага не проектируется.

| Фаза | `current_phase` | Когда читать | Выход |
|---|---|---|---|
| ALIGN | `align` | старт или неясна цель | `artifacts/business_alignment.md` |
| DISCOVER | `discover` | цель и shortlist есть | карта работы и As Is |
| REDESIGN | `redesign` | As Is подтверждён | `artifacts/problem_analysis.md` |
| DESIGN | `design` | процесс уже почищен | target model и human control |
| JUSTIFY | `justify` | есть варианты реализации | business case, decision pack, pilot |
| IMPLEMENT | `implement` | решение о пилоте подтверждено | план внедрения и проверка эффекта |

MVP-маршрут: ALIGN → inventory → shortlist → один deep-dive → REDESIGN → задачи → pattern и human control → business case → decision pack → pilot plan.

Фаза закрывается по DONE WHEN своей карточки, а не потому что вопросы заданы.
