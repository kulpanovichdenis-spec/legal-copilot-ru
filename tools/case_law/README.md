# Case-law deterministic checks

`practice_status.py` применяет действующие числовые пороги CL-4 к уже очищенному
входу. `research_check.py` проверяет manifest одного issue, выводит допустимый counted-set,
сверяет вход классификатора и отличает насыщение поддержки от полноты прохода.
Оба инструмента read-only: они не ищут акты, не толкуют право и не меняют human status.

## Manifest `case_law_research.v1`

```yaml
version: case_law_research.v1
issue: {id: I1, text: "проверяемый правовой вопрос"}
proposition: {id: P1, text: "узкий проверяемый тезис"}
purpose: "зачем проводится проход"
pass_role: standalone              # standalone | supporting | adverse
legal_regime:
  description: "редакция/период отношений"
  source_refs: ["source://norm"]
cases:
  - id: C1
    dispute_id: D1                 # все инстанции одного спора имеют один id
    issue_ref: I1
    proposition_ref: P1
    direction: SUPPORT             # SUPPORT | OPPOSE | NEUTRAL
    authority: B1                  # A1/A2/A3/A4/B1/B2/B3/X
    circuit: МО
    opened: true
    history:
      status: CURRENT              # CURRENT | PARTIALLY_REVERSED | REVERSED | UNKNOWN
      source_refs: ["source://case"]
      # Для PARTIALLY_REVERSED обязательны surviving_scope и scope_confirmed: true.
    legal_regime_fit: MATCH        # MATCH | PARTIAL | NO | UNKNOWN
    issue_fit: MATCH
    analogy_mode: DIRECT_LEGAL     # DIRECT_LEGAL | FACTUAL_ARGUMENTATIVE
    attributions:
      - {type: HOLDING, locator: "абзац 12"}
    citation_lineage:
      mode: ORIGINAL               # ORIGINAL | INDEPENDENT_APPLICATION | COPY
      root_ref:
      explanation: "почему это самостоятельное применение или копирование"
synthesis:
  divergences:
    - type: UNEXPLAINED            # FACTUAL | LEGAL | MIXED | TEMPORAL | UNEXPLAINED
      explanation: "почему линии расходятся либо почему причина не установлена"
      case_refs: [C1, C2]
      limitation: "граница вывода при UNEXPLAINED"
coverage:
  checks:
    source_opened: {status: DONE, evidence_refs: ["source://case"]}
    later_history: {status: DONE, evidence_refs: ["source://history"]}
    legal_regime_fit: {status: DONE, evidence_refs: ["source://norm"]}
    issue_fit: {status: DONE, evidence_refs: ["research://card"]}
    adverse_search: {status: DONE, evidence_refs: ["search://adverse"]}
    conflicts_assessed: {status: DONE, evidence_refs: ["research://synthesis"]}
  targeted_opposition:
    status: NOT_FOUND_IN_TARGETED_SEARCH  # FOUND | ... | NOT_SEARCHED
    search_refs: ["search://adverse"]
  unresolved_conflicts: []
  caller_pending: []
  constraints: {cap_reached: false, unavailable: []}
claimed_outcome: READY_FOR_HANDOFF # optional assertion, checked against derived result
```

При `DONE` нужны `evidence_refs`; при `PENDING`/`UNAVAILABLE` — `reason`. После targeted
search нужны `search_refs`. Для `FACTUAL_ARGUMENTATIVE` нужен `reasoning_link`, но такой
акт не входит в substantive set по исследуемой правовой квалификации.

Если в пуле есть и SUPPORT, и OPPOSE, нужен хотя бы один `synthesis.divergences`.
Для `FACTUAL` обязательны `reasoning_refs`, для `TEMPORAL` — `regime_refs`, для
`UNEXPLAINED` — честная `limitation`. Checker проверяет наличие и согласованность полей,
но не решает за юриста, верно ли объяснено расхождение.

Для `COPY` поле `root_ref` обязано ссылаться на `id` корневого акта в этом же manifest;
ссылки разрешаются до канонического корня, отсутствующие корни и циклы дают ошибку.
`INDEPENDENT_APPLICATION` может ссылаться на общий внешний authority и остаётся
самостоятельной линией своего спора. В цепочке инстанций checker выбирает
детерминированный наивысший substantive authority как `counted_authority`, сохраняет
остальные уровни и округа в `independent_units`, но не считает одну линию дважды.

`practice_input` можно передать как проверяемое заявление с полями `a1`, `a2`, `a4`,
`skes`, `circuits_support`, `circuits_oppose`, `decisions_support`. Checker сравнит его
с уникальными допустимыми единицами и не создаст вторую систему порогов.

## Outcomes

- `READY_FOR_HANDOFF` — текущий проход достаточно покрыт для передачи; source
  verification и human gate сохраняются.
- `CONTINUE_TARGETED` — есть конкретная незакрытая проверка и лимит не сработал.
- `STOP_WITH_GAPS` — лимит или недоступность остановили проход; пробелы видны.
- `HANDOFF_REQUIRED` — обязательная проверка принадлежит вызывающему workflow.

Запуск: `python tools/case_law/research_check.py <manifest.yaml>`. Exit 0 означает
структурно согласованный manifest, exit 2 — ошибки контракта. Это не заключение о
полноте всей судебной практики.
