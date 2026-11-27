# Calculation-plan workflow engine and real CP2K execution

## Workflow model

The computation workflow is driven by a versioned CalculationPlan, not by a prompt that directly executes arbitrary code.

**CalculationPlan → initial DAG → CST CP2K input → HPC Skill Job → output retrieval → CST QC → Data_analysis → result-driven DAG expansion → report**

The plan contains the source structure reference, full method configuration, explicit CP2K kinds/basis/pseudopotentials, cell/boundary settings, tool version, backend/resource profile, output declarations, analysis settings and quality gates. Missing or inconsistent required fields block execution; the coordinator does not invent scientific settings or generate arbitrary Python. Required CP2K method fields include XC, basis/pseudopotential, cutoff and relative cutoff, SCF method/tolerance/iteration limit, charge, multiplicity, per-KIND definitions, basis/potential filenames, cell/Poisson periodicity and solver, UKS and coordinate-centering flags. Finite-system cell lengths and all three angles must be explicit; fields previously defaulted by the builder are now plan-validation errors.

## Dynamic GEO_OPT → ENERGY rule

The initial plan compiles to a GEO_OPT task. ENERGY is not pre-created as a runnable task.

The real GEO_OPT executor must confirm:
- Slurm reports the terminal COMPLETED state;
- allocation exit code is known and equals zero;
- CP2K reports normal termination and SCF convergence;
- output CP2K version matches the version declared in the plan;
- CP2K reports geometry optimization completed;
- the optimized geometry file is selectively retrieved, hash-verified, registered in Data_analysis and resolved through its Artifact ID/SHA-256.

Only then does the controller persist the optimized-structure Artifact as the dependency and create the ENERGY node. ENERGY consumes the final frame of the optimized geometry trajectory, builds and validates a distinct CP2K input, then follows the same stage/submit/monitor/retrieve/verify/register path.

The GEO_OPT → ENERGY edge is tested with an injected fake HPC/CST/Data_analysis stack. It is not a scientific calculation result.

## Persistence and recovery

SQLite persists the Workflow Run, plan snapshot/hash, task identities, dependency edges, attempts, status transitions, remote work directory, input byte hashes, submission timestamp, Job ID, output Artifact references and diagnostics.

- The workflow run is protected by a SQLite transaction-backed process lock.
- A submission intent is committed before sbatch.
- The Job ID callback commits the returned Slurm Job ID immediately, before creating or synchronizing the upstream Job Record.
- Resume with a known Job ID queries that job and does not re-submit.
- A lost sbatch response is reconciled using the opaque remote work directory and backend-specific Slurm accounting. If submission existence cannot be established, the task becomes SUBMISSION_UNKNOWN and stops.
- Scheduler/transport failures are distinguished from CP2K application failures.
- FAILED_PERMANENT, FAILED_INFRASTRUCTURE and CANCELLED are terminal for ordinary resume. No science parameter is changed by recovery.
- There is no automatic retry loop or continuous background polling service. Each CLI resume performs a status/recovery pass; a running task returns RUNNING/QUEUED/SUBMITTED without being reported completed.

## Real adapter ownership

The public real Adapter Factory is:

    build_real_workflow_adapter(plan, project_root, runtime_config)

It binds the existing RealCSTAdapter, the selected HPC Runtime Adapter and the RealDataAnalysisAdapter. Missing configuration or dependencies produce a concrete UNAVAILABLE response. Real mode never falls back to Mock.

HPC Runtime Adapter backends:
- BeiLong_HPC: uses its dedicated Windows OpenSSH config for SSH and SCP, existing Skill privacy header, fixed wcl job name, permitted root, opaque work directories, Slurm commands and bscc_a_job_record.py.
- UCAS_hpc: uses the existing hpc SSH alias, existing CP2K Slurm template, configured Account/Partition/resources/modules and hpc_job_record.py.
- Both use bounded subprocess calls and explicit file selection. The two upstream HPC repositories are read-only; no SSH/SCP/Slurm clone or alternative Job Record format is created here.

Data_analysis remains the sole owner of Artifacts and Evidence:
- external structure file → register_inputs() → resolve_artifact_path();
- generated CP2K input under data/derived/ → register_derived_artifact(parent structure Artifact ID) → resolve_artifact_path();
- retrieved raw CP2K outputs/geometry/logs → register_inputs() → resolve_artifact_path();
- ENERGY output → existing RealDataAnalysisAdapter → Analysis Run + normalized derived Artifact + Evidence Package.

Data_analysis currently exposes no public lookup-by-path/SHA returning an existing Artifact ID. A structure already in data/original_received/ must be referenced by its existing Artifact ID; Pipeline does not inspect registry JSON. This limitation is explicit in the integration guide.

## CLI

    python -m pipeline_contracts.cli plan PLAN.json
    python -m pipeline_contracts.cli validate PLAN.json
    python -m pipeline_contracts.cli preflight PLAN.json --runtime-config RUNTIME.json
    python -m pipeline_contracts.cli run PLAN.json --mock
    python -m pipeline_contracts.cli run PLAN.json --runtime-config RUNTIME.json
    python -m pipeline_contracts.cli status WORKFLOW_RUN_ID --state-db STATE_DB
    python -m pipeline_contracts.cli resume WORKFLOW_RUN_ID --state-db STATE_DB --runtime-config RUNTIME.json
    python -m pipeline_contracts.cli report WORKFLOW_RUN_ID --state-db STATE_DB --output report.json

Only --mock starts the simulator. preflight is read-only with respect to Slurm submission; it checks local APIs/files and remote executable/module/Slurm command availability. It does not submit a job.

Detailed Windows local configuration, both backend examples and read-only preflight shell commands: docs/REAL_CP2K_HPC_INTEGRATION.md.

## jobflow evaluation

jobflow supports Job, Flow and dynamic Response expansion. It was evaluated but is not added as a dependency. Persistent operation would require a persistent Maggma store and a remote manager/queue integration; these would introduce additional infrastructure without binding the existing HPC Skill interfaces. The narrow SQLite controller reuses the dynamic result-driven graph concept while preserving a single workflow-control ledger and existing Artifact/Evidence ownership.

Official references:
- https://materialsproject.github.io/jobflow/tutorials/5-dynamic-flows.html
- https://materialsproject.github.io/jobflow/stores.html
- https://github.com/materialsproject/jobflow

## Validation evidence and limits

Latest Actions run on this branch: 72 tests, 70 passed, 2 optional upstream-source tests skipped; compileall passed. Tests cover the Mock DAG, injected SSH/SCP/Slurm command construction, submission reconciliation, process locking, Data_analysis API order, fake real-adapter GEO_OPT → ENERGY execution, failure gates, hashes and Evidence handoff.

GitHub Actions does not access real HPC. The actual user's SSH profile, cluster configuration, resource permissions, module availability, CP2K runtime, Data_analysis checkout and resulting scientific outputs remain unverified until a read-only local preflight and separately approved execution are performed.

Only GEO_OPT → ENERGY is supported by the bounded real adapter. PDOS, charge analysis, AIMD, arbitrary branching and automatic retry remain outside this increment.
