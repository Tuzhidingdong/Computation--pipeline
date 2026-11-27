# Coordination DFT Publication Pipeline

Reusable scientific-computing orchestration for approved atomistic structures and deterministic CP2K calculation protocols.

## Governing objective

TASK_PLAN_v1.0.0.md remains unchanged and authoritative. The target lifecycle is:

**CalculationPlan → task DAG → CP2K input generation → existing HPC Skill → monitoring/retrieval → CST validation → Data_analysis → result-driven next tasks → complete report.**

The original synchronous PipelineRunner remains the foundational post-processing node.

## Implemented in Agent B branch

- Versioned CalculationPlan v1.0 with required scientific method, input, runtime, output and QC validation.
- Stable GEO_OPT task identity includes the SHA-256 of the resolved input Artifact bytes.
- SQLite Workflow Run, task, attempt, submission-intent, Job ID, event and recovery state.
- Dynamic ENERGY creation only after CST confirms GEO_OPT convergence and a registered optimized-structure Artifact exists.
- Real adapter factory and local-only runtime configuration; Real execution never falls back to Mock.
- BeiLong_HPC and UCAS_hpc adapters using their existing SSH/SCP conventions, Slurm templates and Job Record scripts.
- Existing Data_analysis APIs for input intake, Artifact resolution, derived Artifact registration, Analysis Run and Evidence Package.
- CLI: plan, validate, preflight, run, status, resume and report.
- Explicit Fake/Mock adapter tests, including the Real adapter lifecycle from GEO_OPT to ENERGY and Data_analysis Evidence.

**Real adapter code is implemented, but it has not been run against a live cluster or a real CP2K calculation.** Passing injected tests does not certify the user's local installation, credentials, cluster status or scientific results.

Detailed local setup, backend configuration, read-only checks, recovery semantics and limitations: [docs/REAL_CP2K_HPC_INTEGRATION.md](docs/REAL_CP2K_HPC_INTEGRATION.md).

## Frozen plan compilation and v4.1 model lifecycle

The independent development branch `agent-b/plan-compiler-v41-model-plugin-20261127` adds:
- `pipeline_contracts.plan_compiler`: standard-library DOCX extraction with paragraph/table source locations, evidence-backed claims, and conflict diagnostics.
- `projects.corr_dft_v4_1.plan_compiler.compile_v41_docx()`: project-profile injection and v4.1 planning blockers.
- `projects.corr_dft_v4_1.model_plugin`: explicit atom/bond graph contract, deterministic coordinate-transform candidate generation, structure validation, Data_analysis Artifact registration bridge, review package and hash-pinned approval.
- `pipeline_contracts.project_lifecycle.ProjectLifecycle`: pre-model stages persisted in the existing WorkflowStore SQLite database; approved Artifact ID/SHA handoff into the existing CalculationPlan controller.

Known v4.1 blockers are intentionally reported rather than guessed: the scope of the 15 WP1 orientations is unresolved, and the detailed isolated-fragment spin list contains six candidates while the summary says four. The project profile preserves both statements. Model construction also requires the actual frozen source definitions, explicit chemical topology/donor assignments and reproducible 3D construction constraints; formulas alone are not treated as a structure.

The current builder transforms a fully specified atom graph. It is not yet a topology inference engine or a substitute for a missing v4.1 atom graph. No real v4.1 model candidate has been claimed or approved.

### Plan compiler CLI

```bash
computation-pipeline compile-v41-docx frozen-plan.docx --plan-version v4.1 --output project-manifest.json
computation-pipeline confirm-manifest project-manifest.json --evidence-id docx-block-000012 --confirmed-by "project owner" --rationale "Confirmed against frozen source table" --output confirmed-manifest.json
computation-pipeline resolve-v41-planning confirmed-manifest.json --orientation-scope per_catalyst --fragment-spin-resolution preserve_detailed_six_correct_summary --confirmed-by "project owner" --rationale "Preserve all six detailed spin cases and correct the summary" --output resolved-manifest.json
computation-pipeline compile-calculation-plan resolved-manifest.json approved-calculation-plan.json
```

The two v4.1 resolutions above are explicit owner decisions; the CLI never applies them automatically.

The v4.1 model plugin exposes `generate_validate_review()` to run deterministic candidate generation, validation, Data_analysis Artifact registration and review. It stops at `AWAITING_APPROVAL`; call `approve_candidate()` only after the owner has reviewed the package. `ProjectLifecycle.create_calculation_run()` then verifies the immutable approval and hands the exact Artifact ID/SHA to the existing CalculationPlan DAG.

## Quick start

    python -m pipeline_contracts.cli plan .\calculation-plan.json
    python -m pipeline_contracts.cli validate .\calculation-plan.json
    python -m pipeline_contracts.cli preflight .\calculation-plan.json --runtime-config .\.pipeline\runtime.local.json
    python -m pipeline_contracts.cli run .\calculation-plan.json --mock
    python -m pipeline_contracts.cli run .\calculation-plan.json --runtime-config .\.pipeline\runtime.local.json

Copy .pipeline/runtime.local.example.json to .pipeline/runtime.local.json inside the Data_analysis project root. Fill in local Skill paths, OpenSSH paths, existing SSH aliases, private backend workspace references, resource-profile values, and local basis/pseudopotential paths. The populated file is Git-ignored and must not be committed.

The CalculationPlan project_root must match data_analysis.project_root in the runtime config. The example plan contains illustrative settings only; replace them with the user's approved scientific method and resources.

## Resume and reporting

    python -m pipeline_contracts.cli status WORKFLOW_RUN_ID --state-db STATE_DB_PATH
    python -m pipeline_contracts.cli resume WORKFLOW_RUN_ID --state-db STATE_DB_PATH --runtime-config .\.pipeline\runtime.local.json
    python -m pipeline_contracts.cli report WORKFLOW_RUN_ID --state-db STATE_DB_PATH --output workflow_report.json

Resume queries a known Job ID and never resubmits that task. A lost sbatch response is reconciled using the persisted opaque remote work directory; unresolved submission state becomes SUBMISSION_UNKNOWN. FAILED_PERMANENT, FAILED_INFRASTRUCTURE and CANCELLED are not restarted by ordinary resume. Monitoring is one remote status check per resume invocation, not a resident background poller.

## Ownership boundaries

- Computation--pipeline: CalculationPlan, task DAG, workflow state, routing, recovery and report.
- chem-scitoolkit: CP2K input generation and CP2K input/output validation.
- BeiLong_HPC / UCAS_hpc: cluster-specific SSH/SCP/Slurm, templates, permitted paths and Job Record lifecycle.
- Data_analysis: Artifact intake/resolution, derived Artifact registration, Analysis Runs, provenance and Evidence.

No second Artifact Store, parser, SSH/SCP client, scheduler or persistent service is introduced. Upstream HPC repositories and Data_analysis remain read-only dependencies.

## External workflow library decision

jobflow was evaluated for dynamic Flow expansion. It was not adopted because persistent storage and remote execution would introduce another store/manager stack without directly binding the existing HPC Skills. The focused controller uses SQLite for workflow-control state only. See [docs/WORKFLOW_ENGINE_MVP.md](docs/WORKFLOW_ENGINE_MVP.md).

## Verification

    python -m unittest discover -s tests -v
    python -m compileall -q pipeline_contracts tests examples

Latest GitHub Actions evidence: 74 tests, 72 passed, 2 optional live upstream tests skipped; compileall passed. CI does not connect to either HPC system or run production calculations. See STATUS.md.
