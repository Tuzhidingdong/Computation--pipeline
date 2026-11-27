# Development Status — Computation--pipeline v4.1 integration

## Current branch protection

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/plan-compiler-v41-model-plugin-20261127
- This compiler/provenance change started from PR #3 HEAD dccebf72403aa3b20139507ca2350a9504cbcb6c.
- Latest compiler/test commit: 9d23895d5d568a1dfec2e4bc868fa737ff6efa66.
- PR #3 remains Draft and unmerged. Its base branch is unchanged.
- main, PR #1, PR #2 and all upstream Skill repositories are out of scope and remain untouched.
- No resolve-v41-planning command was run. No CP2K, HPC, Slurm or production DFT task was started.

## Frozen DOCX access and real-input evidence

The owner-provided source is on the local Windows machine:

F:\cp2k practical\hyy\CORR_DFT_Computational_Plan_v4.1_Frozen.docx

A prior local extraction was reported at:

F:\cp2k practical\hyy\pipeline_real_test_20261127_01\

That prior extraction contains 45 paragraph blocks and 10 table locations. The current Agent B development environment cannot access either Windows path, and the original DOCX/extraction artifacts were not available from the connected file library. Consequently, this branch revision has not been run against the exact Frozen DOCX. The 45-paragraph / 10-table counts are inherited from the prior local extraction report, not re-verified by this branch's compiler.

In particular, the actual source claims for ase_vibrations__cp2k and copyready_english_text have not been inspected in this environment. New tests exercise machine-style labelled claim parsing with synthetic examples; they do not adjudicate the actual Frozen DOCX values. Local Agent real-input comparison remains required.

## Compiler and Manifest changes in this revision

| Capability | Current behavior | Evidence status |
|---|---|---|
| Conflict identity | Claims are grouped by normalized field plus system and WP scope. Different fields or different model/WP scopes do not conflict with one another. | Synthetic software tests added; CI pending. |
| Value comparison | Normalizes Unicode compatibility forms, case, whitespace, formatting around common operators/delimiters, and whitespace between a numeric value and a known unit. Numeric magnitude and unit tokens remain distinct; e.g. 500 Ry and 500 Ha remain different. | Synthetic software tests added; CI pending. |
| Duplicate statements | Semantically identical values remain as separate original claims and separate evidence records; they are not reported as conflicts. | Synthetic CHARGE=0 regression added; CI pending. |
| True conflicts | Reports each raw value group with evidence ID, source location and original source text; the diagnostic remains blocking. | Paragraph and table-row conflict regressions added; CI pending. |
| Table evidence | A row-derived claim links every cell that contributes to its label/value pair, not just the label cell. | Synthetic regression added; CI pending. |
| DOCX sections and WP tasks | Extracts headings and WP-labelled task content blocks with source coordinates and evidence IDs. | Synthetic software tests added; real DOCX pending. |
| Systems and model fields | Creates source-linked system identifiers and model properties only when a DOCX heading/claim supplies the required context. | Synthetic software tests added; real DOCX pending. |
| Method parameters | Recognizes explicit labelled values including machine-style entries such as ADDED_MOS 80. Related prose without a reliable value relation remains unresolved. | Synthetic software tests added; real DOCX pending. |
| Dependencies / inputs / outputs / resources | Extracts explicit supported dependency phrases/arrows and labelled input/output/resource claims. Unsupported relations are retained as source evidence rather than guessed. | Synthetic software tests added; real DOCX pending. |
| Field provenance | Every top-level structured category is marked docx_evidence, unresolved or absent; evidence-backed entries carry evidence IDs. | Schema and synthetic tests added; CI pending. |
| Profile values | Kept separately under profile_overlay; each profile leaf has profile provenance and per-field DOCX comparison (consistent, conflict, needs_review, profile_only). Profile values do not populate DOCX systems, models, method, tasks or evidence. | Synthetic software tests added; real DOCX reconciliation pending. |

## Scientific decisions that remain blocked

- WP1_ORIENTATION_SCOPE_UNRESOLVED remains an execution blocker. The code does not choose between per_catalyst and across_both_systems.
- WP1_FRAGMENT_SPIN_COUNT_MISMATCH remains an execution blocker. The detailed six-candidate list and summary count of four remain unreconciled by this code. The existing owner-only options remain retain_all_six and select_four_explicitly; this revision does not choose either.
- The profile's 15 docking-orientation count is not inserted as DOCX-backed data. The prior source audit found no corresponding statement in the Frozen DOCX. Until the actual branch run confirms this against the exact source bytes, it is explicitly profile-only / requires real-input reconciliation, not a Frozen-DOCX fact.
- No atom/bond/donor topology has been inferred or created from these fields.

## Automated verification

- Actions run #405: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46015653652
- Tested code/test commit: 9d23895d5d568a1dfec2e4bc868fa737ff6efa66
- Result: 117 tests total: 115 passed, 2 optional upstream integration tests skipped, 0 failures / 0 errors; compileall passed.
- Actions run #408 on the subsequent status/report-only branch revision also passed with the same 117 total / 115 passed / 2 skipped result.
- The first CI run on the initial code draft exposed a Manifest evidence-aggregation error and an overly broad test expectation. Both were corrected before the final passing run.
- All test fixtures in this revision are synthetic. Software regression success must not be represented as real Frozen DOCX acceptance.

## Required next gates

1. Run the new branch against the exact Frozen DOCX and compare its evidence blocks and Manifest to the prior 45-paragraph / 10-table extraction.
2. Inspect actual claims for CHARGE, ase_vibrations__cp2k, and copyready_english_text; confirm repeated-equal statements are retained and real differing values still block.
3. Audit every profile reconciliation entry, especially the orientation count, against source evidence. Do not create an evidence ID for a profile-only value.
4. Keep both WP1 blockers until the owner explicitly decides. Do not call resolve-v41-planning during this work.
5. Complete real model source/topology, live Artifact registration and approval integration only under their separately authorized gates.

No production HPC calculation is authorized or performed.
