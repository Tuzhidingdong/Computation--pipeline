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

# Agent B — Pipeline End-to-End Orchestration

Updated: 2026-11-28

## Delivery

- PR #5: https://github.com/Tuzhidingdong/Computation--pipeline/pull/5
- Branch: `agent-b/pipeline-e2e-orchestration-20261128`
- Base: `agent-b/plan-compiler-v41-model-plugin-20261127` @ `58d3b06be63b7d9fd778ae39522908e0df6391a4`
- Code validation HEAD: `6e3018a3c9f492e3705aa14a85ddb2c09054a12d`
- PR #5 remains Draft, open and unmerged. PR #3, #1, #2 and #4 were not changed.

## Implemented call chain

`Frozen DOCX → project compiler → Manifest → evidence review/confirmation → ModelSpec → candidate generation → validation → review package/3D preview → explicit approval → frozen Artifact ID/SHA → CalculationPlan → WorkflowController → Mock GEO_OPT/QC → Mock ENERGY → Data_analysis Artifact/Analysis Run/Evidence Package API → final project report`.

The new `ProjectPipeline` is a sequencing layer. It uses the existing `WorkflowStore` SQLite ledger for the 11 project stages; it does not create a second workflow database or Artifact Store. DOCX source bytes are copied into the Project Run and SHA-256 checked. Manifest, claims, evidence IDs, compile diagnostics, confirmations, candidate/validation/approval records, CalculationPlan and Workflow Run references are persisted.

Model generation, validation, review and approval call the existing CORR v4.1 model-plugin functions. The ModelSpec must supply explicit atoms, positions, bonds, fragments, donor atoms and transforms; its evidence IDs must be from the source Manifest and explicitly confirmed. Validation failure or missing preview blocks progression. Approval is explicit and checks the registered Data_analysis ArtifactRef, validation hash and current structure bytes before freezing the Artifact ID/SHA.

CalculationPlan is compiled only after the freeze and must reference the same Artifact ID/SHA. The existing `WorkflowController.create()` and Mock adapter run the DAG. ENERGY is only created after GEO_OPT convergence/QC. The Mock adapter registers the optimized-structure mock file and Mock analysis-result file through the injected Data_analysis API contract; the Analysis Run and Evidence Package are persisted through that API contract, with the mock-only/non-scientific label retained. No real CP2K calculation is represented.

## CLI

Examples (use the same `--state-db` and `--output-root` for each command):

```bash
python -m pipeline_contracts.cli project start frozen.docx --project-id corr_dft_v4_1 --compiler corr_dft_v4_1 --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs
python -m pipeline_contracts.cli project status <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs
python -m pipeline_contracts.cli project review <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs
python -m pipeline_contracts.cli project confirm <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs --evidence-id docx-block-000001 --confirmed-by <USER> --rationale "<basis>" --changes '{"decision":"<what was confirmed>"}'
python -m pipeline_contracts.cli project resume <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs --mode mock --integration-factory <module:function> --model-spec model_specs.json --calculation-plan calculation_plan.json
python -m pipeline_contracts.cli project approve <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs --candidate-id <CANDIDATE_ID> --approver <USER> --approve
python -m pipeline_contracts.cli project resume <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs --mode mock --integration-factory <module:function>
python -m pipeline_contracts.cli project report <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root .pipeline/project_runs
```

The integration factory must return the already-existing Data_analysis API object and preview renderer (plus an optional structure writer/validator). `project resume` is deliberately Mock-only in this delivery. Confirmation and approval are separate explicit user actions; no single-command auto-approval path was added.

## E2E results

- **E2E-A — WP1 block:** passed. The existing run_04 extracted-block fixture retains both `WP1_ORIENTATION_SCOPE_UNRESOLVED` and `WP1_FRAGMENT_SPIN_COUNT_MISMATCH`; Project Run is `BLOCKED`; no model candidates or Workflow Run are created; CLI status/review expose the blockers and evidence.
- **E2E-B — synthetic Mock pass:** passed. A synthetic DOCX is compiled; explicitly specified two-atom topology is built and ASE-validated; review preview is generated; confirmation and approval are explicitly invoked; the exact candidate Artifact ID/SHA is frozen and bound into CalculationPlan; Mock GEO_OPT creates the optimized Artifact only after QC; Mock ENERGY creates a Data_analysis-registered mock result Artifact, persisted Analysis Run and Evidence Package; the final report records the source and provenance chain.
- The E2E-A fixture is the existing extracted-block fixture, not the original Frozen DOCX binary. Its Project Run source path is a test fixture file; this is not claimed as binary-level DOCX acceptance.
- E2E-B uses a test-only Data_analysis API fake implementing the existing public Artifact/Analysis Run/Evidence Package calls. A live Data_analysis installation/API connection has not been exercised.

## CI on the code HEAD

Actions PR run #580: https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46097107400

- unittest: 135 total; 133 passed, 2 skipped; zero failures/errors.
- pytest: 133 passed, 2 skipped, 108 subtests passed.
- compileall: `python -m compileall -q pipeline_contracts tests examples` passed.
- The two skips are optional live upstream integration checks that require owner-approved `CHEM_SCI_TOOLKIT_SOURCE_ROOT` and `DATA_ANALYSIS_SOURCE_ROOT` checkouts. They are not counted as passes.

## Limits and safety

- Only Mock workflow execution was run. No SSH, SCP, Slurm, BeiLong_HPC, UCAS_hpc, CP2K or production DFT task was invoked.
- No real CORR v4.1 topology was generated. No chemistry, donor atom or coordinate was inferred.
- `WP1_ORIENTATION_SCOPE_UNRESOLVED` and `WP1_FRAGMENT_SPIN_COUNT_MISMATCH` remain unchanged blockers. No `resolve-v41-planning` command was used.
- `projects/corr_dft_v4_1/project_profile.json` was not changed.
- PR #5 is Draft and must not be treated as merged or production accepted. Original DOCX binary acceptance, live Data_analysis integration and real/HPC execution remain separate acceptance steps.
