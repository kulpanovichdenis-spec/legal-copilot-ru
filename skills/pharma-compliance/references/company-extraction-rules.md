# Extraction Rules for Internal Acts

## Functional objective

Transform internal acts into operational rules that can answer: may I do this, under what conditions, who approves, what limit/exception/documentation applies and what happens on failure.

## Do not

- split mechanically by paragraph size;
- create only `prohibition` cards;
- lose exceptions or cross-references;
- merge unrelated rules into one card;
- invent missing approval roles/thresholds;
- silently resolve contradictions.

## Extract

For each operative provision identify:

`RULE`, `CONDITIONS`, `EXCEPTIONS`, `THRESHOLDS`, `APPROVALS`, `DOCUMENTATION`, `ESCALATION`, `OWNER`, `EFFECTIVE DATES`, `SOURCE LOCATOR`.

Create multiple cards from one clause when it contains functionally different rules.

## Mapping

Map each card to Global taxonomy: domains, activities, actor roles, benefits, decision types and risk dimensions where supported.

## Versioning

New version creates new cards. Old cards become `superseded`; do not delete. For historical questions retrieve rules effective on the relevant date.

## Diff

On a new version report at least: new rules, removed rules, changed thresholds, changed approvals, changed exceptions and changed responsible roles.
