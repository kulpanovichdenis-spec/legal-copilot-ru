---
id: glossa
kind: commercial_provider
jurisdictions: [RU]
capabilities: [legal_doctrine, civil_law, case_practice]
access: mcp
authority_level: secondary_doctrine
adapter: remote_legal_mcp
connection_ref: glossa
protocol_refs:
  - references/external-legal-databases.md
  - references/source-hierarchy.md
fallbacks: [local-legal-ru-sqlite, pravo-gov-ru]
health_probe: tools/list
rate_limits: provider_account_dependent
auth: bearer_access_code
status: auth_required
data_policy: abstracted_issue_only
verification_roles: [navigation, doctrine]
coverage:
  document_types: [civil_law_doctrine, doctrine_points, linked_case_practice]
  full_text: conditional
  historical_versions: no
  current_status: no
  pinpoint: yes
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [doctrine_is_not_source_of_law, legislation_requires_separate_verification]
---

# Glossa

Доктринальный слой по гражданскому праву. Использовать для толкования,
аргументов за/против и навигации к практике; покрытие сначала проверять через
`glossa_stats`. Это не источник права: норму и судебный акт сверять отдельно.
