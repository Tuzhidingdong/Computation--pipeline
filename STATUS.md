## Follow-up — PR #5 Manifest and CalculationPlan input locks

Updated: 2026-11-28

### Git / PR

- PR #5: https://github.com/Tuzhidingdong/Computation--pipeline/pull/5
- Branch: `agent-b/pipeline-e2e-orchestration-20261128`
- Base: `agent-b/plan-compiler-v41-model-plugin-20261127` @ `58d3b06be63b7d9fd778ae39522908e0df6391a4`
- Manifest/Plan protection implementation: `d00cd6742566650cfe865c3375326d6935d498ed`
- New regression tests: `c1f876fde2150d1c4bc709f0c75d7c2fcc5dd950`
- Dedicated E2E CI step: `d5bd56e5bc7f1ced550c170039fc1e4bf66c1d52`
- PR #5 remains Open / Draft / Not merged.

### A. Evidence Review closes Manifest confirmation

`ProjectPipeline.confirm_evidence()` now accepts confirmation only when `PLAN_COMPILE == COMPLETED`, `EVIDENCE_REVIEW` is `RUNNING` or `BLOCKED`, and every downstream stage from `MODEL_GENERATE` through `RESULT_DELIVERY` remains `PENDING`.

- `EVIDENCE_REVIEW == COMPLETED` is rejected.
- Any downstream stage already started, completed, blocked, failed or awaiting approval is rejected.
- The guards run before loading/transforming the Manifest, updating the WorkflowStore row or writing `manifest.json`.
- Incremental confirmation is retained while Evidence Review is `BLOCKED` due to remaining unresolved source definitions, provided no downstream stage has started.

New regression `test_completed_evidence_review_rejects_manifest_confirmation_without_partial_write` drives the synthetic project through explicit evidence confirmation and model generation to `MODEL_APPROVAL == AWAITING_APPROVAL`. A later confirmation is rejected. It compares the raw database `manifest_json`, in-memory Manifest, on-disk Manifest SHA-256, confirmation count, Evidence Review stage record and every downstream stage record before and after rejection. All remain identical.

### B. Existing Workflow Run freezes its complete CalculationPlan

`ProjectPipeline.resume_mock()` now branches on the existing Workflow Run ID before writing a supplied CalculationPlan.

For an existing Workflow Run it:

1. Reads `plan_hash`, `plan_json` and `plan_id` from the same WorkflowStore.
2. Parses the stored JSON back to CalculationPlan and requires canonical normalized contents, Plan ID and SHA-256 to agree.
3. Checks the ProjectLifecycle `CALCULATION_PLAN` ID/SHA references against the same frozen Plan.
4. Recompiles the original `calculation_plan_input.json` after binding the already-approved Artifact ID/SHA and compares complete Plan ID, SHA-256 and normalized mapping.
5. Performs the same in-memory bind/normalize/compare for any newly supplied `calculation_plan_data`.
6. Checks the persisted final `calculation_plan.json` and its recorded file SHA.
7. Calls `WorkflowController.resume()` with the CalculationPlan reconstructed from WorkflowStore, not with the incoming or disk-recompiled Plan.

All mismatch/integrity checks run before writing Plan files, changing lifecycle stages, appending workflow events, altering task rows/Job IDs, or invoking Data_analysis. A first Workflow Run may still accept the complete Plan, bind the approved Artifact ID/SHA, validate it, persist the final Plan and then create the one existing Workflow Run. No second execution engine or state store was introduced.

The E2E-B regression now checks:

- Same Plan repeat-resume retains the same Workflow Run ID, Plan ID/hash/JSON, task count, exact task records and Job IDs.
- Completed GEO_OPT/ENERGY outputs are not re-executed: Data_analysis Artifact registrations, Analysis Runs and Evidence Packages do not increase.
- The final report still names the same Workflow Run.
- A newly supplied Plan with changed normalized content is rejected before either stored Plan file is overwritten; WorkflowStore Run/Task/Events, Plan JSON/hash, Job IDs/statuses, API registrations and final report bytes remain unchanged.
- A tampered on-disk `calculation_plan_input.json` is rejected rather than silently overwritten; it leaves WorkflowStore, tasks, events, final Plan and final report unchanged.

### Validation — Actions #587

https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46099199732

- New targeted regression module: `python -m pytest -q tests/test_project_pipeline_e2e.py` — **3 passed**.
- Full unittest discovery: **136 total; 134 passed; 2 skipped; 0 failures/errors**.
- Full pytest: **134 passed; 2 skipped; 108 subtests passed**.
- `python -m compileall -q pipeline_contracts tests examples` — **passed**.
- The two skipped checks remain optional upstream integration tests requiring owner-approved source trees; they are not counted as passes.

### Unchanged acceptance boundary

- E2E-A still preserves `WP1_ORIENTATION_SCOPE_UNRESOLVED` and `WP1_FRAGMENT_SPIN_COUNT_MISMATCH`; neither is resolved or bypassed.
- E2E-A remains an extracted run_04 evidence-block fixture, not original Frozen DOCX binary acceptance.
- E2E-B and the new regressions use synthetic fixtures and a test-only Data_analysis API Fake. No live Data_analysis connection was tested.
- No `project_profile.json` scientific value changed; no `resolve-v41-planning`; no SSH/SCP/Slurm/HPC/CP2K/production DFT.

---

# Current Development Status — Pipeline End-to-End Orchestration

Updated: 2026-11-28

## PR / baseline

- PR #5: https://github.com/Tuzhidingdong/Computation--pipeline/pull/5
- Branch: `agent-b/pipeline-e2e-orchestration-20261128`
- Base branch: `agent-b/plan-compiler-v41-model-plugin-20261127`
- Base SHA: `58d3b06be63b7d9fd778ae39522908e0df6391a4`
- Code HEAD validated by Actions #580: `6e3018a3c9f492e3705aa14a85ddb2c09054a12d`
- PR #5 remains Draft/open/unmerged. PR #3, #1, #2 and #4 remain unchanged.

## Pipeline orchestration delivered

- Added `pipeline_contracts/project_pipeline.py` to sequence existing compiler, Manifest confirmation, model plugin, approval, CalculationPlan and WorkflowController.
- Extended `ProjectLifecycle` with the evidence review, workflow execution and result delivery stages, retaining the existing WorkflowStore as the single SQLite control ledger.
- Added `project start/status/review/confirm/approve/resume/report` CLI commands.
- Model candidate generation requires explicit confirmed Manifest evidence and complete ModelSpecs. Explicit approval is required. CalculationPlan is pinned to the approved Artifact ID/SHA.
- Mock GEO_OPT/QC gates dynamic ENERGY task creation. Mock optimized/result Artifacts, Analysis Run and Evidence Package use the injected Data_analysis API interface. Mock outputs are expressly labelled non-scientific.

## E2E and CI

- E2E-A passed: run_04 extracted-block fixture preserves both WP1 blockers, Project Run becomes BLOCKED, and no model candidates or Workflow Run are created.
- E2E-B passed: synthetic DOCX → explicit ModelSpec/topology → validation/review → explicit confirmation/approval → Artifact freeze → CalculationPlan → Mock GEO_OPT → Mock ENERGY → Data_analysis API Fake Artifact/Analysis Run/Evidence Package → final report.
- Actions #580: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46097107400
- unittest: 135 total, 133 passed, 2 skipped, 0 failures/errors.
- pytest: 133 passed, 2 skipped, 108 subtests passed.
- compileall: passed.
- Two skipped tests require owner-approved upstream source trees; skipped tests are not counted as passed.

## Acceptance limits

- E2E-A consumes the existing extracted run_04 block fixture, not the original Frozen DOCX binary. E2E-B covers actual synthetic DOCX input/compile.
- E2E-B uses a test-only fake implementing the existing Data_analysis API calls. Live Data_analysis connection and original production project acceptance have not been run.
- This delivery executes Mock only; it does not call SSH/SCP/Slurm, HPC or CP2K/production DFT.
- Both WP1 blockers remain unresolved; no `resolve-v41-planning`, no real CORR topology generation and no project_profile.json scientific value changes.

Full task report: docs/reports/AGENT_B_PIPELINE_E2E_ORCHESTRATION_20261128.md

---

# Current Follow-up — Generic Manifest Boundary and Evidence Regression

Updated: 2026-11-28

- PR #3 remains Draft, open, unmerged.
- Base SHA remains 5e6e26fdf94efbac54182f819f4879c1aafb1d4d.
- Implementation and regression HEAD verified by Actions run #549: 5666a0c98a0f6bb4d660af29de12ea32966285a2.
- Full report: docs/reports/AGENT_B_GENERAL_LAYER_BOUNDARY_AND_EVIDENCE_REGRESSION_20261128.md.


The generic builder is also tested with project_id=corr_dft_v4_1 but without adapter callbacks; its Manifest must match the same input compiled under an unrelated project ID, apart from the project ID field itself. This verifies adapter opt-in is callback-driven, not project-ID-driven.

## Layer boundary

CORR v4.1-specific DOCX recognition and unresolved-field semantics are in projects/corr_dft_v4_1/docx_adapter.py. projects/corr_dft_v4_1/plan_compiler.py calls the adapter explicitly through compile_docx() callbacks. pipeline_contracts/plan_compiler/manifest.py contains reusable block/evidence parsing, heading and scope handling, and field conflict rules only. CHARGE numeric/explanation separation stays generic and preserves the complete source evidence.

Conflict detection is label-independent by default and no longer excludes all outputs. Only the explicit CORR adapter marks the exact ASE summary/detail pair as coexisting. Output fields are separated by artifact identity; competing values within one artifact still block.

## Tests and validation

Actions run #543: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46092520597

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
