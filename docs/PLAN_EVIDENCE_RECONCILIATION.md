# Project Profile ↔ Manifest Evidence Reconciliation

## Purpose and ownership

The module **pipeline_contracts.plan_compiler.evidence_reconciliation** is an independent, read-only checker. It compares values in a Project Profile with labelled claims and original evidence in a Project Manifest.

It does **not** parse DOCX, extract claims, alter a Profile/Manifest, confirm scientific parameters, or participate in compilation/execution. It is not imported by the compiler, Manifest extractor, v4.1 plugin, CLI, or CalculationPlan path.

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

**aliases** maps a dotted Profile path to one or more exact Manifest field names/labels. An explicit entry replaces that path's default exact suffix aliases. It can disambiguate repeated leaf names. There is no substring, edit-distance, embedding, or semantic-similarity matching.

The report contains one entry per flattened Profile field:

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
      "missing_evidence_ids": [],
      "evidence": [
        {
          "evidence_id": "docx-block-000007",
          "text": "Exchange-correlation functional: PBE",
          "evidence_text": "Exchange-correlation functional: PBE",
          "source": {"part": "word/document.xml", "paragraph": 7},
          "contribution": "field_assertion",
          "claim_field": "xc",
          "claim_label": "Exchange-correlation functional",
          "claim_value": "PBE",
          "claim_unit": null,
          "claim_status": "requires_confirmation",
          "claim_source_text": "Exchange-correlation functional: PBE"
        }
      ],
      "provenance_issues": [],
      "rationale": "..."
    }
  ]
}
~~~

**evidence_id** is a convenience pointer to the first reference. **evidence_ids** retains every referenced ID in claim order, including an ID that cannot be resolved; **missing_evidence_ids** lists unresolved/ambiguous references. **evidence** contains only records found exactly once in the Manifest's original evidence array. It never fabricates a source record for a missing ID.

## Agent B Manifest evidence compatibility

The reader accepts both the earlier single-reference shape and Agent B's newer structure:

~~~json
{
  "field": "multiplicity",
  "label": "Multiplicity",
  "value": "2",
  "evidence_id": "docx-block-000010",
  "evidence_ids": ["docx-block-000010", "docx-block-000011"],
  "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 1},
  "source_text": "Multiplicity | 2",
  "sources": [
    {
      "evidence_id": "docx-block-000010",
      "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 1},
      "source_text": "Multiplicity",
      "raw_value": "2"
    },
    {
      "evidence_id": "docx-block-000011",
      "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 2},
      "source_text": "2",
      "raw_value": "2"
    }
  ],
  "context": {"system_id": "Cu-20", "work_package": "WP1"}
}
~~~

For a multi-cell assertion:

- Every evidence_ids reference must resolve to exactly one Manifest evidence record.
- When sources is present, its ordered IDs, source_text, and source locations must agree with those raw evidence records.
- The first cell is emitted as contribution=field_label; later value cells are emitted separately as contribution=field_value.
- Every returned cell's text and source come only from that individual original Manifest evidence record.
- The row-level claim_source_text remains a separate aggregate field. It is never copied into a cell's text.
- The claim label/field must match the first cell, and the ordered text from value cells must match the claim value. For multiple cells, table/row/column locations must be complete and in order.

A missing, duplicate, inconsistent, or incomplete referenced record prevents SOURCE_SUPPORTED and produces NEEDS_REVIEW. The Profile value is never inserted into the evidence array.

## System and Work Package scoping

The current Profile shape expresses scope in its path:

- systems.<system_id>... and models.<model_id>... are system/model-scoped.
- tasks.WP<n>... is Work-Package-scoped.
- A Manifest claim carries scope through context.system_id and context.work_package.

A claim is eligible only when every scope dimension matches exactly. A missing dimension, or a source claim that is narrower than the Profile path (for example, a system-specific claim offered for a global method field), is ambiguous and returns NEEDS_REVIEW. A claim explicitly scoped to a different system or WP is excluded from that Profile field; it cannot create a false conflict or support another system/WP. Repeated same-name fields across systems/WPs are compared only within matching scope.

Scope is not inferred from nearby headings or values by this module. It trusts only the explicit structured context carried by the Manifest claim.

## Matching and status rules

1. Flatten Profile mappings into dotted paths. Arrays are one ordered aggregate field, not guessed positional labels. Empty/null fields remain visible as NEEDS_REVIEW. Document metadata (schema_version, project_id, description, known_blockers) is excluded.
2. Match Manifest field/label identifiers against exact Profile path suffixes after deterministic identifier normalisation. Explicit aliases replace the defaults for their path.
3. Return SOURCE_SUPPORTED only when there is an exact field match, a unique scope-compatible target, one unique value, complete evidence references, and equality under the conservative value normalisation.
4. Repeated identical claims remain separate and preserve every referenced evidence record. Different values for the same exact field in the same system/WP scope return SOURCE_CONFLICT.
5. A complete exact field claim with one unique value different from the Profile returns SOURCE_MISMATCH.
6. A literal token/phrase in raw evidence without a field-bound claim returns MENTION_ONLY; a coincidentally repeated number never supports a parameter.
7. No field claim and no literal mention returns PROFILE_ONLY. Missing values, ambiguous ownership, or incomplete evidence returns NEEDS_REVIEW.

## Normalisation boundary

Allowed:

- NFKC, case, whitespace, and deterministic identifier-format normalisation compatible with the current Manifest label normaliser.
- Equal finite numeric values expressed as integer, decimal, or scientific notation (for example 500, 500.0, and 5e2).
- KEY=VALUE / KEY: VALUE only when the repeated key exactly identifies the claim's own field or label.
- Quantities only when both sides explicitly carry a unit. A closed Profile-key suffix whitelist is used for fields such as _ry, _ha, _hartree, _ev, _mev, _angstrom, _ev_per_angstrom, _bohr, _nm, _ps, _fs, and _k. Explicit Å/Angstrom, Ha/hartree, and eV/Å/eV/Angstrom aliases are canonicalised.

Not allowed:

- No conversion between different physical units (for example eV ↔ Ry or Å ↔ nm).
- No guessing a unit from arbitrary key text.
- No fuzzy matching, partial-name matching, nearby-number binding, or conflict winner selection.
- No use of aggregate row text as the original text of any individual cell.
- No use of Profile values as substitute evidence.

## Regression tests

The test file tests/test_plan_evidence_reconciliation.py uses synthetic data matching Agent B's claim/evidence structure. It covers:

- two-/multi-cell table rows resolving every evidence ID and returning original per-cell text/location;
- first-cell label versus second-cell value separation;
- missing value-cell evidence and nonexistent IDs failing closed;
- inconsistent sources text/location failing closed;
- repeated identical row claims preserving every cell reference without false conflict;
- different systems and WPs retaining independent claims;
- ambiguous or missing system/WP ownership returning NEEDS_REVIEW;
- different units not being converted;
- the six statuses, exact aliases, duplicate values, mismatches, mentions, incomplete provenance, and read-only input handling.

Run:

~~~bash
python -m unittest discover -s tests -p "test_plan_evidence_reconciliation.py" -v
python -m unittest discover -s tests -v
python -m compileall -q pipeline_contracts tests examples
~~~

## Known limitations

- The checker validates provenance relations already encoded in the Manifest. It does not audit DOCX extraction itself or infer a missing system/WP context.
- It recognises system scope at Profile paths systems.<id> / models.<id> and WP scope at tasks.WP<n>. Other project-specific scope schemas require an explicit future interface extension, not a guessed binding.
- Profile arrays remain ordered aggregate values. It will not infer equivalence between arbitrary prose, table layouts, or differently shaped arrays.
- A successful status is evidence reconciliation only, not owner confirmation, scientific approval, model validation, or execution permission.
