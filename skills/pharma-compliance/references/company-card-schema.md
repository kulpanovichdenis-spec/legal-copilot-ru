# Company Compliance Card Schema

A card is an atomic operational rule, not an arbitrary document chunk.

```yaml
card_id: CCK-HCP-TRAVEL-001
company_profile: example

document:
  document_id: POL-HCP-2026
  title: Policy title
  document_type: policy
  version: '2.0'
  status: active
  effective_from: 2026-01-01
  effective_to: null

card_type: approval_requirement

title: Compliance approval before HCP travel commitment
normalized_rule: >
  HCP travel support requires documented Compliance approval before the
  company commits the expense.

scope:
  actors: [hcp]
  activities: [travel, congress_support]
  business_units: []
  jurisdictions: [RU]

conditions: []
exceptions: []
approvals:
  required: true
  role: Compliance
  timing: before_commitment
thresholds: []
documentation:
  - approval_record
escalation: []
owner: Compliance

related_global_domains: [HCP_HCO]
related_patterns: []

source:
  original_path: profile/knowledge/example/hcp/originals/policy.pdf
  section: '4.2'
  page: 7
  locator_text: 'HCP travel support approval'
```

## Card types

`prohibition`, `permission`, `permission_with_conditions`, `mandatory_action`, `approval_requirement`, `escalation_trigger`, `limit_threshold`, `exception`, `role_responsibility`, `process_step`, `documentation_requirement`, `retention_requirement`, `control`, `definition`.
