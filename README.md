# Coordination DFT Publication Pipeline

Reusable scientific-computing orchestration for approved atomistic structures and deterministic CP2K calculation protocols.

## Governing objective

TASK_PLAN_v1.0.0.md remains unchanged and authoritative. The intended lifecycle is:

**CalculationPlan → task DAG → CP2K input generation → existing HPC Skill → monitoring/retrieval → CST validation → Data_analysis → result-driven next tasks → complete report.**

The original synchronous PipelineRunner is the foundational post-processing node, not the workflow engine itself.

## Current implementation

The current Agent B branch contains:

- Versioned CalculationPlan v1.0 JSON input and schema-level required-parameter validation.
- Stable GEO_OPT task identity including the resolved source Artifact SHA256.
- SQLite Workflow Run, task, attempt, Job ID, submission-intent, event and recovery state.
- Dynamic ENERGY task creation only after GEO_OPT CST convergence and a registered optimized-structure Artifact with SHA256.
- Real adapter factory, local-only runtime configuration and backend-specific HPC Skill wrappers for BeiLong_HPC and UCAS_hpc.
- Official Data_analysis register_inputs, resolve_artifact_path, register_derived_artifact, Analysis Run and Evidence interfaces.
- CLI: plan, validate, preflight, run, status, resume, report.
- Explicit Mock execution remains available only via --mock.

The real adapter code path is implemented, but no live cluster execution has been performed or validated. Fake subprocess/HPC/Data_analysis integration tests do not certify the owner's local installation, credentials, cluster or scientific result.

Detailed setup, backend behavior, read-only checks, recovery semantics and known limitations: docs/REAL_CP2K_HPC_INTEGRATION.md.

## Quick start

    python -m pipeline_contracts.cli plan .\calculation-plan.json
    python -m pipeline_contracts.cli validate .\calculation-plan.json
    python -m pipeline_contracts.cli preflight .\calculation-plan.json --runtime-config .\.pipeline\runtime.local.json
    python -m pipeline_contracts.cli run .\calculation-plan.json --mock
    python -m pipeline_contracts.cli run .\calculation-plan.json --runtime-config .\.pipeline\runtime.local.json

Copy .pipeline/runtime.local.example.json to .pipeline/runtime.local.json inside the Data_analysis project root. Fill in the local Skill paths, SSH/SCP executable paths, active project root, backend alias, resource-profile values, and local basis/pseudopotential file paths. The populated file is Git-ignored and must not be committed.

The CalculationPlan project_root must match data_analysis.project_root in the runtime config. The plan must supply complete, approved CP2K parameters and output requirements. The example file is illustrative only.

## Resume and reporting

    python -m pipeline_contracts.cli status WORKFLOW_RUN_ID --state-db STATE_DB_PATH
    python -m pipeline_contracts.cli resume WORKFLOW_RUN_ID --state-db STATE_DB_PATH --runtime-config .\.pipeline\runtime.local.json
    python -m pipeline_contracts.cli report WORKFLOW_RUN_ID --state-db STATE_DB_PATH --output workflow_report.json

Resume queries known Job IDs and reconciles a lost submission response by the saved opaque remote work directory. If submission cannot be proven either way, the workflow stays SUBMISSION_UNKNOWN; it does not issue a second sbatch. FAILED_PERMANENT and CANCELLED tasks are not restarted by ordinary resume.

## Architecture and ownership

- Computation--pipeline: CalculationPlan interpreter, DAG identity, workflow control state, execution routing, report and resume.
- chem-scitoolkit: CP2K input generation and task-aware input/output validation.
- BeiLong_HPC / UCAS_hpc: cluster-specific SSH/SCP/Slurm, templates, paths, job-record lifecycle and operating rules.
- Data_analysis: Artifact intake/resolution, derived Artifact registration, Analysis Runs, provenance and Evidence.

No second Artifact Store, CP2K parser, SSH/SCP implementation or Slurm scheduler is introduced. Only supported upstream Skill scripts/templates and documented commands are invoked.

## External workflow library decision

jobflow was evaluated for dynamic Flow expansion. It was not adopted because persistent storage and remote execution would introduce a separate store/manager stack without directly binding the existing HPC Skills. The narrow controller uses SQLite for workflow-control state only. See docs/WORKFLOW_ENGINE_MVP.md.

## Development and validation

    python -m unittest discover -s tests -v
    python -m compileall -q pipeline_contracts tests examples

No production DFT/AIMD/Slurm job is run by GitHub Actions. A successful Mock or fake-adapter test does not represent scientific validation or live HPC verification. See STATUS.md for current evidence.
