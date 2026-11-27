# Project Profile ↔ Manifest Evidence Reconciliation

## Purpose and ownership

The module **pipeline_contracts.plan_compiler.evidence_reconciliation** is a read-only, project-agnostic checker. It compares non-metadata values in a Project Profile with the labelled claims and source evidence already present in a Project Manifest.

It does **not** parse DOCX files, extract new claims, change a Profile, rewrite Manifest claims, confirm scientific parameters, or participate in compilation/execution. The caller supplies two parsed mappings. This module returns an auditable report only.

The implementation is intentionally independent of the compiler flow. It is not imported or called by compiler.py, manifest.py, the v4.1 project plugin, the CLI, or the CalculationPlan path.

## Interface

~~~python
from pipeline_contracts.plan_compiler.evidence_reconciliation import (
    reconcile_project_profile,
)

report = reconcile_project_profile(
    profile=project_profile_dict,
    manifest=project_manifest_dict,
    aliases={
        "method.cutoff_ry": ["plane_wave_cutoff", "Plane-wave cutoff"],
    },  # optional
)
~~~

**aliases** maps a dotted Profile field path to one exact Manifest field or label, or a sequence of exact identifiers. An explicit entry replaces that path's default suffix aliases; to disambiguate repeated leaf names, explicitly map each affected Profile path. Identifier normalisation follows the Manifest's existing lowercase/underscore/punctuation-removal convention. It does not use substring, edit-distance, embedding, or semantic-similarity matching.

The report has this top-level shape:

~~~json
{
  "schema_version": "1.0.0",
  "result_count": 1,
  "summary": {
    "SOURCE_SUPPORTED": 1,
    "SOURCE_CONFLICT": 0,
    "SOURCE_MISMATCH": 0,
    "PROFILE_ONLY": 0,
    "MENTION_ONLY": 0,
    "NEEDS_REVIEW": 0
  },
  "results": [
    {
      "profile_field": "method.xc",
      "profile_value": "PBE",
      "status": "SOURCE_SUPPORTED",
      "evidence_id": "docx-block-000007",
      "evidence_ids": ["docx-block-000007"],
      "evidence": [
        {
          "evidence_id": "docx-block-000007",
          "text": "Exchange-correlation functional: PBE",
          "evidence_text": "Exchange-correlation functional: PBE",
          "source": {"part": "word/document.xml", "paragraph": 7},
          "claim_field": "xc",
          "claim_label": "Exchange-correlation functional",
          "claim_value": "PBE",
          "claim_unit": null,
          "claim_status": "requires_confirmation"
        }
      ],
      "rationale": "..."
    }
  ]
}
~~~

**evidence_id** is a convenience pointer to the first source; **evidence_ids** and **evidence** retain every matched source claim. For table-derived claims, **text** prefers the Manifest claim's complete source_text (which may contain the joined row), while **evidence_text** preserves the exact text in the referenced evidence record. **source** retains the claim/evidence location. The input Manifest is never modified.

## Matching and status rules

1. Flatten Profile mappings into dotted paths. Arrays are treated as one ordered field, not split into invented positional fields. Explicit null/empty scalar fields are included as NEEDS_REVIEW. Metadata roots schema_version, project_id, description, and compiler-generated known_blockers are excluded.
2. For automatic matching, compare the Manifest claim's field and label against exact Profile path suffixes (from the full path down to the leaf). This permits a unique leaf match such as method.xc ↔ xc; if the same leaf identifies multiple Profile paths, the result is NEEDS_REVIEW. A project may supply an explicit alias to disambiguate or connect differently named fields.
3. A Profile value is SOURCE_SUPPORTED only when there is at least one exact field-linked claim, all relevant claims have complete evidence ID/text/location provenance, the claims reduce to one unique source value, and that value equals the Profile value after the limited normalisation below.
4. Repeated claims with the same normalised value are one value supported by multiple source records. Different values for the same exact field are SOURCE_CONFLICT, even when one happens to equal the Profile value. No source record is deleted or selected away.
5. An exact field claim with one unique value different from the Profile is SOURCE_MISMATCH. A field name that is merely similar does not count as a match.
6. If no exact field claim exists but the Profile value/term appears as a literal token or phrase in raw Manifest evidence, the result is MENTION_ONLY. This records occurrence only; it is not field support. A standalone number cannot support a parameter.
7. If neither a field-linked claim nor a literal mention exists, the result is PROFILE_ONLY. Missing values, incomplete claim provenance, or multi-Profile-path matches are NEEDS_REVIEW.

## Normalisation boundary

Allowed:

- Ignore case and collapse whitespace in field identifiers and textual values.
- Treat integer/decimal/scientific-notation representations of the same finite numeric value as equal (for example, 500, 500.0, and 5e2).
- Accept a repeated KEY=VALUE / KEY: VALUE form only when the repeated key exactly normalises to that claim's own field or label; otherwise the value is left untouched.
- Compare values already split by a labelled table claim as the claim's extracted field/value pair.
- Compare quantities only when both sides explicitly carry a unit. Explicit unit suffixes in Profile keys are recognised only from a closed whitelist: _ry, _ha, _hartree, _ev, _mev, _angstrom, _ev_per_angstrom, _bohr, _nm, _ps, _fs, and _k. A small set of unambiguous spelling aliases is canonicalised: Å/Angstrom, Ha/hartree, and eV/Å/eV/Angstrom.

Not allowed:

- No conversion between different physical units (for example, eV ↔ Ry or Å ↔ nm), even when a conversion would be mathematically possible.
- No unit guessing from arbitrary Profile path text. Only the closed, documented suffix whitelist is treated as an explicit unit declaration; otherwise a unit must be present in the actual value or explicit { "value": ..., "unit": ... } object / Manifest claim unit field.
- No fuzzy/semantic field matching, partial-string matching, inference from nearby numbers, or selection of one value from a conflict.
- No promotion of a MENTION_ONLY result to source support.

## Test coverage

The test file **tests/test_plan_evidence_reconciliation.py** uses only synthetic Profile/Manifest dictionaries. It covers:

- repeated identical values remaining SOURCE_SUPPORTED;
- two different values producing SOURCE_CONFLICT;
- absent source field producing PROFILE_ONLY;
- isolated numeric mention producing MENTION_ONLY;
- exact explicit alias mapping, including resolution of duplicate leaf-name ambiguity;
- mismatching units producing SOURCE_MISMATCH (no conversion);
- evidence ID, text and source location retention, without mutating source evidence;
- ambiguous field-to-multiple-Profile mapping producing NEEDS_REVIEW;
- non-exact/similar field names not being accepted;
- KEY=VALUE handling, table-row excerpt retention, explicit unit handling, and incomplete provenance.

Run:

~~~bash
python -m unittest discover -s tests -p "test_plan_evidence_reconciliation.py" -v
python -m compileall -q pipeline_contracts tests
~~~

## Known limitations

- This module validates the relationship encoded in Manifest claims. It does not independently validate the DOCX parser's extraction quality or reconstruct omitted table structure.
- Manifest table claims currently point to the label cell's evidence ID while source_text may contain the joined row. The report intentionally preserves both the claim excerpt and the referenced evidence cell rather than fabricating a new evidence ID for another cell.
- Profile arrays are compared as ordered aggregate values. A differently formatted prose/list representation may require an explicit, source-backed claim representation; the module will not guess list equivalence.
- Exact default suffix matching may be ambiguous for repeated leaf names. Supply an explicit, unique alias only after the field mapping has been established by the project owner/reviewer.
- This report is not an owner confirmation and must not be used as a scientific decision or execution approval.
