# Agent B Read-only Interface Review — PR #4

Date: 2026-11-27  
Repository: `Tuzhidingdong/Computation--pipeline`  
PR #3 baseline: `c0fe1623d746b0ed77782da2b7a588fbe13f3f83`  
PR #4 reviewed HEAD: `c99c25159018254703de96c644a04e2cafe29c1b`  
PR #4 base: `c0fe1623d746b0ed77782da2b7a588fbe13f3f83`

## 1. Decision

**Recommendation: C — do not integrate yet. Keep PR #3 and PR #4 as separate Draft PRs pending the real Frozen DOCX evidence review and the additional interface regressions below.**

PR #4 is now correctly based on the specified PR #3 HEAD: comparison reports 5 commits ahead, 0 behind, merge base exactly `c0fe1623...`. It changes only its three Agent C-owned files. No Agent C file was modified by this review. No merge or copy was performed.

The implementation is a meaningful improvement over the earlier revision and is suitable for continued independent testing. It is not yet a drop-in replacement for the v4.1 reconciliation path because the actual v4.1 alias/scope contract has not been exercised against the real Manifest, and two fail-closed/status edge cases remain.

## 2. Evidence mapping review

### Passed by source inspection

PR #4 now reads legacy `evidence_id` and plural `evidence_ids`, and also reads the newer Agent B `sources` entries. For each referenced ID it requires exactly one match in Manifest `evidence`; it takes text and location from that original evidence record, not from the aggregate claim excerpt.

When `sources` is present, its ordered IDs, source text and location are compared to the corresponding original Manifest evidence records. It also validates the claim-level first-cell source pointer, the joined row excerpt, the first-cell label, the ordered value cells, and table/row/column ordering. This aligns with the current Agent B table-claim shape produced in `pipeline_contracts/plan_compiler/manifest.py`: a first-cell `evidence_id`, all contributor IDs in `evidence_ids`, and individual `sources` records.

The report preserves the row-level `claim_source_text` separately from individual evidence text. It does not turn the Profile value into evidence. Missing source records, duplicated evidence records in the Manifest index, text/location mismatches and incomplete multi-cell provenance become `NEEDS_REVIEW`.

### Remaining fail-closed gap R4-1: duplicate IDs in evidence_ids can be silently deduplicated

In `_evidence_payload()`, the `evidence_ids` loop appends an ID only when it is not already present. When `sources` is absent, a claim such as `evidence_ids=["ev-1", "ev-1"]` is silently reduced to one reference. If the Manifest contains one valid `ev-1` record and the other singular fields are consistent, the claim can proceed without a provenance issue.

This is distinct from duplicate records in the Manifest evidence array (which are caught by the exact-one-record check), and distinct from duplicate entries in `sources` (which usually fail the ordered ID comparison). The repeated ID inside the claim's own list should itself be treated as malformed.

**Required before integration:** detect duplicate IDs in the raw `evidence_ids` array before de-duplication and return `NEEDS_REVIEW`; add a regression for the plural-ID-only case with no `sources` array.

### Remaining coverage gap R4-2: multi-cell completeness is only checked against the IDs already declared

The implementation rigorously validates every declared reference and its listed cell data. It does not independently prove that the claim declared every evidence block belonging to that table row. If a caller omits a contributing cell from both `evidence_ids` and `sources`, then constructs `source_text` and `value` from the reduced set, the current checks have no expected contributor list against which to detect the omission.

This is not evidence that the current Agent B extractor omits cells: its row loop currently includes all extracted cells. It is an interface-hardening gap if the reconciliation module is expected to validate arbitrary or partially damaged Manifests.

**Recommended regression:** create a table row with three original Manifest cell records but a claim that references only cells one and three; verify either that the omitted same-row cell is detected or document that completeness is guaranteed upstream by the Manifest producer and is outside this module's contract.

## 3. System/WP scope review

The field-claim path is conservative and explicit:

- `systems.<id>` / `models.<id>` Profile paths require matching `context.system_id`.
- `tasks.WP<n>` requires matching `context.work_package`.
- A claim scoped to another system/WP is excluded.
- Missing scope, or a narrower source claim offered to a broader Profile path, is marked ambiguous and results in `NEEDS_REVIEW`.

This is stronger than the current v4.1 in-file matcher, which simply filters nonmatching/missing context. The generic module's tests cover same field/value names in separate systems and WPs and missing context.

### Remaining status-scope issue R4-3: MENTION_ONLY scans evidence without scope

When no scope-compatible field claim is selected, the `MENTION_ONLY` fallback calls `_mention_evidence(profile_value, evidence)` over the entire Manifest evidence array. Those evidence records do not carry a system/WP context in the current Manifest shape. Therefore a literal value occurring only in another system's or another WP's source block can be reported as `MENTION_ONLY` for this scoped Profile path.

This cannot produce `SOURCE_SUPPORTED`, so the fail-closed execution boundary is not bypassed. However, it can misclassify the status boundary and incorrectly suggest that the value is mentioned in the relevant scope.

**Required before integration:** add a regression where a `systems.Cu-20.charge` Profile value appears only in a claim/evidence explicitly scoped to `SnCu-20`, and another where a WP value appears only in a different WP. Either bind mention evidence to validated explicit context or return `NEEDS_REVIEW` when a scoped mention cannot be attributed safely. Do not treat cross-scope text as scoped mention evidence.

## 4. Failure-closed and status-boundary review

The six statuses are conceptually well separated:

- `SOURCE_SUPPORTED`: exact field alias, matching explicit context, comparable value and complete provenance.
- `SOURCE_CONFLICT`: multiple distinct source values for the same exact field in the same matching scope.
- `SOURCE_MISMATCH`: one well-provenanced source value differs from the Profile value.
- `MENTION_ONLY`: literal source occurrence without a field-bound claim.
- `PROFILE_ONLY`: neither a matching field claim nor a literal mention.
- `NEEDS_REVIEW`: absent/ambiguous scope, unset value, invalid references or incomplete provenance.

No unit conversion is performed. Numeric values are canonicalised with `Decimal`; quantities compare only when both sides carry an explicitly available unit (including a whitelisted Profile-key suffix). Different units remain different. The input Manifest is not mutated.

The edge cases in R4-1 and R4-3 should be covered before relying on the status labels in an integrated workflow. R4-2 should be contractually resolved as either an upstream Manifest guarantee or an additional row-completeness check.

## 5. Relationship to PR #3 v4.1 _profile_provenance()

There is substantial functional overlap, not a complementary pipeline stage:

| Capability | PR #3 `_profile_provenance()` | PR #4 generic module |
|---|---|---|
| Flatten Profile fields | Yes | Yes |
| Match claim field/label | v4.1 leaf aliases | Exact suffix aliases plus caller-provided explicit aliases |
| System/WP context | Filters by explicit context, but missing context can collapse to no match | Explicit match / mismatch / ambiguous classification |
| Compare values | Presentation normalization plus a limited float/unit check | Decimal canonicalisation and conservative explicit-unit handling |
| Distinguish absent/unresolved/mention | `profile_only` / `needs_review` | `PROFILE_ONLY` / `MENTION_ONLY` / `NEEDS_REVIEW` |
| Validate evidence ID resolves uniquely | No | Yes |
| Validate original per-cell text/location | No | Yes |
| Independent reusable API | No; wired into v4.1 compile | Yes; currently standalone/read-only |

PR #3 currently calls `_profile_provenance()` from `compile_v41_docx()` and emits `profile_reconciliation` / `profile_field_provenance`. Adding PR #4 alongside it would create two competing sources of reconciliation truth.

PR #4 could eventually become the shared implementation, with v4.1 supplying explicit aliases and scope configuration. However, the current generic tests do not yet provide an end-to-end mapping for the actual v4.1 Profile paths (including system formulas/counts/charges, nested method keys, and WP task lists) to the actual DOCX claim labels. The real Frozen DOCX and run_04 details are also not present in this review environment. Replacing the wired v4.1 logic now would therefore be premature.

## 6. CI and validation evidence

PR #4 HEAD `c99c25159018254703de96c644a04e2cafe29c1b` has Actions run #415:
- 141 total tests; 139 passed, 2 optional upstream tests skipped; 0 failures/errors.
- `python -m compileall -q pipeline_contracts tests examples`: passed.
- Run: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46018870512

These are software/contract tests. They do not establish acceptance against the real Frozen DOCX or approve scientific parameters.

## 7. Next gate

Keep both PRs Draft and separate. Before reconsidering integration:

1. Address R4-1 and R4-3 with focused tests; resolve the R4-2 completeness contract.
2. Build an explicit v4.1 alias/scope configuration from real DOCX-backed Manifest claims, not Profile-only guesses.
3. Run the generic module and current v4.1 reconciliation against the same exact Frozen DOCX Manifest; compare field status, complete evidence IDs, source text and locations side by side.
4. Only then decide whether PR #4 remains an independent audit module (A) or replaces the v4.1 in-file implementation through an explicit configured interface (B).

No source DOCX was available to this review. This report does not claim real-input acceptance. No scientific decision, model construction or calculation execution was performed.
