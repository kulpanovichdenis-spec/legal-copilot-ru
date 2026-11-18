# Local Rule Conflict Resolution

## Precedence

External mandatory law prevails over internal policy. Internal policy may be stricter.

## Internal conflicts

Use company-configured document hierarchy only when the conflict can be resolved by explicit governance rules. Otherwise surface `LOCAL_RULE_CONFLICT` and show both sources.

## Absence

- `no_relevant_local_rule_found` — retrieval found nothing.
- `company_has_no_rule` — allowed only when manifest coverage is complete and an explicit conclusion is supported.

## Effective date

Resolve by rule effective on the transaction/event date; current rule is not automatically applicable historically.
