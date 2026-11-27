# Agent B Development Report — Frozen DOCX Conflict and Provenance Fix

Date: 2026-11-27  
Repository: Tuzhidingdong/Computation--pipeline  
PR: https://github.com/Tuzhidingdong/Computation--pipeline/pull/3  
Branch: agent-b/plan-compiler-v41-model-plugin-20261127

## 1. Scope and baseline

This change is limited to the Pipeline DOCX compiler, v4.1 compiler, Manifest schema, tests, status and this report. It starts from the PR #3 head verified before editing:

dccebf72403aa3b20139507ca2350a9504cbcb6c

PR #3 remains Draft and unmerged. The existing PR base branch and base SHA are unchanged. No changes were made to main, PR #1, PR #2 or upstream Skill repositories.

No resolve-v41-planning command, CP2K, HPC, Slurm or production DFT task was run.

## 2. Root causes

### A. False conflict detection

The previous detect_conflicts() grouped by the literal field string and compared only str(value).strip().casefold(). That made its equivalence rules incomplete, and the grouping lacked system/WP context. A field appearing in separate systems or work packages could be compared as though it described the same scientific object.

Table-derived claims had a second evidence defect: a row claim used only the first cell's evidence ID, although its value came from the remaining cell(s). A conflict sourced from a table therefore could not identify all source cells.

### B. Profile values masquerading as extracted structure

The previous v4.1 compiler replaced the DOCX Manifest's systems, method and tasks with values from project_profile.json. This made profile-transcribed values appear to be part of the primary structured Manifest despite lacking DOCX evidence IDs. The base compiler also returned empty structured task/model/input-output/resource fields even when the source contained explicit labels or WP headings.

## 3. Changes

### Conflict and evidence handling

- Canonicalizes field identity using Unicode compatibility normalization, case folding and stable label formatting.
- Compares values after narrowly scoped presentation normalization. Case/spacing and numeric-unit spacing are normalized; numeric magnitude and unit tokens are preserved, so 500 Ry and 500 Ha are not merged.
- Separates conflict scopes by normalized field, system ID and work-package ID.
- Retains all original claims and evidence entries for duplicate equal statements.
- Emits a blocking conflict only where a single scoped field has more than one normalized value.
- Conflict diagnostics contain raw values grouped by value, each supporting evidence ID, original source text and source location.
- Table-derived row claims reference all label/value cells participating in the assertion.

### Structured DOCX Manifest

- Builds heading/section paths and WP task content blocks with evidence IDs and source coordinates.
- Structures source-linked system/model properties, method claims (including machine-style labels such as ADDED_MOS 80), task count claims, explicit dependencies, input/output labels and resources.
- Preserves scientifically relevant source prose as unresolved_structured_fields when a dependable field/value relation cannot be established.
- Marks each top-level structured category and every parsed field with docx_evidence, unresolved or absent provenance, including evidence IDs when applicable.
- Preserves claim raw text and evidence separately from structured values.

### Profile separation and reconciliation

- Removes the silent profile overlay into the DOCX systems, models, method, tasks and evidence.
- Stores profile values under profile_overlay, with source path and version.
- Gives each profile leaf a separate profile provenance record that contains no DOCX evidence IDs.
- Records a comparison to DOCX evidence as consistent, conflict, needs_review or profile_only; a relevant but unstructured source mention is unresolved rather than absent.
- The 15-orientation profile value is not promoted to DOCX evidence. It receives no synthetic evidence ID.

## 4. Regression coverage added

New synthetic software regressions cover:

1. Duplicate CHARGE = 0 claims: no conflict, both claims and evidence retained.
2. Case, spacing and presentation-format variants: no false conflict.
3. CHARGE = 0 vs CHARGE = 1: blocking conflict with both raw values and source evidence.
4. Different field names with the same value: no conflict; different physical units remain distinct.
5. Table row conflicts: every contributing label/value cell is identified.
6. Same field across different WP scopes: no cross-scope conflict.
7. Separate machine-style fields for ase_vibrations__cp2k and copyready_english_text.
8. DOCX-derived system, formula/atom-count/charge model properties, method ADDED_MOS 80, WP sections, explicit dependency, resources and input/output extraction.
9. Unstructured method prose: unresolved with its source evidence ID, not filled by profile.
10. A profile-only 15-orientation field: no DOCX evidence ID.
11. Unstructured orientation prose: unresolved, not promoted to a profile fact.
12. DOCX/profile formula agreement and disagreement: both cases are explicitly reconciled, and DOCX values are never overwritten.
13. Absent categories are explicitly marked absent.

The ase_vibrations__cp2k and copyready_english_text test cases use synthetic input. They verify independent claim parsing and duplicate-value handling; they do not establish what the Frozen DOCX actually says for those claims.

## 5. Real Frozen DOCX verification boundary

The target file is on the owner's local Windows machine:

F:\cp2k practical\hyy\CORR_DFT_Computational_Plan_v4.1_Frozen.docx

The previous local extraction directory is:

F:\cp2k practical\hyy\pipeline_real_test_20261127_01\

That prior run was reported to contain 45 paragraph blocks and 10 table locations. These paths are not accessible from the current Agent B environment, and the DOCX/extraction files were not available in the connected file library. This revision therefore has not been run against the exact Frozen DOCX. It does not claim that this branch re-verified the 45/10 parse, adjudicated the actual suspect claims, or established all real DOCX/profile reconciliation results.

The real-input revalidation must compare the new compiler output to the previous extracted content and original source SHA. The Frozen DOCX must remain read-only.

## 6. Scientific blockers and execution safety

Both existing blockers remain part of apply_v41_audit() and continue to carry blocks_execution=true:

- WP1_ORIENTATION_SCOPE_UNRESOLVED: per_catalyst vs across_both_systems.
- WP1_FRAGMENT_SPIN_COUNT_MISMATCH: detailed six candidates vs summary count four.

The existing choices retain_all_six and select_four_explicitly have not been selected by this change. The implementation did not invoke resolve-v41-planning.

No structure or topology was generated, and no production calculation was launched.

## 7. Verification and delivery

- Code/test commit: 9d23895d5d568a1dfec2e4bc868fa737ff6efa66.
- GitHub Actions run #405: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46015653652
- Result on that exact code/test commit: 117 tests total — 115 passed, 2 optional upstream integration tests skipped, 0 failures / 0 errors; compileall passed.
- Actions run #408 on the follow-up status/report revision also passed: 117 total, 115 passed, 2 skipped, 0 failures / errors; compileall passed.
- The first CI attempt detected 8 errors and 1 failed assertion. The errors shared a root cause in top-level Manifest evidence aggregation; the failed assertion expected the WP content category to be unresolved even though its source text had been preserved as a task block. Both were corrected and covered by the final successful run.
- Real Frozen DOCX regression: not run in this environment; local revalidation required.
- PR #3 remains Draft and unmerged.
