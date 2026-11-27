# Pipeline ↔ Skills Adapter Contract v0.1

**Status:** Provisional Pipeline-side contract; mock-tested only  
**Date:** 2026-11-27  
**Scope:** CST, Data_analysis, and HPC adapter boundaries. This is not a workflow engine and does not certify any upstream API.

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
