# Procedural argument manifest

`draft_check.py` performs a read-only structural check before a significant procedural
document is rendered. It validates explicit links between the approved analysis,
material propositions, arguments, evidence and, for an appeal or cassation complaint,
the alleged error in the challenged act.

Run:

```powershell
python tools/procedural_drafting/draft_check.py workflow/<дело>/_analysis/<document>.argument.yaml
```

The YAML root uses `schema: procedural_argument.v1` and these blocks:

- `document`: `type`, `stage`, `structure_mode`, `requested_outcomes`;
- `analysis_scope`: permitted refs for claims, elements, facts, issues, responses,
  proof issues, cases, evidence and authorities;
- `material_propositions`: typed factual/legal propositions, statuses and sources;
- `arguments`: thesis heading, conclusion, rules, application, adverse and result;
- `analogies`: criterion, decisive facts, reasoning link, comparison and effect;
- `appellate_errors`: error description, locator, error type, governing rule,
  materiality and consequence; every material appellate argument and requested outcome
  must be covered;
- `evidence_links`: evidence-to-fact links;
- `critic` and `constraints`: pending human work and an explicit limited-draft decision.

Derived outcomes:

- `READY_FOR_RENDER`: the structural contract is closed;
- `BLOCKED_MATERIAL_GAP`: a material proposition, argument or appellate error lacks
  required support;
- `HANDOFF_REQUIRED`: source, adverse, critic or human work remains;
- `LIMITED_DRAFT`: a lawyer expressly authorized drafting with visible gaps. Structural
  errors cannot be converted into this outcome. Every remaining gap must have a marker
  in its object or in `constraints.visible_gap_markers` keyed by the object ref.

The CLI returns zero only for `READY_FOR_RENDER` and a structurally valid
`LIMITED_DRAFT`. A material block or pending handoff returns exit code 1; a load error
returns 2.

For a factual application, each used fact must be covered by an evidence link attached
to a linked material proposition. For an appellate error, every governing rule must be
grounded by the linked argument's verified legal proposition. A limited-draft decision
does not override pending adverse, critic, source-verification or human gates; those
produce `HANDOFF_REQUIRED`.

The checker does not establish facts, verify authority, assess legal sufficiency, choose
strategy, or compare the manifest semantically with the final DOCX. A successful check
does not mean that the document is ready to file.
