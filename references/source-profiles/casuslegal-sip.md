---
id: casuslegal-sip
kind: commercial_provider
jurisdictions: [RU]
capabilities: [intellectual_property, court_practice]
access: mcp
authority_level: secondary_navigation
adapter: remote_legal_mcp
connection_ref: casuslegal-sip
protocol_refs:
  - references/external-legal-databases.md
  - references/case-law-search.md
fallbacks: [kad-arbitr]
health_probe: tools/list
rate_limits: account_and_offer_dependent
auth: oauth_user_login
status: auth_required
data_policy: abstracted_issue_only
verification_roles: [navigation]
coverage:
  document_types: [intellectual_property_court_decisions]
  full_text: conditional
  historical_versions: no
  current_status: conditional
  pinpoint: conditional
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [court_practice_only, corpus_scope_is_intellectual_property]
---

# Casus: Суд по интеллектуальным правам

Специализированный корпус для IP-споров. Не смешивать его case IDs с другими
Casus connectors; найденный акт открывать полностью и сверять в первоисточнике.
