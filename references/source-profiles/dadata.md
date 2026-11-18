---
id: dadata
kind: specialized_provider
jurisdictions: [RU]
capabilities: [counterparty_identity, registration_data]
access: api
authority_level: derived_registry_data
adapter: dadata_party
connection_ref: dadata
protocol_refs:
  - references/dadata-mcp-setup.md
fallbacks: [egrul-nalog]
health_probe: null
rate_limits: account_plan_dependent
auth: token_from_local_secret_store
status: active
data_policy: abstracted_issue_only
verification_roles: [identity]
coverage:
  document_types: [company_registration_data, entrepreneur_registration_data]
  full_text: no
  historical_versions: no
  current_status: conditional
  pinpoint: no
  provenance: yes
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [counterparty_identity_only, not_a_source_of_law]
---

# DaData

Локальный adapter вызывает официальный `findById/party` API напрямую. Он принимает
только публичный идентификатор: 10/12-значный ИНН, 13-значный ОГРН либо
15-значный ОГРНИП. Произвольный текст, договоры и данные дела передавать нельзя.

Токены хранятся только в локальном слое секретов, а Codex и Claude видят единую
точку Legal Overlay. `overlay_status(probe=true)` не делает холостой платный вызов:
до первого запроса по делу статус остаётся `configured_not_probed`.
