# business_writing

`final_check.py` performs a read-only structural check of a `business_writing.v1` JSON
manifest. It checks answer placement, treatment of decisive gaps, uncertainty visibility,
action ownership, material risk chains, lawful recommendations and preservation of the lawyer
audit trail.

```powershell
python tools/business_writing/final_check.py path/to/manifest.json
```

Exit code is `0` only for `READY_FOR_REVIEW`; other outcomes return `1`. Malformed input returns
`2`. The checker does not validate law, facts, source quality, tone in the rendered document or
the business merits of a recommendation. Human review and the profile skill gates remain
mandatory.

Schema summary:

```json
{
  "schema": "business_writing.v1",
  "mode": "LEGAL_MEMO",
  "audience": "BUSINESS",
  "answer": {
    "present": true,
    "text": "Компания может выбрать законный вариант A после проверки условия X.",
    "location_percent": 8,
    "decisive_fact_unknown": false,
    "branches_or_precise_question": false
  },
  "uncertainties": [
    {
      "type": "UNVERIFIED_SOURCE",
      "resolved": false,
      "visible_in_lawyer_version": true,
      "business_treatment": "SOURCE_STATUS",
      "decisive": false,
      "trace": {
        "marker": "[ПРОВЕРИТЬ ИСТОЧНИК]",
        "status": "PENDING_VERIFICATION",
        "handoff": "Legal verifies before delivery",
        "source_refs": ["SRC-1"],
        "locators": ["p. 3"]
      }
    }
  ],
  "actions": [],
  "risks": [],
  "recommendations": [],
  "source_status": {
    "lawyer_trace_preserved": true,
    "main_reasoning_contains_research_diary": false,
    "material_gaps_inventoried": true
  },
  "quality": {
    "duplicate_propositions": false,
    "ceremonial_opening": false,
    "remote_sanctions_padding": false,
    "weak_source_detour": false,
    "internal_markers_in_business_copy": false
  },
  "mode_requirements": {
    "analysis_by_issue": true,
    "source_status_block_present": true
  }
}
```

For each unresolved uncertainty, `trace` stores the actual lawyer-facing marker, status,
handoff, source refs and matching locators. A boolean declaration alone is insufficient.
`MISSING_FACT` may have empty source arrays; other uncertainty types require at least one
source/locator pair. Mode-specific booleans are mandatory for the selected mode.
