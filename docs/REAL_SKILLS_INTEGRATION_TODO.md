# Real Skills Integration — Agent B Handoff Checklist

**Status:** Pipeline-side real adapters implemented against the exact Agent A branch heads listed below; live runtime integration remains opt-in  \
**Updated:** 2026-11-27

## Upstream revisions inspected

- `Tuzhidingdong/Data_analysis`, `cp2k-dft-artifact-and-evidence-support`: `22ad1290e0d78c6a98fbd6d2d194d3ad8e1c689a`
- `Tuzhidingdong/chem-scitoolkit`, `dft-finite-cluster-production-interfaces`: `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba`

## Implemented on the Pipeline branch

1. **Data_analysis:** `RealDataAnalysisAdapter` lazily binds `list_dft_readers`, `read_dft_file`, `list_dft_operations`, `get_dft_operation`, `run_dft_operation`, `create_dft_analysis_run_from_project` and `build_evidence_package(dft_analysis_runs=[...])`.
2. **Artifact custody:** the current specified DA branch has no `data_analysis.artifact_store` module/resolver. The adapter uses a caller-provided local Artifact URI or injected `artifact_path_resolver`; it never reads the DA registry itself or creates a duplicate store. It requires an Artifact SHA-256 and verifies the reader-reported hash matches it. DA's project provenance function independently verifies its registered Artifact bytes.
3. **Run completeness:** the DA reader currently returns parsed data in memory and does not register derived output Artifacts. The adapter therefore records a `partial` Analysis Run, no made-up output Artifact IDs, and `qc_status=not_assessed`; successful parsing returns `TaskStatus.WARNING` to make that limitation visible. Reader errors become failed runs where supported, with distinct failure diagnostics. It packages the normalized reader result and Evidence Package while preserving the Analysis Run ID, Artifact IDs, hashes, parameters, software, warnings and upstream job reference.
4. **chem-scitoolkit:** `RealCSTAdapter` binds the finite-system builder, CP2K input/output checks, true-Bader/Hirshfeld handling, PDOS, Cube compatibility/subtraction, vacuum plateau/reference checks, ASE HarmonicThermo wrapper and figure-profile APIs. It uses the public functions in `my_sci_toolkit.simulation.cp2k.dft_workflows`, `my_sci_toolkit.simulation.cp2k.builder` and `my_sci_toolkit.viz.style`.
5. **Dependency policy:** upstream imports are lazy. No private branch is installed by default. Missing optional packages/executables surface as unavailable/failure; no scientific values or output Artifacts are fabricated.
6. **HPC:** Mock HPC remains unchanged; no real backend invocation is attempted.

## Remaining real-integration steps

1. Make the Agent A Data_analysis source available in the runtime or inject its public Artifact resolver when an ArtifactRef has no local URI. The Pipeline adapter intentionally does not duplicate Artifact path resolution.
2. Once Data_analysis adds/merges a supported derived Artifact registration path for DFT reader outputs, extend this adapter to register derived output Artifacts and advance eligible runs from `partial`; do not claim that step is implemented now.
3. Run the opt-in live tests in an environment where the approved source trees and required base dependencies are already available:
   - `DATA_ANALYSIS_SOURCE_ROOT`: Data_analysis repository root (contains `src/data_analysis`).
   - `CHEM_SCI_TOOLKIT_SOURCE_ROOT`: chem-scitoolkit source repository root.
   These variables are deliberately not set in public CI and do not cause private repository checkout or dependency installation.
4. If an Agent A branch changes a callable signature, update only the corresponding narrow adapter binding and its contract test. Do not copy upstream algorithms into Pipeline.

## Verification boundary

The public CI adapter tests inject fake module-level APIs to test Pipeline's argument mapping, error mapping, artifact/provenance retention and CST call routing. The opt-in tests call the actual source branches against temporary synthetic files or build a synthetic CP2K input string; they do not run CP2K, ASE calculations with production data, HPC, Slurm or production workflows. Passing these tests is interface validation, not scientific validation.

