# Current Follow-up — Generic Manifest Boundary and Evidence Regression

Updated: 2026-11-28

- PR #3 remains Draft, open, unmerged.
- Base SHA remains 5e6e26fdf94efbac54182f819f4879c1aafb1d4d.
- Code HEAD verified by Actions run #543: c36b66def19038f0f15578a1222d5ec3e096cafe.
- Full report: docs/reports/AGENT_B_GENERAL_LAYER_BOUNDARY_AND_EVIDENCE_REGRESSION_20261128.md.

## Layer boundary

CORR v4.1-specific DOCX recognition and unresolved-field semantics are in projects/corr_dft_v4_1/docx_adapter.py. projects/corr_dft_v4_1/plan_compiler.py calls the adapter explicitly through compile_docx() callbacks. pipeline_contracts/plan_compiler/manifest.py contains reusable block/evidence parsing, heading and scope handling, and field conflict rules only. CHARGE numeric/explanation separation stays generic and preserves the complete source evidence.

Conflict detection is label-independent by default and no longer excludes all outputs. Only the explicit CORR adapter marks the exact ASE summary/detail pair as coexisting. Output fields are separated by artifact identity; competing values within one artifact still block.

## Tests and validation

Actions run #543: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46092308085

- unittest: 133 total, 131 passed, 2 skipped, 0 failures.
- pytest: 131 passed, 2 skipped, 108 subtests passed.
- compileall: passed.
- 104 Profile CSV rows: fully compared by unique field, status, docx_status and evidence ID list.
- Expected statuses: 39 consistent / 44 needs_review / 21 profile_only.
- All referenced evidence IDs are asserted to exist in Manifest evidence.
- Heading tests cover Normal numbered headings, Heading1–Heading9, ListBullet/ListNumber/list_info 1.1 list items, and ordinary prose.

The run_04 test remains an evidence-block regression using published source text, evidence IDs and coordinates. It is not a Frozen DOCX binary end-to-end acceptance run.

No project_profile.json scientific values changed. No owner scientific choices, topology construction, resolve-v41-planning, CP2K, HPC, Slurm or production DFT. main and PR #1/#2/#4 remain untouched.

---

# Current Development Status — PR #3 run_04 evidence repair

Updated: 2026-11-28

## Repository / PR

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/plan-compiler-v41-model-plugin-20261127
- PR #3: https://github.com/Tuzhidingdong/Computation--pipeline/pull/3
- PR remains open and Draft; not merged.
- Base branch/SHA unchanged.
- Implementation, regression and Profile CSV HEAD validated by Actions: d66570408fb3682bfc36c029bc9c5e645657bcfd.
- The run_04 evidence-driven report is docs/reports/AGENT_B_RUN04_EVIDENCE_DRIVEN_PR3_FIX_20261128.md.
- The 104-row mapping is docs/reports/real_docx_run04_20261127/PR3_PROFILE_RECONCILIATION_AFTER_FIX.csv.

## run_04 evidence-driven repair

Five reports on branch diagnostics/pr3-real-docx-run04-evidence-20261127 were read and used. The repair is based on source text, evidence IDs and DOCX paragraph/table locations, not on Profile defaults.

- CHARGE: split scalar 0 from explanatory spin text; preserve explanation and evidence; no false conflict.
- ase_vibrations_cp2k: table summary and paragraph detail classified as consistent summary/detail evidence; preserve all table cells and paragraph evidence.
- copy_ready_english_text: Computational Details and Results Report Template remain two distinct output artifacts.
- ADDED_MOS 80: independently extracted from table 6, row 5, column 2, evidence docx-block-000103; row label and correction evidence remain 000102/000104.
- Paragraph structure: 18 explicitly numbered headings recovered from Normal-style paragraphs; ordinary ListBullet entries are not promoted to headings.
- Scope: WP2 gate and WP4 table-row scope are structured only where source labels establish them. Uncertain system/WP mappings remain needs_review.

## Profile 104 reconciliation

- consistent: 39
- needs_review: 44
- profile_only: 21

The CSV records all 104 fields, previous status, new status and evidence IDs. There are no Profile-invented DOCX evidence IDs. Values in project_profile.json were not changed.

The remaining 21 profile_only entries are metadata, unmentioned optional alternatives/prohibitions/blocker records, and topology requirements for which no corresponding source assertion was found. Related but insufficient source statements are needs_review, including the unnumbered orientation mention, MACE threshold, spin lists, WP3 candidate/gas fields, WP5 sensitivity counts and atom-indexed topology requirements.

## Automated verification

Actions runs #517 and #518 on d66570408fb3682bfc36c029bc9c5e645657bcfd both passed:

- 128 tests total
- 126 passed
- 2 optional upstream integration tests skipped
- 0 failures / 0 errors
- python -m compileall -q pipeline_contracts tests examples passed

The new run_04 regression module covers the three original conflict classes, true conflicting values, real table-cell ADDED_MOS extraction, numbered headings/ListBullet boundaries, unit handling and all 104 Profile reconciliation entries.

## Acceptance boundary

The diagnostic branch provided the extracted source blocks and all requested targeted evidence reports. The regression fixture uses those report-backed raw text blocks, their original evidence IDs and locations, and tests the compiler's Manifest creation/reconciliation paths. The Frozen DOCX binary and complete 160-block extraction package were not present in the evidence branch, so a complete read_frozen_docx() run on the original binary is not claimed. The targeted run_04 evidence repair and CI verification are complete; full binary-level DOCX acceptance remains a separate verification step.

## Unchanged safety boundaries

- P0 Windows GBK JSON stdout fix was already complete and was not re-developed.
- WP1_ORIENTATION_SCOPE_UNRESOLVED and WP1_FRAGMENT_SPIN_COUNT_MISMATCH remain blockers; no decision was selected.
- No resolve-v41-planning, no topology construction, no CP2K, HPC, Slurm or production DFT.
- Agent C / PR #4, main, PR #1 and PR #2 were not modified.
