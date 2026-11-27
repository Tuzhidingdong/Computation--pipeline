# Development Status — coordination-dft-publication-pipeline

Governing objective: TASK_PLAN_v1.0.0.md remains unchanged and authoritative. This status separates code/test evidence from real-cluster and scientific verification.

## Repository and branch protection

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/pipeline-mock-contracts-20261127
- Existing PR #1: Open / Draft / unmerged.
- PR base and main are at the original base SHA cf5adb90cd2e1fc24da2d08fcff160d63cf3574a.
- BeiLong_HPC, UCAS_hpc, Data_analysis and chem-scitoolkit are read-only dependencies in this phase.
- No live cluster SSH/SCP, sbatch, production CP2K/DFT/AIMD, cancellation or real output retrieval was performed.

## Real CP2K GEO_OPT → ENERGY

| Capability | Status | Evidence / boundary |
|---|---|---|
| Real adapter factory | IMPLEMENTED | build_real_workflow_adapter(plan, project_root, runtime_config); explicit UNAVAILABLE reason; no Mock fallback |
| Local-only runtime config | IMPLEMENTED | .pipeline/runtime.local.example.json; private runtime.local.json is Git-ignored; relative local paths resolved from config location |
| Real CST CP2K input generation | IMPLEMENTED — fake API tested | Reuses RealCSTAdapter and chem-scitoolkit CP2KInputBuilder.build_finite_system(); CalculationPlan now requires relative cutoff, Poisson solver, UKS/centering and full cell angles instead of accepting builder defaults. |
| CST input lint | IMPLEMENTED — fake API tested | Calls upstream validate_cp2k_input(); local ASE and cp2klint are required |
| BeiLong_HPC backend | IMPLEMENTED — injected subprocess tested | Dedicated SSH config for both SSH/SCP, wcl privacy header/job name, opaque workspace, external Skill log directory, upstream Job Record script |
| UCAS_hpc backend | IMPLEMENTED — injected subprocess tested | Existing hpc alias, CP2K Slurm template/module setup, configured account/resources, upstream Job Record script |
| Staged input SHA-256 | IMPLEMENTED — injected subprocess tested | Local and remote per-file digests compared before submission |
| Submission intent + Job ID persistence | IMPLEMENTED — SQLite callback tested | Intent and input hashes committed before sbatch; returned Job ID committed immediately |
| Lost sbatch response reconciliation | IMPLEMENTED — fake subprocess tested | Search by opaque work directory; uncertain result becomes SUBMISSION_UNKNOWN; no duplicate sbatch |
| Known Job ID resume | IMPLEMENTED — fake real-adapter test | Reattaches prepared context and checks original Job ID, without second submission for the same task |
| Scheduler/application separation | IMPLEMENTED — tests | Slurm COMPLETED alone is not success; exit code must be known and zero |
| Output retrieval and integrity | IMPLEMENTED — fake adapter/runner tests | Selective CP2K output, optimized geometry and scheduler logs; local/remote hashes checked |
| Data_analysis intake and derived input | IMPLEMENTED — injected API test | register_inputs → resolve; derived input under data/derived → register_derived_artifact(parent structure Artifact ID) → resolve |
| Retrieved Data_analysis source Artifacts | IMPLEMENTED — injected API test | Output/logs first staged outside Data_analysis; then register_inputs and resolver/SHA verification |
| CST output QC/version | IMPLEMENTED — fake CST test | Normal termination, SCF, GEO_OPT completion and CP2K version must match plan |
| Dynamic ENERGY | IMPLEMENTED — fake Real adapter E2E | Only after GEO_OPT convergence and registered optimized-structure Artifact SHA; ENERGY reads the final trajectory frame |
| Analysis Run / Evidence | IMPLEMENTED — injected Data_analysis test | Existing DFT operation/reader/provenance/evidence APIs; true Job ID and Artifact IDs/SHA passed |
| CLI real mode | IMPLEMENTED | plan/validate/preflight/run/status/resume/report; --mock must be explicit |
| SQLite run lock | IMPLEMENTED — unit test | Prevents two processes/controllers from executing one Workflow Run concurrently |
| Automatic retry loop | NOT IMPLEMENTED | No automatic retry; terminal failures are not restarted by ordinary resume |
| Real cluster execution | NOT YET VERIFIED | Requires user local config, read-only preflight and separately approved run |

## Data_analysis Artifact lookup boundary

- A supplied Artifact ID is resolved using Data_analysis and its registered bytes are re-hashed.
- An external source file is registered through register_inputs(); the returned Artifact ID is resolved and re-hashed.
- Data_analysis exposes no public lookup-by-path/SHA operation that returns the already registered Artifact ID. For a path already under data/original_received/, the user must supply the existing Artifact ID. The adapter refuses to re-intake this managed path.
- Pipeline does not read/write Data_analysis registry JSON and does not copy its path-safety or SHA implementation.
- Generated CP2K input is stored under data/derived/ with a task-specific unique filename and parent Artifact ID. Remote task filenames and Slurm-visible labels remain generic.
- HPC outputs are staged outside Data_analysis raw intake and then registered through register_inputs().

## HPC Skill revisions inspected

- BeiLong_HPC: read-only skill/scripts/templates inspected. Dedicated config_bscc_a, fixed wcl name, opaque remote workspace and external hpc/logs path are retained.
- UCAS_hpc: read-only skill/scripts/templates inspected. The existing hpc alias, module initialization, account/partition/resource profile and selective retrieval behavior are retained.
- Neither repository was modified. The adapter uses subprocess with timeout/return code/bounded diagnostics and invokes the existing Job Record scripts. No Paramiko/AsyncSSH or parallel Slurm implementation was introduced.

## Verification

Latest successful Actions run before the final docs/runtime-config test commit: 72 tests, 70 passed, 2 optional upstream tests skipped; compileall passed.

The suite uses injected command runners and fake HPC/CST/Data_analysis implementations. Tests cover:
- BeiLong/UCAS command construction and SSH config differences;
- script privacy, upload hash checks and Job Record commands;
- submission intent, Job ID persistence, lost-response reconciliation and resume;
- one-controller lock, terminal failure/resume rules and application/scheduler failure classification;
- Data_analysis intake/derived registration order and Analysis Run/Evidence mapping;
- fake Real adapter GEO_OPT → ENERGY, non-convergence, missing output/hash failure and known-job resume.

No test connects to a real cluster or runs a real CP2K calculation. The two optional upstream-source tests are skipped unless the owner configures those source checkouts in CI.

## Workflow states and safety

Persisted states include PENDING, READY, SUBMITTING, SUBMITTED, QUEUED, RUNNING, POSTPROCESSING, QC_PASSED, COMPLETED, RETRY_WAIT, BLOCKED, FAILED_PERMANENT, FAILED_INFRASTRUCTURE, CANCELLED, INTERRUPTED_RECOVERY, SUBMISSION_UNKNOWN and UNAVAILABLE.

- Submission intent and remote working directory are durable before sbatch.
- Known Job IDs are queried on resume, never resubmitted.
- A lost sbatch response is reconciled; unresolved state blocks instead of risking a duplicate submission.
- Slurm COMPLETED alone is not scientific success.
- FAILED_PERMANENT, FAILED_INFRASTRUCTURE and CANCELLED are terminal for ordinary resume.
- Scientific parameters are never automatically changed.
- Monitoring is a single remote status check per resume invocation, not a resident background poller.

## Remaining real-environment checks

1. Copy .pipeline/runtime.local.example.json to the local Data_analysis project and fill the paths/aliases/resources already approved for the chosen backend.
2. Ensure the approved Data_analysis and chem-scitoolkit Python environments, ASE and cp2klint are available.
3. Run the documented read-only CLI preflight and inspect every UNAVAILABLE diagnostic.
4. Review the actual CalculationPlan and resource profile.
5. Only after user approval, execute GEO_OPT → ENERGY and inspect its real Analysis Run, Evidence Package and workflow report.

No production job is submitted automatically by CI or by the development agent.
