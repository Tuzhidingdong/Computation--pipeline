# Coordination DFT Publication Pipeline

An independent, reusable Skill and deterministic workflow engine for coordinating atomistic model review, CP2K DFT calculations on existing HPC Skills, reproducible numerical analysis, publication-quality figures and manuscript-ready computational reports.

## Governing objective

TASK_PLAN_v1.0.0.md remains the authoritative and unchanged project baseline. The intended lifecycle is:

Calculation plan → compiled task DAG → real calculation execution → monitoring/retrieval → CST validation → Data_analysis → result-driven next tasks → complete report.

The existing synchronous PipelineRunner is the foundational post-processing MVP only. It is one node in the larger workflow and is not the final workflow engine.

## Current implementation

See docs/WORKFLOW_ENGINE_MVP.md:
- Versioned JSON CalculationPlan v1.0; optional YAML when PyYAML is installed.
- Deterministic validation and initial GEO_OPT task compilation.
- SQLite Workflow Run/task/attempt/event persistence.
- Result-driven ENERGY expansion only after convergence QC and an optimized-structure Artifact hash.
- Resume with the persisted Job ID; no duplicate submission on the recovery path.
- CLI: plan, validate, run, status, resume, report.
- Mock lifecycle tests; Mock mode does not run CP2K or validate science.

Real HPC is not enabled. Both HPC Skills have job-record scripts, but the scripts start after a Slurm Job ID exists and do not expose complete machine-callable stage/submit/poll/retrieve APIs. Pipeline will not reimplement SSH/SCP/Slurm or pretend this gap is solved.

## Quick start

    python -m pipeline_contracts.cli plan examples/cp2k_geo_opt_energy_plan.json
    python -m pipeline_contracts.cli validate examples/cp2k_geo_opt_energy_plan.json
    python -m pipeline_contracts.cli run examples/cp2k_geo_opt_energy_plan.json --mock
    python -m pipeline_contracts.cli run examples/cp2k_geo_opt_energy_plan.json

The example plan contains demonstration method/resource values only. Replace them with the approved scientific configuration and existing backend resource-profile alias before use. Validation does not certify scientific appropriateness.

SQLite defaults to <project_root>/.pipeline/workflow.sqlite. Use --state-db to choose another path. Do not place secrets or private HPC configuration in the plan or repository.

## Existing post-processing MVP

PipelineRunner remains available for already registered CP2K outputs:
input Artifact → optional CST validation → Data_analysis Reader → derived Artifact → Analysis Run / Evidence.

See examples/postprocess_existing_cp2k_output.py. It is not a substitute for the workflow controller.

## Architecture and safety

- Computation--pipeline owns plan validation, task DAG, task identity, workflow state, routing, QC gates and report assembly.
- chem-scitoolkit owns CP2K construction/validation and specialist scientific utilities.
- Data_analysis owns Artifact registration/storage, Analysis Runs, provenance and Evidence.
- BeiLong_HPC and UCAS_hpc own their respective authentication, transfer, Slurm and job-record procedures.
- Scientific parameters are never modified automatically without an explicit authorized recovery rule.
- One coordinator; no hidden worker orchestration.
- Public CI runs no production calculations.

## Development

    python -m unittest discover -s tests -v
    python -m compileall -q pipeline_contracts tests examples

STATUS.md records implementation and real-integration gaps. Mock tests are not scientific validation.
