"""Versioned, dependency-free contracts for future scientific Skill adapters.

These are Pipeline-side models. They do not claim to be upstream Skill APIs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class ContractError(ValueError):
    """Raised when a request, response, or reference violates the contract."""


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")


def _require_mapping(name: str, value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")


class TaskStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_VALIDATION = "awaiting_validation"
    SUCCEEDED = "succeeded"
    WARNING = "warning"
    FAILED = "failed"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ArtifactRef:
    """Opaque reference to an artifact managed by an upstream system."""

    artifact_id: str
    sha256: str | None = None
    format_id: str | None = None
    media_type: str | None = None
    uri: str | None = None
    storage_mode: str | None = None
    source_system: str | None = None
    mock: bool = False

    def __post_init__(self) -> None:
        _require_text("artifact_id", self.artifact_id)
        if self.sha256 is not None and not _SHA256_RE.fullmatch(self.sha256):
            raise ContractError("sha256 must be 64 hexadecimal characters when supplied")
        if self.mock and self.uri is not None and not self.uri.startswith("mock://"):
            raise ContractError("mock artifact URIs must use the mock:// scheme")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO

    def __post_init__(self) -> None:
        _require_text("diagnostic.code", self.code)
        _require_text("diagnostic.message", self.message)


@dataclass(frozen=True)
class ProvenanceRecord:
    task_id: str
    component: str
    operation: str
    operation_version: str | None = None
    input_artifacts: tuple[ArtifactRef, ...] = ()
    output_artifacts: tuple[ArtifactRef, ...] = ()
    upstream_job_reference: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    software: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("provenance.task_id", self.task_id)
        _require_text("provenance.component", self.component)
        _require_text("provenance.operation", self.operation)
        _require_mapping("provenance.parameters", self.parameters)
        _require_mapping("provenance.software", self.software)


@dataclass(frozen=True)
class CSTTaskRequest:
    task_id: str
    operation: str
    task_config: Mapping[str, Any] = field(default_factory=dict)
    input_artifacts: tuple[ArtifactRef, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    upstream_job_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("task_id", self.task_id)
        if self.upstream_job_reference is not None:
            _require_text("upstream_job_reference", self.upstream_job_reference)
        _require_text("operation", self.operation)
        _require_mapping("task_config", self.task_config)
        _require_mapping("parameters", self.parameters)
        _require_mapping("metadata", self.metadata)
        if not self.input_artifacts and not self.task_config:
            raise ContractError("CST request requires task_config or at least one input artifact")


@dataclass(frozen=True)
class AdapterOutcome:
    task_id: str
    status: TaskStatus
    structured_result: Mapping[str, Any]
    output_artifacts: tuple[ArtifactRef, ...]
    diagnostics: tuple[Diagnostic, ...]
    provenance: ProvenanceRecord
    error: str | None = None
    execution_mode: str = "real"
    scientific_validation: str = "not_evaluated"

    def __post_init__(self) -> None:
        _require_text("outcome.task_id", self.task_id)
        _require_mapping("structured_result", self.structured_result)
        if self.status == TaskStatus.FAILED and not self.error:
            raise ContractError("failed adapter outcome requires an error message")
        if self.status != TaskStatus.FAILED and self.error is not None:
            raise ContractError("error must be absent unless adapter status is failed")
        if self.status == TaskStatus.WARNING and not any(
            item.severity == DiagnosticSeverity.WARNING for item in self.diagnostics
        ):
            raise ContractError("warning outcome requires at least one warning diagnostic")
        if self.execution_mode == "mock" and self.scientific_validation != "not_evaluated":
            raise ContractError("mock outcomes cannot claim scientific validation")


@dataclass(frozen=True)
class AnalysisRequest:
    task_id: str
    operation: str
    input_artifacts: tuple[ArtifactRef, ...]
    analysis_task: Mapping[str, Any]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    structure_metadata: Mapping[str, Any] = field(default_factory=dict)
    upstream_job_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("analysis.task_id", self.task_id)
        if self.upstream_job_reference is not None:
            _require_text("analysis.upstream_job_reference", self.upstream_job_reference)
        _require_text("analysis.operation", self.operation)
        if not self.input_artifacts:
            raise ContractError("analysis request requires at least one input artifact")
        _require_mapping("analysis_task", self.analysis_task)
        if not self.analysis_task:
            raise ContractError("analysis_task must not be empty")
        _require_mapping("analysis.parameters", self.parameters)
        _require_mapping("structure_metadata", self.structure_metadata)
        _require_mapping("analysis.metadata", self.metadata)


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    source_artifact_ids: tuple[str, ...]
    source_hashes: Mapping[str, str] = field(default_factory=dict)
    source_locator: str | None = None
    contract_id: str | None = None
    contract_version: str | None = None

    def __post_init__(self) -> None:
        _require_text("evidence_id", self.evidence_id)
        if not self.source_artifact_ids:
            raise ContractError("evidence reference must retain source artifact IDs")
        _require_mapping("evidence.source_hashes", self.source_hashes)
        for artifact_id, digest in self.source_hashes.items():
            _require_text("evidence source artifact ID", artifact_id)
            if not _SHA256_RE.fullmatch(digest):
                raise ContractError(f"invalid SHA-256 for evidence source {artifact_id}")


@dataclass(frozen=True)
class AnalysisOutcome:
    task_id: str
    analysis_run_id: str | None
    status: TaskStatus
    output_artifacts: tuple[ArtifactRef, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    provenance: ProvenanceRecord
    qc_status: str = "not_evaluated"
    qc: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error: str | None = None
    execution_mode: str = "real"
    result: Mapping[str, Any] = field(default_factory=dict)
    analysis_run_record: Mapping[str, Any] = field(default_factory=dict)
    evidence_package: Mapping[str, Any] | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        _require_text("analysis outcome.task_id", self.task_id)
        if self.analysis_run_id is not None:
            _require_text("analysis_run_id", self.analysis_run_id)
        _require_mapping("analysis.qc", self.qc)
        _require_mapping("analysis.result", self.result)
        _require_mapping("analysis_run_record", self.analysis_run_record)
        if self.evidence_package is not None:
            _require_mapping("evidence_package", self.evidence_package)
        if self.status == TaskStatus.FAILED and not self.error:
            raise ContractError("failed analysis outcome requires an error message")
        if self.status != TaskStatus.FAILED and self.error is not None:
            raise ContractError("analysis error must be absent unless status is failed")
        if self.execution_mode == "mock" and self.qc_status != "not_evaluated":
            raise ContractError("mock analysis cannot claim a scientific QC result")


class HpcState(str, Enum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_VALIDATION = "awaiting_validation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HpcTaskManifest:
    task_id: str
    input_artifacts: tuple[ArtifactRef, ...]
    payload: Mapping[str, Any] = field(default_factory=dict)
    expected_outputs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        _require_text("HPC task_id", self.task_id)
        if not self.input_artifacts:
            raise ContractError("HPC task manifest requires input artifacts")
        _require_mapping("HPC manifest payload", self.payload)


@dataclass(frozen=True)
class HpcPreflight:
    backend_id: str
    ready: bool
    capabilities: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class HpcStageResult:
    task_id: str
    staged_artifacts: tuple[ArtifactRef, ...]
    stage_reference: str


@dataclass(frozen=True)
class JobReference:
    job_id: str
    task_id: str
    backend_id: str

    def __post_init__(self) -> None:
        _require_text("job_id", self.job_id)
        _require_text("job_reference.task_id", self.task_id)
        _require_text("backend_id", self.backend_id)


@dataclass(frozen=True)
class HpcStatus:
    job_reference: JobReference
    state: HpcState
    scheduler_state: str
    application_state: str = "unknown"
    hashes_verified: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class HpcJobRecord:
    job_reference: JobReference
    scheduler_state: str
    application_state: str
    application_exit_code: int | None = None
    completion_evidence: str | None = None
    output_artifacts: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True)
class HashVerification:
    verified: bool
    checked_artifact_ids: tuple[str, ...]
    failures: tuple[str, ...] = ()
    verification_mode: str = "real_sha256"

    def __post_init__(self) -> None:
        if self.verified and self.failures:
            raise ContractError("successful hash verification cannot contain failures")
        if not self.checked_artifact_ids:
            raise ContractError("hash verification must identify the checked artifacts")
