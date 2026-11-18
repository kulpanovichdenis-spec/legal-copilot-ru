---
id: local-legal-memory-sqlite
kind: internal_curated
jurisdictions: [RU, EAEU]
capabilities: [legal_opinions, reviewed_telegram, topic_maps, official_labor_guidance]
access: local_files
authority_level: internal_context
adapter: sqlite_legal_memory
connection_ref: local-legal-memory-sqlite
protocol_refs:
  - tools/legal_overlay/README.md
  - references/legal-kb-usage.md
  - references/source-hierarchy.md
fallbacks: []
health_probe: sqlite_legal_memory_status
rate_limits: none_local_read_only
auth: null
status: active
data_policy: local_only
verification_roles: [navigation, internal_context]
coverage:
  document_types: [legal_opinions, reviewed_telegram_cards, topic_maps, official_labor_guidance]
  full_text: conditional
  historical_versions: no
  current_status: no
  pinpoint: conditional
  provenance: conditional
norm_verification:
  eligible: false
  mode: not_eligible
  requires: []
  verified_tools: []
  last_smoke_at: null
  limitations: [mixed_non_normative_context, cited_norms_require_separate_verification]
---

# Local legal memory

Immutable local provider for lawyer opinions, reviewed Telegram commentary, topic maps and official
Rostrud labor guidance. Opinions are internal context, Telegram cards are secondary context, topic
maps are navigation only, and Rostrud cards are `administrative_guidance`. Labor cards must be
presented as official non-normative guidance and their legal references verified separately.
None of these layers may be presented as a source of law. The snapshot is opened only through
`mode=ro&immutable=1` after manifest, SHA-256, schema and integrity validation.

The default Telegram search exposes only `keep_commentary` and `keep_guideline`. Records marked
`needs_source_review` or `delete_candidate` require an explicit `status` filter.
