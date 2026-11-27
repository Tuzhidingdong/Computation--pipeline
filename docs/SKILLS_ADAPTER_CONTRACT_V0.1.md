# Pipeline ↔ Skills Adapter Contract v0.1

**Status:** Pipeline-side contract with optional real CST/Data_analysis adapters; mock and adapter-boundary tested. Live upstream execution remains opt-in.  
**Updated:** 2026-11-27  
**Scope:** CST, Data_analysis, and HPC adapter boundaries. This is not a workflow engine and does not certify scientific validity.

## 1. Design rules

1. `Computation--pipeline` owns task identity, orchestration, state transitions and cross-backend routing. Specialist Skills own scientific operations, artifact/evidence records and cluster execution details.
2. Pipeline communicates through narrow typed requests, outcomes and opaque references. It does not copy specialist algorithms or databases.
3. The method names `execute()` and `analyze()` below are **internal Pipeline adapter methods**. They are not claims that `chem-scitoolkit` or `Data_analysis` currently exports functions with those names.
4. `ArtifactRef` carries an upstream `artifact_id` and optional hash/format/URI metadata. It is not an Artifact Store, does not contain file bytes, and does not imply that Pipeline owns the referenced storage.
5. Mocks use `mock://` references and explicitly set scientific validation/QC to `not_evaluated`. They never generate numerical scientific results.
6. The contract is deliberately small. Add fields only when a real upstream implementation or tested integration requires them; preserve existing upstream schemas and identifiers.

## 2. Shared reference and provenance model

### ArtifactRef

| Field | Required | Meaning |
|---|---:|---|
| `artifact_id` | Yes | Opaque identifier assigned by the owning Artifact system. |
| `sha256` | No | SHA-256 of the exact source/output bytes when available; 64 hex characters. |
| `format_id` | No | Registered format identifier, not a guessed file extension. |
| `media_type` | No | Optional media type. |
| `uri` | No | Opaque resolver URI; do not put cluster credentials or private paths here. |
| `storage_mode` | No | Upstream storage mode, e.g. local copy or external managed reference. |
| `source_system` | No | System owning the reference, such as `Data_analysis`. |
| `mock` | No | `true` only for synthetic test references. |

Pipeline must preserve the original Artifact ID and hash when passing a reference between adapters. A missing hash remains missing; the adapter must not invent one. Paths and bytes are resolved by the owning upstream system when its supported access API is available.

### ProvenanceRecord

A result should carry `task_id`, component/operation name and version, input/output ArtifactRefs, optional `upstream_job_reference`, operation parameters, software versions, and warnings. The pipeline-level task ID and upstream job ID are distinct identifiers and must both be retained.

### Status and diagnostics

`TaskStatus` distinguishes `pending`, `submitted`, `queued`, `running`, `awaiting_validation`, `succeeded`, `warning` and `failed`. An adapter failure requires a non-empty error. Warnings are structured diagnostics, not silently folded into success. `succeeded` means the adapter operation completed; it does **not** by itself mean a scientific result passed QC.

## 3. chem-scitoolkit adapter (CST)

### Pipeline-side request

`CSTTaskRequest` contains:

- `task_id`: stable Pipeline task identifier;
- `operation`: requested capability identifier (provisional until CST exposes its tested operation names);
- `task_config`: calculation/task configuration, e.g. run type, charge/spin, cell/Poisson, print settings;
- `input_artifacts`: structure, CP2K input, prior calculation or other source ArtifactRefs;
- `parameters`: operation-specific values with units where applicable;
- `upstream_job_reference`: optional HPC job reference for parsing or result assessment;
- `metadata`: schema/source revision and other non-secret context.

At least one of `task_config` or `input_artifacts` is required. Existing scientific input files are passed by reference; Pipeline does not reimplement their parsers.

### Pipeline-side response

`AdapterOutcome` contains:

- the same `task_id`;
- adapter `status`;
- `structured_result` for normalized metadata/results returned by the real CST implementation;
- output ArtifactRefs;
- typed diagnostics and optional error;
- `ProvenanceRecord`, including input/output references and the upstream job reference;
- `execution_mode` and `scientific_validation`.

A real adapter must not invent missing fields or claim `scientific_validation=passed` unless the CST result and project gate provide evidence. A mock response uses `execution_mode=mock`, `scientific_validation=not_evaluated`, a placeholder result marker, and mock-only ArtifactRefs.

### Upstream binding status

**Provisional.** No current CST callable function/signature is established by the Pipeline repository's audit. Candidate operations include finite CP2K input construction, task-aware output assessment, PDOS/cube/charge normalization and ASE thermochemistry wrapping, but names and argument shapes must be bound only after Agent A supplies implementation and tests. Do not treat `CSTTaskRequest.operation` strings in tests as real CST API names.

## 4. Data_analysis adapter (DA)

### Pipeline-side request

`AnalysisRequest` contains:

- `task_id` and provisional `operation` identifier;
- `input_artifacts`: one or more CST/HPC/source ArtifactRefs;
- `analysis_task`: requested registration/normalization/analysis intent;
- `parameters`: deterministic operation parameters;
- `structure_metadata`: optional structure/model identity and calculation metadata;
- `upstream_job_reference`: optional HPC job identifier;
- `metadata`: source task ID, relevant operation context and schema version.

### Pipeline-side response

`AnalysisOutcome` contains:

- `analysis_run_id` (or the equivalent ID returned by the real DA implementation);
- status, output ArtifactRefs and EvidenceRefs;
- `ProvenanceRecord`, retaining input/output IDs, hashes, operation/software versions, parameters and upstream job reference;
- structured QC status/details, warnings and an explicit error on failure.

An `EvidenceRef` preserves its source Artifact IDs and known hashes. An absent source hash, locator, Observation ID or evidence field stays absent; Pipeline must not synthesize source evidence.

### Data_analysis ownership and PR #4 dependency

The existing architecture assigns Artifact, Analysis Run, SHA-256, cache and evidence ownership to `Data_analysis`. Pipeline stores only references and orchestration state. **Do not add an Artifact Store, artifact database, content cache or competing evidence registry here.**

As inspected on 2026-11-27, `Tuzhidingdong/Data_analysis` PR #4 (“Add read-only managed Artifact interoperability and evidence export contract”) is open and unmerged. Its proposed scope includes read-only external managed references (without copying managed bytes), Artifact path/stream access, Artifact schema compatibility, and `scientific-evidence-export@1.0.0` provenance fields. The PR describes `data_analysis.artifact_store.resolve_artifact_path(...)` and `open_artifact(...)` as candidate access functions. They are **not treated here as merged/main-branch APIs**. Do not copy PR #4 code into Pipeline. After its owner-reviewed merge, bind the real DA adapter to the merged, tested interface and preserve its Artifact IDs/hashes and external-reference custody model.

The current main-branch capability audit records DA's Artifact and Analysis Run schemas as reusable, and DA-1/DA-2 DFT format/reader/operation registration as upstream work. This contract does not assume those DFT registrations already exist.

## 5. HPC adapter

Pipeline defines one internal `HpcAdapter` Protocol with the following expected operations:

| Pipeline-side operation | Input | Output |
|---|---|---|
| `preflight()` | None | Backend readiness, supported capabilities and diagnostics. |
| `stage_inputs(task_manifest)` | Task ID, input ArtifactRefs and execution payload | Staging record and staged input references. |
| `submit(task_manifest)` | Staged task manifest | Opaque `JobReference` linked to the Pipeline task ID and backend ID. |
| `get_status(job_reference)` | JobReference | Normalized async state plus raw scheduler/application states. |
| `get_record(job_reference)` | JobReference | Upstream job record, exit code/application evidence and output references. |
| `retrieve_selected_outputs(job_reference, output_selection)` | JobReference and selected Artifact/output IDs | Only requested output ArtifactRefs. |
| `verify_hashes(manifest)` | Output manifest | Per-artifact integrity result and failures. |

The adapter is responsible only for translation and orchestration. `BeiLong_HPC` and `UCAS_hpc` remain authoritative for their own authentication, path, Slurm, transfer and job-ledger behavior. Their exact command lines, hosts, accounts, paths and connection settings do not belong in this public repository.

### Completion rule

A scheduler state of `COMPLETED` is mapped to `awaiting_validation`, not `succeeded`. The Pipeline may mark the HPC task successful only after the backend job record confirms application-level success and the selected output integrity checks pass. Application failure or hash failure blocks success. A lost/unknown status stays `unknown` or `awaiting_validation`; it must not be promoted by inference.

The mock HPC adapter exercises this lifecycle without SSH, SCP, Slurm or remote files. Its hash check is explicitly a mock assertion (`mock_scenario_no_bytes_hashed`), not a real SHA-256 calculation.

### Upstream binding status

**Provisional.** The operation names above are Pipeline-side adapter expectations, not claims about identical functions in either HPC Skill. The architecture audit reports both Skills already have their own scheduler, job-record and checksum capabilities, with intentionally different operational interfaces. Final per-Skill command/function mappings require read-only confirmation by the authorized owner; only then should two backend-specific adapters be bound.

## 6. Mock contract behavior

The standard-library-only mocks support success, warning, pending and failure for CST/DA, plus HPC submitted → queued → running → scheduler completed → awaiting validation → success/failure. They preserve task IDs, Artifact IDs, Analysis Run IDs, Evidence source IDs and Job References. Invalid/missing inputs and undeclared output selections are rejected.

Mock outputs are identifiers and metadata only. The fields `scientific_values_generated=false`, `scientific_validation=not_evaluated`, `qc_status=not_evaluated` and `mock://` URIs make it impossible to mistake the fixture for a real calculation or validated analysis. A passed mock adapter test proves only request/response compatibility and control flow.

## 7. Verification

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q pipeline_contracts tests
```

The suite is intended to verify schema handoff, reference/provenance preservation, warning/failure propagation, invalid-input rejection, scheduler/application separation, hash-failure blocking and the `Pipeline → Mock CST → Mock Data_analysis` reference chain. It does not validate CP2K, an analysis algorithm, scientific QC, a real Artifact Store, SSH/SCP, a scheduler or production HPC execution.


## 8. Real upstream bindings (Agent A branches inspected 2026-11-27)

The following signatures were read from the exact upstream branch heads listed here. They are not imported at package import time and are not installed automatically by Pipeline.

| Upstream | Branch | Inspected HEAD |
|---|---|---|
| `Tuzhidingdong/Data_analysis` | `cp2k-dft-artifact-and-evidence-support` | `22ad1290e0d78c6a98fbd6d2d194d3ad8e1c689a` |
| `Tuzhidingdong/chem-scitoolkit` | `dft-finite-cluster-production-interfaces` | `dc1290a6c58aa9291b1b5d28503ac9a95ffbc4ba` |

### 8.1 Data_analysis

`RealDataAnalysisAdapter` lazily binds these module-level symbols:

- `data_analysis.dft_readers.list_dft_readers(format_id=None)`
- `data_analysis.dft_readers.read_dft_file(path, **reader_parameters)`
- `data_analysis.dft_operations.list_dft_operations()`
- `data_analysis.dft_operations.get_dft_operation(operation_id)`
- `data_analysis.dft_operations.run_dft_operation(operation_id, **parameters)`
- `data_analysis.dft_provenance.create_dft_analysis_run_from_project(...)`
- `data_analysis.evidence.build_evidence_package(dft_analysis_runs=[...])`

The current branch also implements the `dft.artifact.read` and `dft.normalized_result.package` operation IDs. The adapter checks the operation registry before reading, calls the reader for each input reference, records reader catalogue/selection and statuses, creates the run with the upstream project provenance function, packages the normalized result through `run_dft_operation`, and builds an Evidence Package from the persisted Analysis Run record.

**Artifact ownership / path rule:** this inspected branch does not contain `data_analysis.artifact_store` or a public Artifact resolver. Pipeline therefore does not inspect Data_analysis registry JSON, locate files itself, or create a parallel Artifact Store. The adapter accepts a caller-supplied local path/file URI in `ArtifactRef.uri`, or an injected `artifact_path_resolver(project_root, artifact_id)`. A resolver can be bound to a future owner-provided public Data_analysis API after that API is present. The Analysis Run creation call still delegates Artifact-ID registration and SHA-256 verification to Data_analysis using its own `project_root`.

A real Data_analysis request must include a valid 64-character `ArtifactRef.sha256`. A missing hash is rejected before reading; a reader hash that differs from the reference hash is a failed input. Only a local URI or an injected/upstream resolver is accepted. Remote URI schemes are not fetched by Pipeline.

**Partial-result semantics:** `read_dft_file` currently returns parsed content in memory. The inspected API does not register a new derived Artifact from these returned bytes. To avoid inventing output IDs or storing bytes in Pipeline, the adapter creates an Analysis Run with `status=partial`, no output Artifact IDs, and `qc_status=not_assessed` when all reads succeed. It returns the normalized reader data, persisted Analysis Run record/ID and Evidence Package, with Pipeline `TaskStatus.WARNING` to make the absence of a registered derived Artifact explicit. Reader failures are recorded as failed Analysis Runs (where the upstream API permits) and surfaced as `TaskStatus.FAILED`; unavailable reader, unsupported format, source missing, parse failure and hash mismatch have distinct diagnostic codes.

### 8.2 chem-scitoolkit

`RealCSTAdapter` lazily binds:

| Pipeline operation ID | Actual upstream callable |
|---|---|
| `cp2k.build_finite_system` | `my_sci_toolkit.simulation.cp2k.builder.CP2KInputBuilder(...).build_finite_system(...)` |
| `cp2k.validate_input` | `dft_workflows.validate_cp2k_input(input_path, base_dir=None)` |
| `cp2k.validate_output` | `dft_workflows.validate_cp2k_output(log_path, run_type)` |
| `charge.estimate_hirshfeld` | `dft_workflows.estimate_hirshfeld_charges(...)` |
| `charge.validate_bader` | `dft_workflows.validate_bader_true_results(...)` |
| `pdos.normalize` | `dft_workflows.normalize_cp2k_pdos(...)` |
| `cube.read` | `dft_workflows.read_cube(path)` |
| `cube.validate_compatibility` | `dft_workflows.validate_cube_compatibility(...)` |
| `cube.subtract_fields` | `dft_workflows.subtract_cube_fields(...)` |
| `vacuum.detect_plateau` | `dft_workflows.detect_vacuum_plateau(...)` |
| `vacuum.validate_reference` | `dft_workflows.validate_vacuum_energy_reference(...)` |
| `thermochemistry.ase_harmonic` | `dft_workflows.ase_harmonic_thermochemistry(...)` |
| `figure.apply_profile` | `my_sci_toolkit.viz.style.apply_figure_profile(profile)` |
| `figure.save_profiled` | `my_sci_toolkit.viz.style.save_figure_profiled(fig, output_path, profile, metadata=None)` |

For the finite builder, request configuration uses `task_config.builder_options` for the builder constructor and `task_config.arguments` plus `parameters` for `build_finite_system`. For file-based operations, the primary local Artifact URI is supplied to the exact file/path parameter; PDOS accepts all selected input Artifact paths. DataFrame/array arguments for charge and analysis helpers remain supplied by the caller; Pipeline does not reimplement their conversion.

CST's result is returned as structured output/metadata. The adapter does not claim to have registered a result Artifact or run a CP2K calculation. Optional tools/executables (for example `cp2klint`, `cp2k_pdos`, ASE) remain upstream requirements; missing optional tools become explicit failure/unavailable outcomes rather than simulated values. A non-passing upstream assessment is preserved as a warning and never promoted to scientific success.

### 8.3 Dependency and live-test policy

- `pipeline_contracts.real_adapters` imports only Python standard-library modules and the local Pipeline contract models at module import time.
- Upstream modules are imported only when the caller instantiates an adapter and invokes it, or when a caller injects tested module/API objects.
- No private Data_analysis branch is installed by default and no dependency is fetched automatically.
- CI runs synthetic adapter-boundary tests. Optional live tests use `DATA_ANALYSIS_SOURCE_ROOT` and `CHEM_SCI_TOOLKIT_SOURCE_ROOT` to point to owner-approved source trees. An unset variable skips that corresponding live test.
- Live Data_analysis tests create a temporary synthetic project and Artifact registration. Live CST tests generate a synthetic finite CP2K input string only; they do not invoke CP2K.

These tests validate interface wiring and status/provenance handoff only. They do not validate scientific algorithms, actual CP2K executable compatibility, HPC behavior or scientific QC.
