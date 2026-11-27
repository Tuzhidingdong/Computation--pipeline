# Real Skills Integration — Agent B Handoff Checklist

**Status:** Data_analysis resolver/derived registration and the minimal synchronous Pipeline runner are implemented on the existing Draft PR #1; live source integration remains opt-in.
**Updated:** 2026-11-27

## Upstream revisions inspected

- Data_analysis, branch `cp2k-dft-artifact-and-evidence-support`, HEAD `b71c9e90e65af0f8a7a377ab37159dc60fed3a97`.
- chem-scitoolkit, branch `dft-finite-cluster-production-interfaces`, HEAD `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba`.

## Implemented on the Pipeline branch

1. **Official Artifact resolution:** `RealDataAnalysisAdapter` calls `data_analysis.artifact_store.resolve_artifact_path(project_root, artifact_id)` before reading. This delegates registry lookup, project path containment, symlink rejection and registered SHA-256 verification to Data_analysis. No URI is required for the managed Artifact-ID path.
2. **URI compatibility:** an injected owner resolver remains supported. A local `ArtifactRef.uri` is a legacy fallback only when no official/injected resolver exists; it is restricted to the project tree and byte hash, and later DA derived-registration / Analysis Run calls still verify source Artifact custody and hash. An error from the official resolver is never bypassed by a URI.
3. **Derived output persistence:** after a successful reader result, JSON-compatible records are written atomically to a unique non-overwriting file under `data/derived/`. The first stage uses `format_id="json_records"`; results that cannot be faithfully JSON-serialized (including non-finite numbers or unsupported objects) are not registered.
4. **Derived Artifact registration:** the persisted file is passed to `register_derived_artifact()` with source Artifact IDs, parser/reader identity and version, parse status `parsed`, and explicit `quality_status` / `analysis_eligibility` of `not_assessed`. The returned Artifact ID, SHA-256, format, source locator, record and record path are retained.
5. **Analysis Run and Evidence order:** the registered output descriptor is passed to `create_dft_analysis_run_from_project(output_artifacts=[derived])`. The returned Analysis Run is checked for the output ID and SHA-256. Only then is `dft.normalized_result.package` called, followed by `build_evidence_package(dft_analysis_runs=[record_path])`.
6. **Failure semantics:** reader failures create failed Analysis Runs without outputs. Serialization/registration failures create failed run records without output IDs and return `TaskStatus.WARNING`, preserving in-memory reader results, any already-written file path and the explicit error. No fake Artifact ID is emitted. Scientific QC remains `not_assessed`; parser success is not treated as scientific QC pass.
7. **chem-scitoolkit:** `RealCSTAdapter` remains bound to the finite CP2K builder, task-aware output validator, Hirshfeld/Bader, PDOS/Cube/vacuum, ASE thermochemistry and figure-profile functions. No production CP2K run is invoked.
8. **Dependency policy:** upstream imports remain lazy. No private branch is installed by default, and no private upstream repository is added as a required public CI dependency.
9. **HPC:** Mock HPC remains unchanged; real HPC submission is deferred.

## Required verification

- Run `python -m unittest discover -s tests -v`.
- Run `python -m compileall -q pipeline_contracts tests`.
- API-double tests assert the required order: resolver → reader → JSON persistence → derived registration → Analysis Run with output → normalized-result packaging → Evidence Package.
- Optional live tests use temporary synthetic source data and are enabled only by explicit `DATA_ANALYSIS_SOURCE_ROOT` / `CHEM_SCI_TOOLKIT_SOURCE_ROOT`. They do not run CP2K, AIMD, Slurm or production HPC.
- Public CI uses API doubles and does not install or check out Agent A's private branches automatically.

## Minimal Pipeline runner (Agent B MVP)

The package now exports `PipelineRunner`, `PipelineTaskManifest`, `PipelineTaskResult` and `CSTValidationSpec` from `pipeline_contracts`.

- The runner executes one linear flow: resolve input Artifact IDs → optional CST validation → Data_analysis Reader and derived Artifact registration → Analysis Run → normalized-result packaging → Evidence Package.
- Task manifests require `task_id`, `project_root`, `input_artifact_ids` and `operation`; reader parameters, formats, expected hashes and CST validation are optional.
- Before dispatch, a RealDataAnalysisAdapter's official resolver verifies the registered input and the runner pins the resolved SHA-256 onto the request. No local URI is required from the caller.
- Missing adapters/dependencies are represented as `unavailable`; failed CST/Reader/registration steps stop or downgrade the task appropriately. CST warnings can continue into Data_analysis. A nominally successful Data_analysis response missing the run/output/evidence closure is downgraded to warning.
- Scientific QC remains `not_assessed`. Mock records/evidence are tagged as mock and are not scientific validation.
- Python example: `examples/postprocess_existing_cp2k_output.py`; user instructions are in the README's “Minimal Pipeline MVP” section.
- This is a synchronous single-workflow coordinator only. It does not include DAG scheduling, persistent task databases, queues, a service/API server or real HPC submission.

## Remaining boundaries

- This change implements only the minimal Data_analysis reader-to-derived-Artifact lifecycle. It does not introduce a general workflow engine or large binary/array serialization format.
- Non-JSON results require a future explicit storage format/serializer; for now they remain in-memory with a visible warning and no output Artifact.
- A registration error after a file was written leaves the real file in `data/derived/` for recovery, but no Pipeline output Artifact is claimed unless Data_analysis returned a valid descriptor and the Analysis Run retained it.
- Scientific QC and result-specific physical validation remain outside this adapter.
- Live runtime integration against the supplied private source tree is opt-in; public CI does not fetch or install it.

## Safety and ownership

- Only `Tuzhidingdong/Computation--pipeline` is modified by Agent B.
- `Data_analysis` and `chem-scitoolkit` remain read-only upstream dependencies.
- No production DFT, AIMD, SSH/SCP, Slurm or HPC task is run.
- Existing Mock adapters and their original 10 tests are retained.
- PR #1 remains Open / Draft and is not auto-merged.