# Company Compliance Knowledge Manifest

Purpose: prevent false assumptions about local coverage.

```yaml
company_profile: example
last_reviewed: 2026-10-06

hierarchy:
  - board_policy
  - corporate_policy
  - regulation
  - sop
  - instruction
  - guidance

coverage:
  - category: HCP_HCO
    loaded: true
    current: candidate
    verified: true
    notes: Current HCP policy set is loaded.
  - category: THIRD_PARTIES
    loaded: true
    current: partial
    verified: true
    notes: Due-diligence and charity rules are loaded; no general third-party SOP.
  - category: DISTRIBUTOR_COMPETITION
    loaded: false
    current: null
    verified: false
    notes: No company source was provided.

conflicts:
  - conflict_id: CONFLICT-HCP-FEE-001
    card_id_a: CCK-HCP-FEE-LEGACY-001
    card_id_b: CCK-HCP-FEE-002
    status: open
    description: Legacy fee table requires a currency decision against the calculator.
```

The hierarchy is configurable per company; never hard-code a universal corporate-document hierarchy.

`coverage` and `conflicts` are lists because the SQLite builder imports each item as
one row. `current` may be `true`, `false`, `null`, or a descriptive review state such
as `candidate` or `partial`; `verified` remains a separate lawyer-review flag.
