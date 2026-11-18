# Common pharma-compliance knowledge

These versioned JSON files are the auditable source records for the bundled skill.
`../database/pharma_compliance.sqlite` is a deterministic read-only projection built by
`../scripts/build_database.py`; it is not the normative legal snapshot and is not a legal
authority.

The records were integrated from `pharma-compliance-playbook-v0.1` supplied for this
project. Source URLs and summaries are navigation leads. Missing source/effective dates
remain explicit data gaps; do not infer currency from `status: active`. Russian legal
propositions must be verified through the project's normal source hierarchy.

`search_terms.json` contains bilingual retrieval vocabulary derived from the supplied
acceptance scenarios. It improves recall and does not add legal propositions.
