# Development Status — coordination-dft-publication-pipeline

> This file records implementation progress. The governing objective remains TASK_PLAN_v1.0.0.md; architecture ownership is documented under docs/.

## Repository and baseline

- Repository: `Tuzhidingdong/Computation--pipeline`
- Default branch: `main`
- Agent B branch: `agent-b/pipeline-mock-contracts-20261127`
- Existing PR: https://github.com/Tuzhidingdong/Computation--pipeline/pull/1 (Open / Draft; do not merge automatically)
- Data_analysis source inspected: `cp2k-dft-artifact-and-evidence-support` @ `b71c9e90e65af0f8a7a377ab37159dc60fed3a97`
- chem-scitoolkit source inspected: `dft-finite-cluster-production-interfaces` @ `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba`
- Only Computation--pipeline is modified. Upstream repositories remain read-only.
- No production DFT, AIMD, SSH/SCP, Slurm or HPC task has been submitted.

## Pipeline MVP — synchronous post-processing runner

Implemented in `pipeline_contracts/runner.py` and exported from the package:

- `PipelineTaskManifest`: task ID, project root, input Artifact IDs, operation, parameters, optional Artifact hash/format metadata and optional CST validation specification.
- `PipelineRunner.run(manifest)`: synchronous linear execution; it does not create a DAG, queue, database, service or scheduler.
- `PipelineTaskResult`: final state, state history, stage summaries, input/output ArtifactRefs, Analysis Run ID/record, Evidence refs/package, QC status, diagnostics, warnings and error.
- `CSTValidationSpec`: select optional CP2K input/output validation and choose whether an unavailable validator is blocking.
- Explicit adapter injection is required. A missing Data_analysis or required CST adapter is returned as `unavailable`; the runner never silently selects Mock or Real.
- Status aggregation preserves `succeeded`, `warning`, `failed` and `unavailable`. CST warning results continue to Data_analysis; required CST failure/unavailability stops the workflow. Reader/provenance failure never reports task success.
- HPC is not invoked in this workflow; existing Mock HPC remains unchanged.

## Input custody and Data_analysis handoff

- A manifest may contain only input Artifact IDs. When a real Data_analysis adapter exposes its official resolver, the runner calls it first, lets Data_analysis verify project containment, symlinks and registered SHA-256, then pins the verified file SHA onto the Pipeline ArtifactRef before passing it downstream.
- A caller-provided SHA, when supplied, must match the resolved bytes. The RealDataAnalysisAdapter also retains its strict SHA requirement when called directly.
- Optional RealCST validation receives the same resolved input file path through a file URI; the analysis request retains the Artifact ID and verified SHA.
- Data_analysis remains the owner of Artifact registry/storage, derived Artifact registration, Analysis Runs, hashes and Evidence. Pipeline never reads DA registry files.
- JSON-compatible reader results are atomically written below project `data/derived/`, registered through `register_derived_artifact()`, and passed to `create_dft_analysis_run_from_project(output_artifacts=[...])`.
- The Analysis Run output ID and SHA are verified before normalized-result packaging and Evidence Package construction.
- Scientific QC remains `not_assessed`; parser success is not scientific validation.
- Serialization/registration failure creates no fake output Artifact and cannot produce a successful task state. A file already written before registration failure remains on disk for recovery.

## Adapter boundaries

- `RealDataAnalysisAdapter`: official Artifact resolver, DFT Reader, derived Artifact registration, Analysis Run, normalized result and Evidence.
- `RealCSTAdapter`: finite CP2K builder, CP2K input/output assessment, charge/PDOS/Cube/vacuum/thermochemistry/figure helpers. The runner only invokes CST validation when the task manifest requests it.
- Mock CST / Data_analysis / HPC adapters remain available. Mock Analysis Run and Evidence objects are synthetic and clearly marked `execution_mode="mock"`; no scientific values are generated.

## Example and tests

- Runnable Python example: `examples/postprocess_existing_cp2k_output.py`.
- Usage documentation: README section “Minimal Pipeline MVP — existing CP2K output post-processing”.
- Original 10 Mock contract tests are retained.
- Runner tests cover a complete Mock end-to-end chain, optional CST warning, Reader failure, Artifact hash error, derived registration failure, missing/unavailable adapters, optional validator skip and non-terminal stage state.
- Real Data_analysis boundary tests cover Artifact-ID-only resolver access, SHA rejection, derived JSON persistence/registration, Analysis Run output ID/hash and Evidence ordering.
- Latest verified CI at time of this edit: run [45935827801](https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/45935827801), code commit `c71fc064aa32591c65cf8c3f557419cb759e58fd`: 35 tests run, 33 passed, 2 optional live upstream source tests skipped; compileall passed. Later small status/error-mapping edits must receive their own CI check before final handoff.
- Mock tests validate orchestration and reference propagation only, not CP2K, scientific algorithms or scientific QC.

## Remaining boundaries

1. Live upstream execution remains opt-in and was not run in public CI; source-root variables and approved runtime dependencies must be supplied by the owner.
2. Derived JSON persistence is the first supported format. Large arrays/binary Reader outputs need a separately specified storage format.
3. This is one synchronous post-processing path, not a general DAG/controller, workflow server or queue.
4. Real HPC is deferred; no scheduler adapter is invoked.

## Safety

- No private Data_analysis branch is installed automatically or made a required public CI dependency.
- No changes to Data_analysis, chem-scitoolkit, BeiLong_HPC or UCAS_hpc.
- No production DFT, AIMD, Slurm or HPC submission.
- PR #1 remains Open / Draft and unmerged.
