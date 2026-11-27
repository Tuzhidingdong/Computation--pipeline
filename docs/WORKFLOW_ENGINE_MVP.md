# Calculation-plan workflow engine MVP

## Implemented

- JSON CalculationPlan v1.0; YAML when PyYAML is installed. Plan fields include scientific question, structure path/Artifact ID, full method, calculations and tool versions, backend alias, resource profile, outputs, analysis, QC and retry policy.
- Deterministic validation rejects missing XC/basis/pseudopotential/cutoff/SCF/charge/multiplicity and unregistered operations. It never generates Python or changes scientific settings.
- Initial DAG contains GEO_OPT only. ENERGY is dynamically added only after structured convergence QC passes and an optimized-structure Artifact with SHA256 is returned.
- SQLite persists plan snapshot/hash, DAG nodes, task states, HPC Job ID, attempts, events, results and recovery state. It is a workflow-control ledger only; Artifact/Evidence remain Data_analysis-owned.
- Resume passes an existing Job ID to the adapter; it does not resubmit the same task. Input/method changes alter deterministic task identity.
- CLI: plan, validate, run, status, resume, report.
- Mock E2E covers convergence/non-convergence, dynamic ENERGY insertion, network interruption with durable Job ID, recovery and Analysis Run/Evidence references.

## State and success rules

PENDING → READY → SUBMITTED → POSTPROCESSING → QC_PASSED → COMPLETED

Network loss after submission becomes INTERRUPTED_RECOVERY. Scheduler COMPLETED without application exit code 0 and expected output references is not success. A failed GEO_OPT QC does not create ENERGY. Execution is sequential under one visible coordinator.

## Real HPC integration blocker

Read-only upstream heads inspected: BeiLong_HPC 40ce15a9285e94f4abf1418361387e90e850a899; UCAS_hpc ebde5c1e76432d7e0d6728da804fb62dc5f84583.

Their job-record scripts expose create/update/sync/show/list. The Skills describe safe staging/submission/monitoring/retrieval, but neither repository exposes a stable callable Python API or CLI for complete stage-inputs → submit → poll → selective-retrieve. The record scripts assume a Slurm Job ID already exists; they do not stage or submit. Their sync subcommand queries an existing Job ID. A natural-language Skill instruction is not a programmatic endpoint.

This increment therefore adds no parallel SSH/SCP/Slurm code and invents no upstream CLI commands. A real adapter cannot be enabled until an owner-approved machine-callable interface is supplied or identified. Without an injected adapter, production CLI returns UNAVAILABLE. No cluster preflight, SSH, SCP, Slurm submission, cancellation or retrieval was run. Per-backend credentials, paths and security rules remain in private upstream repositories.

## jobflow decision

jobflow supports Job, Flow and dynamic Response expansion. It is not adopted because official documentation says its default MemoryStore is process-local; persistent production use generally requires a Maggma store such as MongoDB. Remote queue execution uses separate managers such as FireWorks or jobflow-remote, which do not directly bind the existing HPC Skill interfaces. Introducing a separate JobStore and remote manager would add infrastructure beside the required SQLite control ledger and Skill-owned HPC operations.

We reuse the dynamic result-driven graph concept and implement the narrowly scoped SQLite controller. No jobflow, AiiDA, FireWorks, Parsl or atomate2 dependency is added. Official references:
- https://materialsproject.github.io/jobflow/tutorials/5-dynamic-flows.html
- https://materialsproject.github.io/jobflow/stores.html
- https://github.com/materialsproject/jobflow

## Not yet validated

- No real CP2K input generation/calculation, real CST QC, real HPC Skill lifecycle, real Data_analysis Reader, scientific QC or production report has run end-to-end.
- Mock Artifact references/hashes are synthetic, not hashes of real output bytes.
- Retry policy is retained/validated but automatic retry execution is not implemented.
- Only GEO_OPT → ENERGY is supported; PDOS/charge branches and arbitrary user-declared branches remain future registered operations.
