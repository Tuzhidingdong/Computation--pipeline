# Development Status — coordination-dft-publication-pipeline

> This file records execution progress only. The governing development objective is `TASK_PLAN_v1.0.0.md`; architecture ownership and the approved prerequisite are documented in `docs/`.

## Repository and baseline

- **Repository:** `Tuzhidingdong/Computation--pipeline`
- **Default branch:** `main`
- **Agent B branch:** `agent-b/pipeline-mock-contracts-20261127`
- **Agent B PR:** https://github.com/Tuzhidingdong/Computation--pipeline/pull/1 (Open / Draft; do not auto-merge)
- **Upstream Data_analysis inspected branch:** `cp2k-dft-artifact-and-evidence-support` at `b71c9e90e65af0f8a7a377ab37159dc60fed3a97`
- **Upstream chem-scitoolkit inspected branch:** `dft-finite-cluster-production-interfaces` at `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba`
- **No production DFT or HPC task has been submitted.**
- **Follow-up CI for the Artifact resolver/derived-output change:** pending on the new Pipeline commit; earlier adapter-only CI does not validate this follow-up.

## Agent B work — real Skill adapter phase

The original provisional contracts and 10 Mock tests are retained. This phase adds optional real adapter classes in `pipeline_contracts/real_adapters.py`:

- `RealDataAnalysisAdapter`: lazily binds the actual Data_analysis DFT reader, operation registry/dispatcher, project-backed Analysis Run creator and Evidence Package builder.
- `RealCSTAdapter`: lazily binds the actual finite-system builder, task-aware CP2K output validator, charge helpers, PDOS/Cube/vacuum utilities, ASE thermochemistry and figure-profile functions.
- `load_data_analysis_api()`: imports upstream modules only on demand. No private dependency is installed by default.
- `AnalysisOutcome`: extended to retain returned reader data, persisted Analysis Run record, Evidence Package and detailed diagnostics. Missing Analysis Run IDs are represented as `None` on failure, never invented.

## Data_analysis adapter boundary

The Agent A Data_analysis branch at `b71c9e90e65af0f8a7a377ab37159dc60fed3a97` now exposes `data_analysis.artifact_store.resolve_artifact_path()` and `register_derived_artifact()`. Pipeline resolves by Artifact ID through the official resolver before reading; Data_analysis owns registry lookup, path containment, symlink rejection and SHA-256 verification. A local URI is not required. A legacy URI fallback is considered only when no official or injected resolver exists, and still requires the DA registration/Analysis Run APIs to verify custody and hashes. Pipeline never reads DA registry JSON or creates another Artifact Store.

After successful JSON-compatible reads, Pipeline atomically writes a unique file under `data/derived/`, registers it through `register_derived_artifact()`, and passes the returned descriptor in `output_artifacts` to `create_dft_analysis_run_from_project()`. The Analysis Run's output Artifact ID and SHA-256 are checked before normalized-result packaging and Evidence construction. Non-JSON serialization or registration failure returns a warning with in-memory results and no fabricated output Artifact; a file already persisted before a registration failure is retained for recovery. Scientific QC remains `not_assessed`.

## CST adapter boundary

The real CST adapter uses exact functions observed on the supplied Agent A branch. It returns upstream metadata/result objects only. It does not create Artifact Store entries or run CP2K. Missing `cp2klint`, `cp2k_pdos`, ASE or other optional runtime dependencies are surfaced as explicit unavailable/failure outcomes.

## Tests

- Existing Mock contract tests: 10 (retained).
- New real adapter boundary tests: Data_analysis API doubles verify official resolver/hash rejection, no-URI input, atomic derived JSON persistence, registration → Analysis Run output ID/SHA → normalized package → Evidence ordering, serialization/registration failure semantics, and QC not_assessed; CST builder/validator doubles remain.
- Optional live tests are skipped unless `DATA_ANALYSIS_SOURCE_ROOT` and/or `CHEM_SCI_TOOLKIT_SOURCE_ROOT` are explicitly set. They use temporary synthetic artifacts only.
- GitHub Actions PR run [45930335174](https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/45930335174): `Ran 19 tests`, `OK (skipped=2)`; the 17 executed tests passed and the two opt-in source-tree tests were skipped because `DATA_ANALYSIS_SOURCE_ROOT` / `CHEM_SCI_TOOLKIT_SOURCE_ROOT` were not supplied. `python -m compileall -q pipeline_contracts tests` passed.
- Matching push run [45930485763](https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/45930329890) also succeeded.
- Passing adapter tests validate interface wiring and status/provenance flow only, not scientific algorithms or scientific QC.

## Remaining blockers / follow-up

1. Live upstream source tests require an approved environment with both branch source trees and optional runtime packages available; public CI will not install or check out private upstream source automatically.
2. First-stage derived persistence supports JSON-compatible reader records only; large binary/numerical arrays need an explicit future serializer/storage format.
3. Real HPC adapter binding remains deferred; Mock HPC stays in place and no scheduler calls are made.

## Pipeline engine phases

The full workflow DAG/controller/model-review/production DFT engine has not started. This task only implements the narrow specialist adapters and tests required for the upstream integration handoff.

## Safety

- Only `Computation--pipeline` is modified by Agent B.
- Agent A repositories are read-only.
- BeiLong_HPC and UCAS_hpc remain read-only.
- No production DFT, AIMD, SSH/SCP, Slurm or HPC task has been submitted.
- PR #1 remains Open / Draft and unmerged.
