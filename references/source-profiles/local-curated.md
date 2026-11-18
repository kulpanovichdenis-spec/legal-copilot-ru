---
id: local-curated
kind: internal_curated
jurisdictions: [RU, UZ, KZ]
capabilities: [local_playbooks, playbook_cards, methodology]
access: local_files
authority_level: internal_methodology
adapter: local_curated
connection_ref: local-curated
protocol_refs:
  - references/source-hierarchy.md
  - references/ad-creative-playbook.md
  - references/contract-playbook.md
  - references/procedural-playbook.md
fallbacks: []
health_probe: local_allowlist
rate_limits: null
auth: null
status: active
data_policy: local_only
verification_roles: [navigation, methodology]
coverage:
  document_types: [playbooks, playbook_cards, working_methodology]
  full_text: yes
  historical_versions: no
  current_status: no
  pinpoint: yes
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [methodology_only, cited_norms_require_separate_verification]
---

# Локальные канонические методики

Provider только адресует существующие playbook и card-файлы и читает их на месте.
Он не создаёт вторую копию содержания и не позволяет серверному представлению
перезаписывать локальный канон. Материалы являются внутренней методикой работы,
а не НПА, судебной практикой или иным источником права.
