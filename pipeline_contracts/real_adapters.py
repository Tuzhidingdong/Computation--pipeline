"""Optional adapters to the real upstream Skill APIs.

The adapters import upstream packages lazily. They never vendor upstream code,
create an Artifact Store, or install optional dependencies.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse

from .models import (
    AdapterOutcome,
    AnalysisOutcome,
    AnalysisRequest,
    ArtifactRef,
    ContractError,
    CSTTaskRequest,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceRef,
    ProvenanceRecord,
    TaskStatus,
)


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def load_data_analysis_api() -> SimpleNamespace:
    """Load the verified module-level API from an installed/source Data_analysis.

    Data_analysis currently exposes these functions from submodules rather than
    its package __init__.py. The modules are imported only when this function is
    called; Pipeline has no mandatory dependency on the private upstream repo.
    """
    try:
        readers = importlib.import_module("data_analysis.dft_readers")
        operations = importlib.import_module("data_analysis.dft_operations")
        provenance = importlib.import_module("data_analysis.dft_provenance")
        evidence = importlib.import_module("data_analysis.evidence")
        artifact_store = importlib.import_module("data_analysis.artifact_store")
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Data_analysis DFT API is unavailable. Install/expose the owner-approved "
            "Data_analysis source in the runtime; Pipeline will not install the "
            "unmerged private branch automatically."
        ) from exc

    required = {
        "list_dft_readers": getattr(readers, "list_dft_readers", None),
        "read_dft_file": getattr(readers, "read_dft_file", None),
        "list_dft_operations": getattr(operations, "list_dft_operations", None),
        "get_dft_operation": getattr(operations, "get_dft_operation", None),
        "run_dft_operation": getattr(operations, "run_dft_operation", None),
        "create_dft_analysis_run_from_project": getattr(
            provenance, "create_dft_analysis_run_from_project", None
        ),
        "build_evidence_package": getattr(evidence, "build_evidence_package", None),
        "resolve_artifact_path": getattr(artifact_store, "resolve_artifact_path", None),
        "register_derived_artifact": getattr(artifact_store, "register_derived_artifact", None),
    }
    missing = [name for name, function in required.items() if not callable(function)]
    if missing:
        raise RuntimeError(f"Data_analysis DFT API is missing callable(s): {', '.join(missing)}")
    return SimpleNamespace(**required)


def _local_artifact_path(
    artifact: ArtifactRef,
    *,
    project_root: str | Path | None,
    resolver: Callable[[str, str], str | Path] | None,
    api: Any,
) -> Path:
    """Resolve a managed Artifact through Data_analysis before considering legacy URIs.

    A resolver error is authoritative and is never bypassed by a caller-supplied URI.
    The URI fallback exists only for older/injected API surfaces without the public
    resolver; the derived registration and Analysis Run APIs still verify the ID and
    registered input hash before a result can be considered complete.
    """
    if project_root is None:
        raise ContractError("project_root is required for Data_analysis Artifact resolution")
    root = Path(project_root).expanduser().resolve(strict=True)

    official_resolver = getattr(api, "resolve_artifact_path", None)
    if callable(official_resolver):
        # Data_analysis owns registry lookup, project containment, symlink checks and SHA-256.
        return Path(official_resolver(str(root), artifact.artifact_id)).expanduser().resolve(strict=True)

    # Backward-compatible injection point for an owner-provided resolver.
    if resolver is not None:
        return Path(resolver(str(root), artifact.artifact_id)).expanduser().resolve(strict=True)

    # Legacy URI compatibility is deliberately unavailable when the official resolver
    # rejects an Artifact. It is considered only when this runtime has no resolver API.
    if artifact.uri:
        parsed = urlparse(artifact.uri)
        if parsed.scheme == "file":
            supplied = Path(unquote(parsed.path))
            if os.name == "nt" and len(parsed.path) >= 3 and parsed.path[0] == "/" and parsed.path[2] == ":":
                supplied = Path(unquote(parsed.path[1:]))
        elif not parsed.scheme:
            supplied = Path(artifact.uri)
        else:
            raise ContractError(
                f"Artifact {artifact.artifact_id} URI scheme {parsed.scheme!r} is not a local file URI"
            )

        lexical = Path(os.path.abspath(supplied.expanduser()))
        try:
            relative = lexical.relative_to(root)
        except ValueError as exc:
            raise ContractError("legacy Artifact URI must point inside the Data_analysis project") from exc
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ContractError(f"legacy Artifact URI contains a symlink component: {current}")
        path = lexical.resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not artifact.sha256 or digest.lower() != artifact.sha256.lower():
            raise ValueError(
                f"legacy Artifact URI SHA-256 does not match ArtifactRef for {artifact.artifact_id}"
            )
        return path

    raise ContractError(
        f"Artifact {artifact.artifact_id} has no Data_analysis resolver and no explicit local URI"
    )


def _atomic_write_derived_json(project_root: str | Path, task_id: str, payload: str) -> Path:
    """Write JSON below data/derived atomically without replacing an existing file."""
    root = Path(project_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)

    current = root
    for component in ("data", "derived"):
        current = current / component
        if current.exists() and current.is_symlink():
            raise ContractError(f"derived output directory contains a symlink: {current}")
        current.mkdir(exist_ok=True)
        if current.is_symlink():
            raise ContractError(f"derived output directory contains a symlink: {current}")
        try:
            current.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise ContractError("derived output directory escapes the Data_analysis project") from exc

    safe_task = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id)).strip(".-_")[:48] or "task"
    encoded = payload.encode("utf-8")
    for _ in range(5):
        token = uuid.uuid4().hex
        target = current / f"dft-reader-{safe_task}-{token}.json"
        temporary = current / f".{target.name}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            # A same-directory hard link is atomic and fails rather than overwriting
            # a target that already exists.
            os.link(temporary, target)
            temporary.unlink()
            return target
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            continue
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    raise FileExistsError("could not allocate a unique derived Artifact result filename")

class RealDataAnalysisAdapter:
    """Bridge Pipeline ArtifactRefs to Data_analysis's DFT reader/run/evidence APIs.

    The adapter requires an existing Data_analysis project root containing the
    referenced Artifact records. File resolution is delegated to an injected or
    upstream resolver, or uses the local URI already carried by ArtifactRef.
    """

    READ_OPERATION = "dft.artifact.read"
    NORMALIZE_OPERATION = "dft.normalized_result.package"

    def __init__(
        self,
        project_root: str | Path,
        *,
        api: Any | None = None,
        artifact_path_resolver: Callable[[str, str], str | Path] | None = None,
        data_analysis_version: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.api = api
        self.artifact_path_resolver = artifact_path_resolver
        self.data_analysis_version = data_analysis_version or _package_version("scientific-data-analysis")

    def _failure(
        self,
        request: AnalysisRequest,
        code: str,
        message: str,
        *,
        result: Mapping[str, Any] | None = None,
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> AnalysisOutcome:
        diagnostic = Diagnostic(code, message, DiagnosticSeverity.ERROR)
        provenance = ProvenanceRecord(
            task_id=request.task_id,
            component="Data_analysis",
            operation=request.operation,
            input_artifacts=request.input_artifacts,
            upstream_job_reference=request.upstream_job_reference,
            parameters=request.parameters,
            software={"pipeline_adapter": "real-data-analysis-v1"},
            warnings=(),
        )
        return AnalysisOutcome(
            task_id=request.task_id,
            analysis_run_id=None,
            status=TaskStatus.FAILED,
            output_artifacts=(),
            evidence_refs=(),
            provenance=provenance,
            qc_status="blocked",
            qc={"status": "blocked", "reason_code": code, "scientific_qc": "not_assessed"},
            error=message,
            execution_mode="real",
            result=dict(result or {}),
            diagnostics=(diagnostic, *diagnostics),
        )

    @staticmethod
    def _operation_is_implemented(descriptor: Mapping[str, Any] | None) -> bool:
        return bool(descriptor and descriptor.get("status") == "implemented")

    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        if any(item.mock for item in request.input_artifacts):
            return self._failure(
                request, "MOCK_ARTIFACT_REJECTED",
                "Real Data_analysis adapter refuses mock:// Artifact references."
            )
        try:
            api = self.api or load_data_analysis_api()
        except Exception as exc:
            return self._failure(request, "DATA_ANALYSIS_UNAVAILABLE", str(exc))

        if not callable(getattr(api, "register_derived_artifact", None)):
            return self._failure(
                request,
                "DA_DERIVED_ARTIFACT_API_UNAVAILABLE",
                "Data_analysis register_derived_artifact() is unavailable; no successful output can be claimed.",
            )

        try:
            operations = api.list_dft_operations()
            operation_map = {
                str(item.get("operation_id")): item
                for item in operations
                if isinstance(item, Mapping)
            }
            read_descriptor = api.get_dft_operation(self.READ_OPERATION)
            normalize_descriptor = api.get_dft_operation(self.NORMALIZE_OPERATION)
            if not self._operation_is_implemented(read_descriptor):
                return self._failure(
                    request, "DFT_READ_OPERATION_UNAVAILABLE",
                    f"Data_analysis operation {self.READ_OPERATION!r} is not implemented.",
                    result={"registered_operation": read_descriptor, "operations": operations},
                )
            if not self._operation_is_implemented(normalize_descriptor):
                return self._failure(
                    request, "DFT_NORMALIZATION_OPERATION_UNAVAILABLE",
                    f"Data_analysis operation {self.NORMALIZE_OPERATION!r} is not implemented.",
                    result={"registered_operation": normalize_descriptor},
                )
            if self.READ_OPERATION not in operation_map or self.NORMALIZE_OPERATION not in operation_map:
                return self._failure(
                    request, "DFT_OPERATION_REGISTRY_MISMATCH",
                    "get_dft_operation and list_dft_operations returned inconsistent DFT operation registries.",
                    result={"operations": operations},
                )

            reader_id = request.parameters.get("reader_id")
            reader_results: list[dict[str, Any]] = []
            reader_catalogues: list[dict[str, Any]] = []
            for artifact in request.input_artifacts:
                if not artifact.sha256:
                    raise ContractError(
                        f"Artifact {artifact.artifact_id} must carry a verified SHA-256 before real DFT reading"
                    )
                path = _local_artifact_path(
                    artifact,
                    project_root=self.project_root,
                    resolver=self.artifact_path_resolver,
                    api=api,
                )
                format_id = artifact.format_id or request.parameters.get("format_id")
                candidates = api.list_dft_readers(format_id) if format_id else api.list_dft_readers()
                reader_catalogues.append({
                    "artifact_id": artifact.artifact_id,
                    "format_id": format_id,
                    "candidates": candidates,
                })
                kwargs: dict[str, Any] = {
                    key: request.parameters[key]
                    for key in (
                        "force_unit", "max_records", "timeout_seconds",
                        "pdos_sigma_hartree", "pdos_step_hartree",
                    )
                    if key in request.parameters
                }
                read_result = api.read_dft_file(
                    path,
                    format_id=format_id,
                    reader_id=str(reader_id) if reader_id else None,
                    **kwargs,
                )
                if not isinstance(read_result, Mapping):
                    raise TypeError("Data_analysis read_dft_file must return a mapping")
                result_record = dict(read_result)
                result_record["pipeline_artifact_id"] = artifact.artifact_id
                actual_hash = result_record.get("source_sha256")
                if not actual_hash or str(actual_hash).lower() != artifact.sha256.lower():
                    result_record["status"] = "artifact_hash_mismatch"
                    result_record["error"] = (
                        f"Data_analysis read hash {actual_hash!r} does not match "
                        f"Pipeline ArtifactRef hash {artifact.sha256}"
                    )
                reader_results.append(result_record)

            valid_reader_statuses = {"parsed", "validated"}
            read_succeeded = bool(reader_results) and all(
                item.get("status") in valid_reader_statuses for item in reader_results
            )
            error_messages = [
                str(item.get("error") or item.get("status") or "DFT reader failed")
                for item in reader_results
                if item.get("status") not in valid_reader_statuses
            ]
            failure_codes = {
                "reader_unavailable": "DFT_READER_UNAVAILABLE",
                "unsupported_format": "DFT_FORMAT_UNSUPPORTED",
                "parse_failed": "DFT_PARSE_FAILED",
                "source_unavailable": "DFT_SOURCE_UNAVAILABLE",
                "artifact_hash_mismatch": "DFT_ARTIFACT_HASH_MISMATCH",
            }
            first_failure_code = next(
                (
                    failure_codes.get(str(item.get("status")), "DFT_READ_FAILED")
                    for item in reader_results
                    if item.get("status") not in valid_reader_statuses
                ),
                "DFT_READ_FAILED",
            )
            reader_warnings = [
                str(message)
                for item in reader_results
                for message in (item.get("warnings") or [])
            ]

            normalized_payload: dict[str, Any] = {
                "schema_version": "1.0.0",
                "result_type": "dft_reader_records",
                "pipeline_task_id": request.task_id,
                "source_artifact_ids": [item.artifact_id for item in request.input_artifacts],
                "reader_results": reader_results,
                "reader_catalogues": reader_catalogues,
                "scientific_qc": "not_assessed",
            }
            derived_path: Path | None = None
            derived: dict[str, Any] | None = None
            persistence_error: str | None = None

            if read_succeeded:
                try:
                    # Reject NumPy objects, non-finite numbers and other values that
                    # cannot be represented faithfully in the first-stage JSON format.
                    serialized = json.dumps(
                        normalized_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                        allow_nan=False,
                    ) + "\n"
                    derived_path = _atomic_write_derived_json(
                        self.project_root, request.task_id, serialized
                    )
                    reader_ids = sorted({
                        str(item.get("reader_id") or "unknown") for item in reader_results
                    })
                    reader_versions = sorted({
                        str(item.get("reader_version") or "unknown") for item in reader_results
                    })
                    parser_id = ", ".join(reader_ids)
                    parser_version = ", ".join(reader_versions)
                    derived_response = api.register_derived_artifact(
                        str(self.project_root),
                        str(derived_path),
                        source_artifact_ids=[item.artifact_id for item in request.input_artifacts],
                        format_id="json_records",
                        parser_id=parser_id,
                        parser_version=parser_version,
                        parse_status=(
                            "parsed"
                            if all(item.get("status") == "parsed" for item in reader_results)
                            else "partial"
                        ),
                        parse_assurance="unverified",
                        quality_status="not_assessed",
                        analysis_eligibility="not_assessed",
                        use_status="undecided",
                        warnings=reader_warnings,
                        provenance={
                            "operation_id": self.READ_OPERATION,
                            "operation_version": str(read_descriptor.get("operation_version") or "unknown"),
                            "pipeline_task_id": request.task_id,
                            "reader_ids": reader_ids,
                            "reader_versions": reader_versions,
                        },
                    )
                    if not isinstance(derived_response, Mapping):
                        raise TypeError("Data_analysis register_derived_artifact must return a mapping")
                    required_derived_fields = {
                        "artifact_id", "sha256", "format_id", "source_locator", "artifact", "record_path"
                    }
                    missing_derived_fields = required_derived_fields.difference(derived_response)
                    if missing_derived_fields:
                        raise ValueError(
                            "Data_analysis derived Artifact response is missing fields: "
                            + ", ".join(sorted(missing_derived_fields))
                        )
                    derived = dict(derived_response)
                    if not isinstance(derived.get("artifact_id"), str) or not derived["artifact_id"]:
                        raise ValueError("Data_analysis derived Artifact has an invalid artifact_id")
                    if not isinstance(derived.get("sha256"), str) or not re.fullmatch(
                        r"[0-9a-fA-F]{64}", derived["sha256"]
                    ):
                        raise ValueError("Data_analysis derived Artifact has an invalid SHA-256")
                    if derived.get("format_id") != "json_records":
                        raise ValueError("Data_analysis derived Artifact did not retain format_id='json_records'")
                    if not isinstance(derived.get("source_locator"), Mapping):
                        raise ValueError("Data_analysis derived Artifact has an invalid source_locator")
                    if not isinstance(derived.get("artifact"), Mapping):
                        raise ValueError("Data_analysis derived Artifact has no Artifact record description")
                    if not str(derived.get("record_path") or "").strip():
                        raise ValueError("Data_analysis derived Artifact has no record_path")
                    written_hash = hashlib.sha256(derived_path.read_bytes()).hexdigest()
                    if written_hash.lower() != derived["sha256"].lower():
                        raise ValueError("registered derived Artifact SHA-256 does not match the persisted file")
                except Exception as exc:
                    persistence_error = f"{type(exc).__name__}: {exc}"

            run_status = "completed" if read_succeeded and derived is not None else "failed"
            qc_status = "not_assessed" if read_succeeded else "blocked"
            requested_operation = str(request.analysis_task.get("operation_id") or self.READ_OPERATION)
            run_parameters = {
                "pipeline_task_id": request.task_id,
                "requested_operation": requested_operation,
                "reader_requests": [
                    {
                        "artifact_id": item.artifact_id,
                        "format_id": item.format_id or request.parameters.get("format_id"),
                        "reader_id": reader_id,
                    }
                    for item in request.input_artifacts
                ],
                "analysis_parameters": dict(request.parameters),
                "derived_result_format": "json_records" if derived is not None else None,
                "derived_result_relative_path": (
                    derived.get("source_locator", {}).get("stored_relative_path")
                    if derived is not None else None
                ),
            }
            metadata = dict(request.structure_metadata)
            output_descriptors = [derived] if derived is not None else []
            run_warnings = list(reader_warnings + error_messages)
            if persistence_error:
                run_warnings.append("Derived Artifact persistence/registration failed: " + persistence_error)

            run_creation = api.create_dft_analysis_run_from_project(
                project_root=str(self.project_root),
                input_artifact_ids=[item.artifact_id for item in request.input_artifacts],
                output_artifacts=output_descriptors,
                operation_id=self.READ_OPERATION,
                operation_version=str(read_descriptor.get("operation_version") or "unknown"),
                parameters=run_parameters,
                software={
                    "data_analysis": self.data_analysis_version,
                    "reader": ", ".join(
                        str(item.get("reader_id") or "unknown") for item in reader_results
                    ),
                },
                persist=True,
                status=run_status,
                structure_artifact_id=metadata.get("structure_artifact_id"),
                structure_sha256=metadata.get("structure_sha256"),
                approved_model_sha256=metadata.get("approved_model_sha256"),
                upstream_job_reference=request.upstream_job_reference,
                parser_id=", ".join(
                    sorted({str(item.get("reader_id") or "unknown") for item in reader_results})
                ),
                parser_version=", ".join(
                    sorted({str(item.get("reader_version") or "unknown") for item in reader_results})
                ),
                units=metadata.get("units", {}),
                assumptions=tuple(metadata.get("assumptions", ())),
                warnings=tuple(run_warnings),
                qc_status=qc_status,
                environment=metadata.get("environment", {}),
            )
            if not isinstance(run_creation, Mapping) or not isinstance(run_creation.get("analysis_run"), Mapping):
                raise TypeError("Data_analysis create_dft_analysis_run_from_project returned an invalid record")
            analysis_run = dict(run_creation["analysis_run"])
            record_path = run_creation.get("record_path")
            analysis_run_id = analysis_run.get("analysis_run_id")
            if not isinstance(analysis_run_id, str) or not analysis_run_id:
                raise ValueError("Data_analysis Analysis Run record has no analysis_run_id")
            if not record_path:
                raise ValueError("Data_analysis did not persist the Analysis Run record")

            # Confirm the persisted Analysis Run actually contains the registered
            # output Artifact. Never infer success from a successful registration call alone.
            if derived is not None:
                output_ids = list(analysis_run.get("output_artifact_ids", []))
                output_hashes = dict(analysis_run.get("output_hashes", {}))
                if derived["artifact_id"] not in output_ids:
                    raise ValueError("Analysis Run did not retain the registered derived Artifact ID")
                if str(output_hashes.get(derived["artifact_id"], "")).lower() != derived["sha256"].lower():
                    raise ValueError("Analysis Run did not retain the registered derived Artifact SHA-256")

            input_hashes = dict(analysis_run.get("input_hashes", {}))
            for artifact, reader_result in zip(request.input_artifacts, reader_results):
                if str(input_hashes.get(artifact.artifact_id, "")).lower() != str(
                    reader_result.get("source_sha256", "")
                ).lower():
                    raise ValueError(
                        f"Analysis Run input hash for {artifact.artifact_id} does not match the bytes read by Data_analysis"
                    )

            normalized_for_package = dict(normalized_payload)
            normalized_for_package["derived_artifacts"] = [derived] if derived is not None else []
            normalized_for_package["persistence_status"] = (
                "registered" if derived is not None else "failed"
            )
            if persistence_error:
                normalized_for_package["persistence_error"] = persistence_error

            post_run_warnings: list[str] = []
            normalized_result: Mapping[str, Any] | None = None
            try:
                normalized_response = api.run_dft_operation(
                    self.NORMALIZE_OPERATION,
                    analysis_run=analysis_run,
                    normalized_result=normalized_for_package,
                )
                if not isinstance(normalized_response, Mapping) or normalized_response.get("status") != "completed":
                    raise RuntimeError(
                        "Data_analysis normalized-result operation failed: "
                        + str((normalized_response or {}).get("error", "unknown operation response"))
                    )
                normalized_result = normalized_response.get("result")
            except Exception as exc:
                post_run_warnings.append(f"Normalized-result packaging failed: {type(exc).__name__}: {exc}")

            evidence_package: Mapping[str, Any] | None = None
            try:
                evidence_response = api.build_evidence_package(
                    dft_analysis_runs=[record_path],
                    question=str(request.analysis_task.get("question") or "DFT artifact parsing and provenance"),
                )
                if not isinstance(evidence_response, Mapping):
                    raise TypeError("Data_analysis build_evidence_package must return a mapping")
                evidence_package = dict(evidence_response)
            except Exception as exc:
                post_run_warnings.append(f"Evidence Package construction failed: {type(exc).__name__}: {exc}")

            output_refs: tuple[ArtifactRef, ...] = ()
            if derived is not None:
                locator = dict(derived["source_locator"])
                relative_path = locator.get("stored_relative_path") or derived.get("relative_path")
                output_refs = (
                    ArtifactRef(
                        artifact_id=str(derived["artifact_id"]),
                        sha256=str(derived["sha256"]),
                        format_id=str(derived["format_id"]),
                        media_type="application/json",
                        uri=str(self.project_root / str(relative_path)) if relative_path else None,
                        storage_mode="project",
                        source_system="Data_analysis",
                    ),
                )

            evidence_refs: tuple[EvidenceRef, ...] = ()
            evidence_id = evidence_package.get("evidence_package_id") if evidence_package else None
            source_ids = tuple(dict.fromkeys(
                list(analysis_run.get("input_artifact_ids", []))
                + list(analysis_run.get("output_artifact_ids", []))
            ))
            source_hashes = {
                **dict(analysis_run.get("input_hashes", {})),
                **dict(analysis_run.get("output_hashes", {})),
            }
            if evidence_id and source_ids:
                evidence_refs = (
                    EvidenceRef(
                        evidence_id=str(evidence_id),
                        source_artifact_ids=source_ids,
                        source_hashes={key: value for key, value in source_hashes.items() if key in source_ids},
                        source_locator=str(record_path),
                        contract_id=str(evidence_package.get("contract_id")) if evidence_package.get("contract_id") else None,
                        contract_version=str(evidence_package.get("contract_version")) if evidence_package.get("contract_version") else None,
                    ),
                )

            provenance = ProvenanceRecord(
                task_id=request.task_id,
                component="Data_analysis",
                operation=self.READ_OPERATION,
                operation_version=str(read_descriptor.get("operation_version") or "unknown"),
                input_artifacts=request.input_artifacts,
                output_artifacts=output_refs,
                upstream_job_reference=request.upstream_job_reference,
                parameters=run_parameters,
                software=dict(analysis_run.get("software", {})),
                warnings=tuple(run_warnings + post_run_warnings),
            )

            warnings = list(reader_warnings)
            if persistence_error:
                warnings.append(
                    "Reader completed in memory, but its normalized JSON result could not be fully persisted and registered: "
                    + persistence_error
                )
            warnings.extend(post_run_warnings)

            if not read_succeeded:
                outcome_status = TaskStatus.FAILED
                error = "; ".join(error_messages) or "Data_analysis reader failed"
            elif persistence_error or post_run_warnings:
                outcome_status = TaskStatus.WARNING
                error = None
            else:
                outcome_status = TaskStatus.SUCCEEDED
                error = None

            diagnostics: list[Diagnostic] = []
            if not read_succeeded:
                diagnostics.append(Diagnostic(
                    first_failure_code,
                    error or "Data_analysis DFT reader failed.",
                    DiagnosticSeverity.ERROR,
                ))
            elif persistence_error:
                diagnostics.append(Diagnostic(
                    "DFT_DERIVED_ARTIFACT_PERSISTENCE_FAILED",
                    persistence_error,
                    DiagnosticSeverity.WARNING,
                ))
            if post_run_warnings:
                diagnostics.append(Diagnostic(
                    "DFT_POST_RUN_PACKAGING_WARNING",
                    "; ".join(post_run_warnings),
                    DiagnosticSeverity.WARNING,
                ))
            if read_succeeded:
                diagnostics.append(Diagnostic(
                    "DFT_SCIENTIFIC_QC_NOT_ASSESSED",
                    "Reader parsing and Artifact custody completed; scientific QC was not assessed by this adapter.",
                    DiagnosticSeverity.INFO,
                ))

            return AnalysisOutcome(
                task_id=request.task_id,
                analysis_run_id=analysis_run_id,
                status=outcome_status,
                output_artifacts=output_refs,
                evidence_refs=evidence_refs,
                provenance=provenance,
                qc_status=qc_status,
                qc={
                    "status": qc_status,
                    "analysis_run_status": run_status,
                    "reader_statuses": [item.get("status") for item in reader_results],
                    "scientific_qc": "not_assessed",
                    "derived_output_artifact_registered": derived is not None,
                    "persistence_status": "registered" if derived is not None else (
                        "failed" if persistence_error else "not_attempted"
                    ),
                    "persistence_error": persistence_error,
                },
                warnings=tuple(warnings),
                error=error,
                execution_mode="real",
                result={
                    "reader_results": reader_results,
                    "reader_catalogues": reader_catalogues,
                    "normalized_result": normalized_result,
                    "derived_artifact": derived,
                    "derived_file_path": str(derived_path) if derived_path else None,
                    "persistence_error": persistence_error,
                    "analysis_run_record_path": str(record_path),
                },
                analysis_run_record=analysis_run,
                evidence_package=evidence_package,
                diagnostics=tuple(diagnostics),
            )
        except ContractError as exc:
            return self._failure(request, "ARTIFACT_RESOLUTION_FAILED", str(exc))
        except FileNotFoundError as exc:
            return self._failure(
                request, "DA_ARTIFACT_NOT_REGISTERED_OR_SOURCE_MISSING", str(exc)
            )
        except ValueError as exc:
            return self._failure(request, "DA_ARTIFACT_PROVENANCE_REJECTED", str(exc))
        except (ImportError, ModuleNotFoundError) as exc:
            return self._failure(request, "OPTIONAL_DEPENDENCY_UNAVAILABLE", str(exc))
        except Exception as exc:
            return self._failure(
                request, "DATA_ANALYSIS_ADAPTER_ERROR",
                f"{type(exc).__name__}: {exc}",
            )

class RealCSTAdapter:
    """Lazy bridge to the verified chem-scitoolkit finite-system and DFT APIs."""

    WORKFLOW_OPERATIONS = {
        "cp2k.validate_input": "validate_cp2k_input",
        "cp2k.validate_output": "validate_cp2k_output",
        "charge.estimate_hirshfeld": "estimate_hirshfeld_charges",
        "charge.validate_bader": "validate_bader_true_results",
        "pdos.normalize": "normalize_cp2k_pdos",
        "cube.read": "read_cube",
        "cube.validate_compatibility": "validate_cube_compatibility",
        "cube.subtract_fields": "subtract_cube_fields",
        "vacuum.detect_plateau": "detect_vacuum_plateau",
        "vacuum.validate_reference": "validate_vacuum_energy_reference",
        "thermochemistry.ase_harmonic": "ase_harmonic_thermochemistry",
    }

    def __init__(
        self,
        *,
        builder_cls: Any | None = None,
        workflows: Any | None = None,
        style: Any | None = None,
        chem_scitoolkit_version: str | None = None,
    ) -> None:
        self.builder_cls = builder_cls
        self.workflows = workflows
        self.style = style
        self.chem_scitoolkit_version = chem_scitoolkit_version or _package_version("chem-scitoolkit")

    def _load_components(self) -> tuple[Any, Any, Any]:
        builder_cls, workflows, style = self.builder_cls, self.workflows, self.style
        if builder_cls is None:
            builder_module = importlib.import_module("my_sci_toolkit.simulation.cp2k.builder")
            builder_cls = getattr(builder_module, "CP2KInputBuilder")
        if workflows is None:
            workflows = importlib.import_module("my_sci_toolkit.simulation.cp2k.dft_workflows")
        if style is None:
            style = importlib.import_module("my_sci_toolkit.viz.style")
        return builder_cls, workflows, style

    @staticmethod
    def _artifact_paths(request: CSTTaskRequest) -> list[Path]:
        paths: list[Path] = []
        for artifact in request.input_artifacts:
            if artifact.mock:
                raise ContractError(f"real CST adapter refuses mock Artifact {artifact.artifact_id}")
            if not artifact.uri:
                continue
            parsed = urlparse(artifact.uri)
            if parsed.scheme == "file":
                value = unquote(parsed.path)
                if os.name == "nt" and len(value) >= 3 and value[0] == "/" and value[2] == ":":
                    value = value[1:]
                paths.append(Path(value).expanduser().resolve())
            elif not parsed.scheme:
                paths.append(Path(artifact.uri).expanduser().resolve())
            else:
                raise ContractError(
                    f"Artifact {artifact.artifact_id} URI scheme {parsed.scheme!r} is not a local file URI"
                )
        return paths

    @staticmethod
    def _non_passing_result(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        if value.get("passed") is False or value.get("supported") is False or value.get("compatible") is False:
            return True
        return str(value.get("status", "")).lower() in {"failed", "failed_or_incomplete", "unsupported", "blocked"}

    def _failure(self, request: CSTTaskRequest, code: str, message: str) -> AdapterOutcome:
        return AdapterOutcome(
            task_id=request.task_id,
            status=TaskStatus.FAILED,
            structured_result={"adapter_error_code": code},
            output_artifacts=(),
            diagnostics=(Diagnostic(code, message, DiagnosticSeverity.ERROR),),
            provenance=ProvenanceRecord(
                task_id=request.task_id,
                component="chem-scitoolkit",
                operation=request.operation,
                input_artifacts=request.input_artifacts,
                upstream_job_reference=request.upstream_job_reference,
                parameters=request.parameters,
                software={"pipeline_adapter": "real-chem-scitoolkit-v1"},
            ),
            error=message,
            execution_mode="real",
            scientific_validation="not_evaluated",
        )

    def execute(self, request: CSTTaskRequest) -> AdapterOutcome:
        try:
            builder_cls, workflows, style = self._load_components()
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            return self._failure(
                request, "CST_DEPENDENCY_UNAVAILABLE",
                "chem-scitoolkit public API is unavailable in this runtime: " + str(exc),
            )
        try:
            arguments = dict(request.parameters)
            arguments.update(dict(request.task_config.get("arguments", {})))
            artifact_paths = self._artifact_paths(request)
            primary_path = artifact_paths[0] if artifact_paths else None

            if request.operation == "cp2k.build_finite_system":
                builder_options = dict(request.task_config.get("builder_options", {}))
                builder = builder_cls(**builder_options)
                value = builder.build_finite_system(**arguments)
                text_value = str(value)
                structured = {
                    "result_kind": "cp2k_input_text",
                    "input_text": text_value,
                    "sha256": hashlib.sha256(text_value.encode("utf-8")).hexdigest(),
                    "artifact_registered": False,
                }
                component_version = self.chem_scitoolkit_version
            elif request.operation in self.WORKFLOW_OPERATIONS:
                function = getattr(workflows, self.WORKFLOW_OPERATIONS[request.operation], None)
                if not callable(function):
                    return self._failure(
                        request, "CST_API_MISSING",
                        f"chem-scitoolkit dft_workflows is missing {self.WORKFLOW_OPERATIONS[request.operation]}",
                    )
                if primary_path is not None:
                    if request.operation == "cp2k.validate_input":
                        arguments.setdefault("input_path", primary_path)
                    elif request.operation == "cp2k.validate_output":
                        arguments.setdefault("log_path", primary_path)
                    elif request.operation == "cube.read":
                        arguments.setdefault("path", primary_path)
                    elif request.operation == "pdos.normalize":
                        arguments.setdefault("pdos_paths", artifact_paths)
                value = function(**arguments)
                structured = dict(value) if isinstance(value, Mapping) else {"value": value}
                component_version = self.chem_scitoolkit_version
            elif request.operation in {"figure.apply_profile", "figure.save_profiled"}:
                function_name = (
                    "apply_figure_profile" if request.operation == "figure.apply_profile"
                    else "save_figure_profiled"
                )
                function = getattr(style, function_name, None)
                if not callable(function):
                    return self._failure(request, "CST_API_MISSING", f"chem-scitoolkit style API is missing {function_name}")
                value = function(**arguments)
                structured = dict(value) if isinstance(value, Mapping) else {"value": str(value) if isinstance(value, Path) else value}
                component_version = self.chem_scitoolkit_version
            else:
                return self._failure(
                    request, "CST_OPERATION_UNSUPPORTED",
                    f"Pipeline CST adapter does not map operation {request.operation!r}.",
                )

            failed_assessment = self._non_passing_result(structured)
            diagnostics = ()
            status = TaskStatus.SUCCEEDED
            if failed_assessment:
                status = TaskStatus.WARNING
                diagnostics = (
                    Diagnostic(
                        "CST_ASSESSMENT_NOT_PASSED",
                        "Upstream assessment returned a non-passing/unsupported state; raw structured result is preserved.",
                        DiagnosticSeverity.WARNING,
                    ),
                )
            provenance = ProvenanceRecord(
                task_id=request.task_id,
                component="chem-scitoolkit",
                operation=request.operation,
                operation_version=component_version,
                input_artifacts=request.input_artifacts,
                output_artifacts=(),
                upstream_job_reference=request.upstream_job_reference,
                parameters={**dict(request.parameters), **dict(request.task_config.get("arguments", {}))},
                software={"chem_scitoolkit": component_version},
                warnings=tuple(item.message for item in diagnostics),
            )
            return AdapterOutcome(
                task_id=request.task_id,
                status=status,
                structured_result=structured,
                output_artifacts=(),
                diagnostics=diagnostics,
                provenance=provenance,
                execution_mode="real",
                scientific_validation="not_evaluated",
            )
        except ContractError as exc:
            return self._failure(request, "CST_INPUT_REFERENCE_INVALID", str(exc))
        except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
            message = str(exc)
            code = "CST_DEPENDENCY_UNAVAILABLE" if (
                "optional" in message.lower() or "install" in message.lower()
            ) else "CST_INPUT_UNAVAILABLE"
            return self._failure(request, code, message)
        except Exception as exc:
            return self._failure(request, "CST_OPERATION_FAILED", f"{type(exc).__name__}: {exc}")
