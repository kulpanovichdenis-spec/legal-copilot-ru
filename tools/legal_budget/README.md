# Legal budget

Повторить учебный прогон:

```text
python tools/legal_budget/budget.py demo
python tools/legal_budget/budget.py reforecast-demo
```

Без `--folder` оба прогона пишут во временный каталог и не трогают `fixtures/`. Закоммиченные примеры остаются в `fixtures/demo_run/` и `fixtures/reforecast_run/`. Данные синтетические. Это не бюджет организации.

Новый боевой запуск создаётся в `workflow/`, не в этой папке:

```text
python tools/legal_budget/budget.py init --folder "workflow/<папка>" --run-id "<id>" --goal create
python tools/legal_budget/budget.py challenge --folder "workflow/<папка>"
python tools/legal_budget/budget.py cut --folder "workflow/<папка>" --percent 15
python tools/legal_budget/budget.py make-vs-buy --external 100 --salary 100
python tools/legal_budget/budget.py render --folder "workflow/<папка>"
python tools/legal_budget/budget.py gate --folder "workflow/<папка>"
```

`gate` всегда возвращает `ready_for_submission: false`. `cut` не масштабирует строки. `make-vs-buy` не решает нанимать.
