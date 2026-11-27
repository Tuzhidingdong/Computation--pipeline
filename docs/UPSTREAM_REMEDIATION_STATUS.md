# Upstream Remediation Status

**Current state:** Agent A supplied the Data_analysis Artifact resolver and derived Artifact registration APIs. Agent B has bound these interfaces in the existing Pipeline Draft PR #1. Live upstream runtime tests are opt-in; public CI uses synthetic fixtures and injected API doubles.  
**Governing instruction:** [UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md](UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)  
**Audit:** [EXISTING_SKILL_CAPABILITY_AUDIT.md](EXISTING_SKILL_CAPABILITY_AUDIT.md)  
**Adapter contract:** [SKILLS_ADAPTER_CONTRACT_V0.1.md](SKILLS_ADAPTER_CONTRACT_V0.1.md)  
**Live binding notes:** [REAL_SKILLS_INTEGRATION_TODO.md](REAL_SKILLS_INTEGRATION_TODO.md)

## Upstream branches inspected

| Repository | Agent A branch | Inspected HEAD | Agent B action |
|---|---|---|---|
| chem-scitoolkit | `dft-finite-cluster-production-interfaces` | `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba` | Read-only source/signature inspection; bound Pipeline RealCSTAdapter |
| Data_analysis | `cp2k-dft-artifact-and-evidence-support` | `b71c9e90e65af0f8a7a377ab37159dc60fed3a97` | Read-only source/signature inspection; bound official resolver and derived registration in Pipeline RealDataAnalysisAdapter |
| BeiLong_HPC (private) | unchanged | Existing historical audit revision only | Mock adapter remains; no real HPC invocation |
| UCAS_hpc (private) | unchanged | Existing historical audit revision only | Mock adapter remains; no real HPC invocation |

These are the exact branch heads supplied by the user and confirmed from the remote refs during this task. They are not claims about merged default branches.

## Requirement tracker

| ID | Requirement | Target | Status | Evidence / boundary |
|---|---|---|---|---|
| CST-1 | Finite/non-periodic CP2K input builder | chem-scitoolkit | REAL ADAPTER BOUND | Calls `CP2KInputBuilder.build_finite_system`; no CP2K execution |
| CST-2 | Task-aware CP2K output validation | chem-scitoolkit | REAL ADAPTER BOUND | Calls `validate_cp2k_output`; status preserved, not scientific validation |
| CST-3 | True Bader / calibrated Hirshfeld handling | chem-scitoolkit | REAL ADAPTER BOUND | Calls `validate_bader_true_results` / `estimate_hirshfeld_charges` |
| CST-4 | PDOS parsing/normalization | chem-scitoolkit | REAL ADAPTER BOUND | Calls `normalize_cp2k_pdos`; optional `cp2k_pdos` executable remains required |
| CST-5 | Cube grid and vacuum reference utilities | chem-scitoolkit | REAL ADAPTER BOUND | Calls cube/plateau/reference functions |
| CST-6 | ASE thermochemistry wrapper | chem-scitoolkit | REAL ADAPTER BOUND | Calls `ase_harmonic_thermochemistry`; ASE remains optional |
| CST-7 | Figure profile | chem-scitoolkit | REAL ADAPTER BOUND | Calls `apply_figure_profile` / `save_figure_profiled` |
| DA-1 | DFT file format/reader registration | Data_analysis | REAL ADAPTER BOUND | Calls `list_dft_readers` / `read_dft_file`; reader status/hash retained |
| DA-2 | Reader and operation registration | Data_analysis | REAL ADAPTER BOUND | Calls operation list/get/run APIs; operation availability checked |
| DA-3 | DFT provenance/evidence linking | Data_analysis | REAL ADAPTER BOUND — REGISTERED OUTPUT FLOW | Calls `create_dft_analysis_run_from_project` with the registered derived Artifact, then normalized-result packaging and Evidence Package construction; scientific QC remains not_assessed |
| HPC-1 | BeiLong adapter mapping | Computation--pipeline | MOCK CONTRACT ONLY | Real mapping remains read-only follow-up; no Slurm submission |
| HPC-2 | UCAS adapter mapping | Computation--pipeline | MOCK CONTRACT ONLY | Real mapping remains read-only follow-up; no Slurm submission |
| EXT-1 | External tool/license/version inventory | Computation--pipeline | EXISTING BASELINE — VERIFICATION PENDING | `EXTERNAL_TOOL_SELECTION.md` |
| INT-1 | Cross-component mock integration | Computation--pipeline | COMPLETE — MOCK ONLY | `tests/test_mock_integration.py` |
| INT-2 | Real adapter interface-boundary tests | Computation--pipeline | IMPLEMENTED — CI RESULT PENDING | `tests/test_real_adapters.py`; live source tests are opt-in |

## Data_analysis ownership and current limitation

- Data_analysis remains the sole owner of Artifact records/storage, Analysis Runs, cache and Evidence Packages.
- The inspected Data_analysis branch exposes DFT readers, operation registry/dispatcher, project-backed Analysis Run creation and DFT Evidence Package construction.
- The supplied branch now exposes `data_analysis.artifact_store.resolve_artifact_path(project_root, artifact_id)` and `register_derived_artifact(project_root, file_path, ...)`. Resolver and registration own registry access, path containment, symlink checks and registered SHA verification.
- Pipeline no longer requires ArtifactRef.uri; the official resolver is called first and its failures are never bypassed by a URI. A narrowly scoped legacy URI/injected-resolver fallback remains available only when the official resolver is absent.
- Successful JSON-compatible reader output is atomically persisted under project `data/derived/`, registered with the original source Artifact IDs, and passed into `create_dft_analysis_run_from_project(output_artifacts=[derived])`.
- The returned Analysis Run is checked for the registered output Artifact ID and SHA-256. Normalized-result packaging and Evidence Package construction follow Analysis Run persistence.
- Serialization/registration failures create failed Analysis Runs without output IDs and preserve reader data/error details in a warning outcome. Scientific QC remains `not_assessed`; parsing success is not a QC pass.
- The adapter does not install the unmerged private branch or add DA as a mandatory public CI dependency.

## Validation boundary

- The existing 10 Mock tests remain unchanged.
- New real-adapter tests use an in-memory Data_analysis API double to validate official resolver use, hash rejection, derived JSON output, registration descriptor → Analysis Run ID/SHA → Evidence references, and serialization/registration failure semantics.
- Optional live tests use temporary synthetic files and environment variables pointing at approved source trees. They do not execute CP2K or HPC.
- Public CI must not check out the private Data_analysis repository or install its branch automatically.
- Latest PR Actions run: [45930492422](https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/45930335174), commit `341d8fa435b7887b090cebcdf2b11c9e5a146b7d`: 21 unittest cases discovered; 19 passed and 2 opt-in live source-tree cases skipped because the upstream source-root environment variables were not set. Compileall passed. Matching push run: [45930485763](https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/45930329890).
- Mock/adapter tests are not evidence of scientific algorithm correctness or scientific QC.

## Safety

- Only `Computation--pipeline` is modified by Agent B.
- No private HPC host, user, account, path, key, credential or connection configuration is included.
- No production DFT, AIMD, SSH/SCP, Slurm or production HPC task has been submitted.
- PR #1 remains open and Draft; no merge or auto-merge is requested.
