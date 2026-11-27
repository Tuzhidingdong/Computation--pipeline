# Development Status — coordination-dft-publication-pipeline

Governing objective: TASK_PLAN_v1.0.0.md (preserved unchanged). This status separates implemented control-flow code from real scientific/HPC validation.

## Repository
- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/pipeline-mock-contracts-20261127
- Existing PR #1: Open / Draft / unmerged.
- This work modifies this repository only. Upstream Skill repositories remain read-only.
- No production DFT/AIMD, remote HPC, SSH/SCP, Slurm preflight or Slurm submission was performed.

## Workflow Engine increment

| Capability | Status | Evidence / limitation |
|---|---|---|
| Versioned CalculationPlan JSON v1.0 | IMPLEMENTED | pipeline_contracts/calculation_plan.py |
| YAML plan input | IMPLEMENTED — optional dependency | Requires PyYAML; JSON works with standard library |
| Scientific parameter validation | IMPLEMENTED — schema-level | Required method fields checked; scientific appropriateness is not certified |
| Deterministic initial DAG | IMPLEMENTED — CP2K GEO_OPT | Stable task key includes plan/structure/method hash |
| Dynamic GEO_OPT → ENERGY | IMPLEMENTED — Mock tested | ENERGY created only after convergence gate and hashed optimized-structure Artifact |
| SQLite Workflow Run/task/attempt/event ledger | IMPLEMENTED | workflow-control state only, not Artifact/Evidence |
| Resume without duplicate submit | IMPLEMENTED — Mock tested | Persisted Job ID passed to adapter after simulated network interruption |
| CLI plan/validate/run/status/resume/report | IMPLEMENTED | python -m pipeline_contracts.cli |
| Mock scheduler/application/QC lifecycle | IMPLEMENTED — synthetic | No CP2K binary, HPC or scientific data |
| Real CST input generation/output QC | NOT YET INTEGRATED | Existing RealCSTAdapter exists; controller binding incomplete |
| Real HPC lifecycle for BeiLong / UCAS | BLOCKED — upstream callable interface gap | Job-record scripts provide create/update/sync/show/list; no complete stage/submit/poll/selective-retrieve CLI/API |
| Real Data_analysis in full GEO_OPT→ENERGY run | NOT YET INTEGRATED | Existing RealDataAnalysisAdapter remains available for post-processing; workflow binding outstanding |
| Automated infrastructure retry policy | NOT IMPLEMENTED | Policy retained/validated in plan; automatic retry loop not implemented |
| PDOS/charge/other result branches | NOT IMPLEMENTED | Current bounded graph is CP2K GEO_OPT→ENERGY |

## External workflow library decision

jobflow is not added. It supports dynamic Response/Flow expansion, but default MemoryStore is process-local; persistent stores typically use Maggma-backed databases. Remote queue execution requires a separate manager (e.g. FireWorks/jobflow-remote) and does not directly bind existing HPC Skill interfaces. A lightweight SQLite control ledger is a better fit. Rationale and official references are in docs/WORKFLOW_ENGINE_MVP.md.

## HPC Skill read-only findings
- BeiLong_HPC inspected at HEAD 40ce15a9285e94f4abf1418361387e90e850a899.
- UCAS_hpc inspected at HEAD ebde5c1e76432d7e0d6728da804fb62dc5f84583.
- Job-record tools are useful for records/status sync after a Job ID exists. Skill-level staging/submission/retrieval procedures are not exposed as a complete programmatic API. No new SSH/SCP/Slurm implementation was added.

## Tests
Previous baseline CI run 45936035658 tested the earlier 37-test version only. New workflow tests are in tests/test_workflow.py; current increment CI verification is pending.

## Workflow states
PENDING, READY, SUBMITTED, QUEUED, RUNNING, POSTPROCESSING, QC_PASSED, COMPLETED, RETRY_WAIT, BLOCKED, FAILED_PERMANENT, CANCELLED and INTERRUPTED_RECOVERY. COMPLETED requires scheduler completion, application exit code 0, output references and applicable result/QC gate. Scheduler COMPLETED alone is insufficient.

## Next blockers
1. Obtain/approve callable stage/submit/poll/selective-retrieve interfaces from each HPC Skill without modifying them here.
2. Bind RealCSTAdapter to actual CP2K input generation and GEO_OPT/ENERGY output validation.
3. Bind RealDataAnalysisAdapter to retrieved ArtifactRefs and require real Analysis Run/Evidence references.
4. Implement bounded infrastructure retry; never alter scientific settings without explicit authorization.
