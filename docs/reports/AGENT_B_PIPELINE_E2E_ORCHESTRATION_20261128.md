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
