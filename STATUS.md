# Development Status — coordination-dft-publication-pipeline

Governing objective: TASK_PLAN_v1.0.0.md (preserved unchanged). This file distinguishes implemented code/tests from live external-system and scientific validation.

## Repository

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/pipeline-mock-contracts-20261127
- Existing PR #1: Open / Draft / unmerged.
- Upstream repositories are read-only in this phase.
- No SSH/SCP connection to a cluster, live Slurm submission, production DFT/AIMD, cancellation or output retrieval was performed during development.

## Real CP2K GEO_OPT → ENERGY integration

| Capability | Status | Evidence / boundary |
|---|---|---|
| Real adapter factory | IMPLEMENTED | build_real_workflow_adapter(plan, project_root, runtime_config); explicit Unavailable reason; no Mock fallback |
| Local runtime config | IMPLEMENTED | .pipeline/runtime.local.example.json; populated runtime.local.json ignored by Git |
| Real CST input generation | IMPLEMENTED — fake API tested | Reuses RealCSTAdapter and existing CP2KInputBuilder; input registered with Data_analysis |
| CST CP2K input lint | IMPLEMENTED — fake API tested | Calls upstream validate_cp2k_input; needs local basis/potential files for path resolution |
| BeiLong_HPC backend wrapper | IMPLEMENTED — injected subprocess tested | Dedicated SSH config for SSH/SCP, wcl privacy header/job name, opaque workdir, Skill Job Record script, external logs directory |
| UCAS_hpc backend wrapper | IMPLEMENTED — injected subprocess tested | hpc alias, upstream CP2K Slurm template, module initialization, account/resources, Skill Job Record script |
| Upload SHA256 | IMPLEMENTED — fake subprocess tested | Local and remote hashes compared before submission |
| Submission intent + Job ID persistence | IMPLEMENTED — SQLite callbacks tested | Intent saved before sbatch; Job ID saved in callback immediately after response |
| Lost sbatch response reconciliation | IMPLEMENTED — fake subprocess tested | Search by opaque WorkDir using squeue/sacct; unresolved state becomes SUBMISSION_UNKNOWN, no duplicate submission |
| Known Job ID resume | IMPLEMENTED — controller and adapter tests | Existing job is queried; normal resume does not call sbatch for known Job ID |
| Scheduler/application separation | IMPLEMENTED — tests | Slurm COMPLETED stays AWAITING_VALIDATION; requires known exit code 0 and CP2K/CST checks |
| Selective output retrieval/hash verification | IMPLEMENTED — fake subprocess/HPC tests | CP2K output, optimized geometry and Slurm logs; backend-specific BeiLong log directory |
| Data_analysis intake/derived Artifact | IMPLEMENTED — injected API tests | register_inputs → resolve, and register_derived_artifact(parent Artifact ID) → resolve/hash |
| CST output QC and CP2K version match | IMPLEMENTED — fake CST test | Normal termination, SCF, GEO_OPT completion, required CP2K version |
| Dynamic ENERGY creation | IMPLEMENTED — Mock and fake real adapter tests | Only after convergence and registered optimized-structure Artifact SHA |
| Analysis Run/Evidence handoff | IMPLEMENTED — injected Data_analysis test | Output Artifact ID/SHA and upstream Job ID passed to existing adapter |
| CLI real-mode entry | IMPLEMENTED | plan/validate/preflight/run/status/resume/report; --mock explicit |
| Cross-process run lock | IMPLEMENTED — unit test | SQLite lock prevents two controllers simultaneously running the same Workflow Run |
| Automatic infrastructure retry | NOT IMPLEMENTED | Recoverable failures retain task/job/intent; no automatic retry loop |
| Live HPC/real CP2K validation | NOT YET PERFORMED | Must be exercised in the user's local environment after runtime config/preflight |

## Data_analysis Artifact intake boundary

- A supplied Artifact ID is resolved with Data_analysis and the registered SHA256 is checked.
- A path outside Data_analysis intake is passed through official register_inputs(); the returned Artifact ID is resolved and rehashed.
- A path already inside data/original_received/ is not re-intaked. Supply its existing Artifact ID.
- The inspected public Data_analysis API does not expose a lookup-by-path/SHA returning the existing Artifact ID. Pipeline does not read registry JSON. Exact duplicate handling for an external path is left to Data_analysis register_inputs(); that API can create a new intake record with its internal exact-duplicate link but does not return the duplicate target metadata.
- Generated CP2K input is written under data/derived/ and registered with the true parent structure Artifact ID. HPC output is staged outside Data_analysis's retained raw intake area and then registered with register_inputs().

## HPC Skill read-only revisions inspected

- BeiLong_HPC: 40ce15a9285e94f4abf1418361387e90e850a899
- UCAS_hpc: ebde5c1e76432d7e0d6728da804fb62dc5f84583

The adapters use the installed Skill scripts/templates and documented command conventions. They do not contain private SSH identities, credentials or cluster directories. Upstream repositories were not changed.

## External workflow library decision

jobflow is not added. Its dynamic Response/Flow model is relevant, but persistent stores and remote queue managers would add infrastructure without directly binding the current HPC Skills. This phase keeps SQLite as a local workflow-control ledger and retains the Data_analysis Artifact/Evidence ownership boundary. The evaluation is in docs/WORKFLOW_ENGINE_MVP.md and the real integration details are in docs/REAL_CP2K_HPC_INTEGRATION.md.

## Verification

- The most recent CI results are linked from PR #1. The newest run after the last real-adapter test adjustment is pending.
- Tests use injected subprocess, Fake HPC, Fake CST and Fake Data_analysis APIs. They do not access clusters or certify the owner's exact local Skill checkout/runtime.
- Optional live Data_analysis/CST source tests remain opt-in and may be skipped by public CI.

## Workflow states and safety

The controller persists PENDING, READY, SUBMITTING, SUBMITTED, QUEUED, RUNNING, POSTPROCESSING, QC_PASSED, COMPLETED, RETRY_WAIT, BLOCKED, FAILED_PERMANENT, CANCELLED, INTERRUPTED_RECOVERY, SUBMISSION_UNKNOWN and UNAVAILABLE.

- Submission intent and remote working directory are durable before sbatch.
- A known Job ID is polled rather than resubmitted.
- An uncertain sbatch response must be reconciled; otherwise the task is SUBMISSION_UNKNOWN.
- Slurm COMPLETED alone is not scientific success.
- Ordinary resume does not restart FAILED_PERMANENT or CANCELLED tasks.
- Scientific parameters are not changed by infrastructure recovery.

## Remaining real-environment checks

1. Install/activate the owner-approved Data_analysis and chem-scitoolkit source environments and complete the local runtime file.
2. Run the read-only preflight CLI for the chosen backend and confirm CP2K version and basis/pseudopotential availability.
3. Review the generated CalculationPlan input and resource profile.
4. Only then use run to submit the approved GEO_OPT/ENERGY workflow.
5. Inspect the generated report and the real Data_analysis Analysis Run/Evidence records.

No production job is submitted automatically by CI or by the development agent.
