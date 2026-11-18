# Retrieval Rules

## Query construction

Search by factual structure:

- actors;
- context;
- activity;
- benefit/value;
- decision potentially influenced;
- route to market;
- evidence/chronology;
- risk dimension.

Do not rely only on statute names or user wording.

## Order

1. Exact structured filters if facts are clear.
2. FTS for rules/patterns/cases/controls.
3. Expand via linked patterns and controls.
4. Query Company Compliance Knowledge.
5. Retrieve source references for verification.

## Company Compliance Knowledge

When active, search for prohibition, permission, conditions, approvals, thresholds, exceptions, documentation and escalation. A zero-result search is reported as `no_relevant_local_rule_found`, not `no_company_rule`.

## Vector search

Not part of MVP. Add only after eval demonstrates material recall improvement over structured + FTS retrieval.
