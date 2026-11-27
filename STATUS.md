# Development Status — coordination-dft-publication-pipeline

> This file records execution progress only. The governing development objective is `TASK_PLAN_v1.0.0.md`; architecture ownership and the approved prerequisite are documented in `docs/`.

## Repository and baseline

- **Repository:** `Tuzhidingdong/Computation--pipeline`
- **Default branch:** `main`
- **Agent B branch:** `agent-b/pipeline-mock-contracts-20261127`
- **Agent B PR:** https://github.com/Tuzhidingdong/Computation--pipeline/pull/1 (Open / Draft; do not auto-merge)
- **Upstream Data_analysis inspected branch:** `cp2k-dft-artifact-and-evidence-support` at `22ad1290e0d78c6a98fbd6d2d194d3ad8e1c689a`
- **Upstream chem-scitoolkit inspected branch:** `dft-finite-cluster-production-interfaces` at `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba`
- **No production DFT or HPC task has been submitted.**

## Agent B work — real Skill adapter phase

The original provisional contracts and 10 Mock tests are retained. This phase adds optional real adapter classes in `pipeline_contracts/real_adapters.py`:

- `RealDataAnalysisAdapter`: lazily binds the actual Data_analysis DFT reader, operation registry/dispatcher, project-backed Analysis Run creator and Evidence Package builder.
- `RealCSTAdapter`: lazily binds the actual finite-system builder, task-aware CP2K output validator, charge helpers, PDOS/Cube/vacuum utilities, ASE thermochemistry and figure-profile functions.
- `load_data_analysis_api()`: imports upstream modules only on demand. No private dependency is installed by default.
- `AnalysisOutcome`: extended to retain returned reader data, persisted Analysis Run record, Evidence Package and detailed diagnostics. Missing Analysis Run IDs are represented as `None` on failure, never invented.

## Data_analysis adapter boundary

The current Agent A Data_analysis branch has no public Artifact resolver module. Pipeline therefore requires either a caller-supplied local URI/file URI or an injected resolver. It requires Artifact SHA-256 and checks the reader result hash. Data_analysis itself verifies the registered Artifact and creates the Analysis Run. Pipeline does not read DA registry JSON or create another Artifact Store.

The current `read_dft_file` result is in-memory; there is no derived-output Artifact registration API in the inspected branch. The real adapter therefore creates a `partial` Analysis Run, no synthetic output Artifact, `qc_status=not_assessed`, and a Pipeline warning. Once Agent A provides a supported derived Artifact registration API, the adapter can be extended narrowly.

## CST adapter boundary

The real CST adapter uses exact functions observed on the supplied Agent A branch. It returns upstream metadata/result objects only. It does not create Artifact Store entries or run CP2K. Missing `cp2klint`, `cp2k_pdos`, ASE or other optional runtime dependencies are surfaced as explicit unavailable/failure outcomes.

## Tests

- Existing Mock contract tests: 10 (retained).
- New real adapter boundary tests: tests injected Data_analysis API double, CST builder/validator doubles, missing resolver/hash, unsupported format and reader-unavailable cases.
- Optional live tests are skipped unless `DATA_ANALYSIS_SOURCE_ROOT` and/or `CHEM_SCI_TOOLKIT_SOURCE_ROOT` are explicitly set. They use temporary synthetic artifacts only.
- Exact GitHub Actions results will be recorded after the branch update runs.
- Passing adapter tests validate interface wiring and status/provenance flow only, not scientific algorithms or scientific QC.

## Remaining blockers / follow-up

1. Data_analysis must expose a public Artifact path resolver for cases where ArtifactRef has no local URI; Pipeline supports injected resolver and will not duplicate the registry logic.
2. Data_analysis currently has no public derived-output Artifact registration function for this DFT read/normalization flow; run status remains partial until that capability is available.
3. Live upstream source tests require an approved environment with both branch source trees and optional runtime packages available; public CI will not install or checkout private upstream source.
4. Real HPC adapter binding remains deferred; Mock HPC stays in place and no scheduler calls are made.

## Pipeline engine phases

The full workflow DAG/controller/model-review/production DFT engine has not started. This task only implements the narrow specialist adapters and tests required for the upstream integration handoff.

## Safety

- Only `Computation--pipeline` is modified by Agent B.
- Agent A repositories are read-only.
- BeiLong_HPC and UCAS_hpc remain read-only.
- No production DFT, AIMD, SSH/SCP, Slurm or HPC task has been submitted.
- PR #1 remains Open / Draft and unmerged.
