"""Synthetic adapters for interface/control-flow tests; no science is computed."""
from __future__ import annotations

from typing import Sequence

from .models import (
    AdapterOutcome,
    AnalysisOutcome,
    AnalysisRequest,
    ArtifactRef,
    CSTTaskRequest,
    ContractError,
    Diagnostic,
    DiagnosticSeverity,
    EvidenceRef,
    HashVerification,
    HpcJobRecord,
    HpcPreflight,
    HpcStageResult,
    HpcState,
    HpcStatus,
    HpcTaskManifest,
    JobReference,
    ProvenanceRecord,
    TaskStatus,
)


def _mock_artifact(source: str, artifact_id: str, uri_suffix: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        format_id="mock-reference",
        uri=f"mock://{source}/{uri_suffix}",
        source_system=f"Mock:{source}",
        mock=True,
    )


class MockCSTAdapter:
    """Pass-through contract stub; it never evaluates a scientific operation."""

    execution_mode = "mock"

    def __init__(self, status: TaskStatus | str = TaskStatus.SUCCEEDED) -> None:
        try:
            self.status = TaskStatus(status)
        except ValueError as exc:
            raise ContractError(f"unsupported mock CST status: {status}") from exc
        if self.status not in {
            TaskStatus.SUCCEEDED, TaskStatus.WARNING, TaskStatus.FAILED,
            TaskStatus.PENDING, TaskStatus.UNAVAILABLE,
        }:
            raise ContractError("unsupported mock CST status")
        self.last_request: CSTTaskRequest | None = None

    def execute(self, request: CSTTaskRequest) -> AdapterOutcome:
        self.last_request = request
        output = ()
        if self.status in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}:
            output = (_mock_artifact("cst", f"mock-cst-{request.task_id}", f"{request.task_id}/result"),)
        diagnostics: tuple[Diagnostic, ...] = ()
        if self.status == TaskStatus.WARNING:
            diagnostics = (
                Diagnostic("MOCK_CST_WARNING", "Synthetic validation warning; no scientific QC was performed",
                           DiagnosticSeverity.WARNING),
            )
        elif self.status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE}:
            diagnostics = (
                Diagnostic(
                    "MOCK_CST_" + self.status.value.upper(),
                    "Synthetic CST validation did not run successfully",
                    DiagnosticSeverity.ERROR,
                ),
            )
        error = (
            "Synthetic CST adapter " + self.status.value + "; no calculation was run"
            if self.status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE} else None
        )
        provenance = ProvenanceRecord(
            task_id=request.task_id,
            component="MockCSTAdapter",
            operation=request.operation,
            operation_version="mock-contract-v1",
            input_artifacts=request.input_artifacts,
            output_artifacts=output,
            upstream_job_reference=request.upstream_job_reference,
            parameters=request.parameters,
            software={"adapter": "mock-contract-v1"},
            warnings=tuple(item.message for item in diagnostics if item.severity == DiagnosticSeverity.WARNING),
        )
        return AdapterOutcome(
            task_id=request.task_id,
            status=self.status,
            structured_result={
                "execution_mode": "mock",
                "operation": request.operation,
                "result_kind": "interface-placeholder",
                "scientific_values_generated": False,
            },
            output_artifacts=output,
            diagnostics=diagnostics,
            provenance=provenance,
            error=error,
            execution_mode="mock",
            scientific_validation="not_evaluated",
        )


class MockDataAnalysisAdapter:
    """Returns synthetic IDs/references for orchestration tests; no Artifact Store is created."""

    execution_mode = "mock"

    def __init__(
        self,
        status: TaskStatus | str = TaskStatus.SUCCEEDED,
        *,
        failure_code: str = "MOCK_READER_FAILED",
        failure_message: str | None = None,
    ) -> None:
        try:
            self.status = TaskStatus(status)
        except ValueError as exc:
            raise ContractError(f"unsupported mock Data_analysis status: {status}") from exc
        if self.status not in {
            TaskStatus.SUCCEEDED, TaskStatus.WARNING, TaskStatus.FAILED,
            TaskStatus.PENDING, TaskStatus.UNAVAILABLE,
        }:
            raise ContractError("unsupported mock Data_analysis status")
        self.failure_code = failure_code
        self.failure_message = failure_message
        self.last_request: AnalysisRequest | None = None

    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        self.last_request = request
        successful = self.status in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}
        analysis_run_id = f"mock-analysis-run-{request.task_id}" if successful else None
        output = ()
        evidence = ()
        evidence_package = None
        analysis_run_record = {}
        if successful:
            output = (
                _mock_artifact(
                    "data-analysis",
                    f"mock-analysis-artifact-{request.task_id}",
                    f"{request.task_id}/analysis",
                ),
            )
            known_hashes = {
                item.artifact_id: item.sha256
                for item in request.input_artifacts
                if item.sha256 is not None
            }
            source_ids = tuple(item.artifact_id for item in request.input_artifacts)
            evidence_id = f"mock-evidence-{request.task_id}"
            evidence = (
                EvidenceRef(
                    evidence_id=evidence_id,
                    source_artifact_ids=source_ids,
                    source_hashes=known_hashes,
                    source_locator=f"mock://evidence/{request.task_id}",
                    contract_id="mock-evidence-reference",
                    contract_version="0",
                ),
            )
            analysis_run_record = {
                "analysis_run_id": analysis_run_id,
                "operation_id": request.operation,
                "input_artifact_ids": [item.artifact_id for item in request.input_artifacts],
                "output_artifact_ids": [item.artifact_id for item in output],
                "input_hashes": known_hashes,
                "output_hashes": {},
                "status": self.status.value,
                "qc_status": "not_evaluated",
                "execution_mode": "mock",
            }
            evidence_package = {
                "evidence_package_id": evidence_id,
                "execution_mode": "mock",
                "analysis_run_id": analysis_run_id,
                "input_artifact_ids": analysis_run_record["input_artifact_ids"],
                "output_artifact_ids": analysis_run_record["output_artifact_ids"],
                "qc_status": "not_evaluated",
            }

        warnings: tuple[str, ...] = ()
        diagnostics: tuple[Diagnostic, ...] = ()
        if self.status == TaskStatus.WARNING:
            warnings = ("Synthetic Data_analysis warning for orchestration testing",)
            diagnostics = (
                Diagnostic("MOCK_DA_WARNING", warnings[0], DiagnosticSeverity.WARNING),
            )
        error = None
        if self.status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE}:
            error = self.failure_message or (
                "Synthetic Data_analysis " + self.status.value + "; no output Artifact was registered"
            )
            diagnostics = (
                Diagnostic(self.failure_code, error, DiagnosticSeverity.ERROR),
            )

        provenance = ProvenanceRecord(
            task_id=request.task_id,
            component="MockDataAnalysisAdapter",
            operation=request.operation,
            operation_version="mock-contract-v1",
            input_artifacts=request.input_artifacts,
            output_artifacts=output,
            upstream_job_reference=request.upstream_job_reference,
            parameters=request.parameters,
            software={"adapter": "mock-contract-v1"},
            warnings=warnings,
        )
        return AnalysisOutcome(
            task_id=request.task_id,
            analysis_run_id=analysis_run_id,
            status=self.status,
            output_artifacts=output,
            evidence_refs=evidence,
            provenance=provenance,
            qc_status="not_evaluated",
            qc={"status": "not_evaluated", "checks": [], "scientific_validation": False},
            warnings=warnings,
            error=error,
            execution_mode="mock",
            analysis_run_record=analysis_run_record,
            evidence_package=evidence_package,
            diagnostics=diagnostics,
        )


class MockHpcAdapter:
    """Deterministic async lifecycle stub; scheduler completion is not success."""

    _SCHEDULER_SEQUENCE = ("SUBMITTED", "PENDING", "RUNNING", "COMPLETED")

    def __init__(self, application_state: str = "succeeded", hashes_valid: bool = True) -> None:
        if application_state not in {"unknown", "succeeded", "failed"}:
            raise ContractError("application_state must be unknown, succeeded, or failed")
        self.application_state = application_state
        self.hashes_valid = hashes_valid
        self._staged: dict[str, HpcTaskManifest] = {}
        self._manifests: dict[str, HpcTaskManifest] = {}
        self._polls: dict[str, int] = {}
        self._record_checked: set[str] = set()
        self._hash_checks: dict[str, bool] = {}

    def preflight(self) -> HpcPreflight:
        return HpcPreflight("mock-hpc", True, ("submit", "status", "record", "selective-retrieve", "hash-check"))

    def stage_inputs(self, task_manifest: HpcTaskManifest) -> HpcStageResult:
        if not self.preflight().ready:
            raise ContractError("HPC preflight did not pass")
        self._staged[task_manifest.task_id] = task_manifest
        return HpcStageResult(task_manifest.task_id, task_manifest.input_artifacts, f"mock-stage-{task_manifest.task_id}")

    def submit(self, task_manifest: HpcTaskManifest) -> JobReference:
        if task_manifest.task_id not in self._staged:
            raise ContractError("stage_inputs must complete before submit")
        job = JobReference(f"mock-job-{task_manifest.task_id}", task_manifest.task_id, "mock-hpc")
        self._manifests[job.job_id] = task_manifest
        self._polls[job.job_id] = 0
        return job

    def _require_job(self, job_reference: JobReference) -> HpcTaskManifest:
        try:
            manifest = self._manifests[job_reference.job_id]
        except KeyError as exc:
            raise ContractError(f"unknown mock job: {job_reference.job_id}") from exc
        if manifest.task_id != job_reference.task_id:
            raise ContractError("job reference task_id does not match submitted task")
        return manifest

    def _scheduler_state(self, job_reference: JobReference) -> str:
        index = min(self._polls[job_reference.job_id], len(self._SCHEDULER_SEQUENCE) - 1)
        self._polls[job_reference.job_id] += 1
        return self._SCHEDULER_SEQUENCE[index]

    def get_status(self, job_reference: JobReference) -> HpcStatus:
        self._require_job(job_reference)
        scheduler = self._scheduler_state(job_reference)
        if scheduler != "COMPLETED":
            state = {
                "SUBMITTED": HpcState.SUBMITTED,
                "PENDING": HpcState.QUEUED,
                "RUNNING": HpcState.RUNNING,
            }[scheduler]
        elif job_reference.job_id not in self._record_checked:
            state = HpcState.AWAITING_VALIDATION
        elif self.application_state == "failed":
            state = HpcState.FAILED
        elif self.application_state != "succeeded" or job_reference.job_id not in self._hash_checks:
            state = HpcState.AWAITING_VALIDATION
        elif not self._hash_checks[job_reference.job_id]:
            state = HpcState.FAILED
        else:
            state = HpcState.SUCCEEDED
        return HpcStatus(
            job_reference=job_reference,
            state=state,
            scheduler_state=scheduler,
            application_state=self.application_state if job_reference.job_id in self._record_checked else "unknown",
            hashes_verified=self._hash_checks.get(job_reference.job_id, False),
        )

    def get_record(self, job_reference: JobReference) -> HpcJobRecord:
        manifest = self._require_job(job_reference)
        self._record_checked.add(job_reference.job_id)
        scheduler = "COMPLETED" if self._polls[job_reference.job_id] >= 4 else self._SCHEDULER_SEQUENCE[max(0, self._polls[job_reference.job_id] - 1)]
        return HpcJobRecord(
            job_reference=job_reference,
            scheduler_state=scheduler,
            application_state=self.application_state,
            application_exit_code=0 if self.application_state == "succeeded" else (1 if self.application_state == "failed" else None),
            completion_evidence="mock application marker" if self.application_state == "succeeded" else None,
            output_artifacts=manifest.expected_outputs,
        )

    def retrieve_selected_outputs(
        self, job_reference: JobReference, output_selection: Sequence[str]
    ) -> tuple[ArtifactRef, ...]:
        manifest = self._require_job(job_reference)
        if self._polls[job_reference.job_id] < 4:
            raise ContractError("outputs are unavailable before scheduler completion")
        by_id = {item.artifact_id: item for item in manifest.expected_outputs}
        missing = [artifact_id for artifact_id in output_selection if artifact_id not in by_id]
        if missing:
            raise ContractError(f"requested outputs are not declared: {', '.join(missing)}")
        return tuple(by_id[item] for item in output_selection)

    def verify_hashes(self, manifest: Sequence[ArtifactRef]) -> HashVerification:
        if not manifest:
            raise ContractError("hash verification requires at least one artifact reference")
        artifact_ids = {item.artifact_id for item in manifest}
        job_id = next((key for key, value in self._manifests.items() if artifact_ids.issubset({x.artifact_id for x in value.expected_outputs})), None)
        if job_id is None:
            raise ContractError("hash manifest does not match a submitted job's declared outputs")
        self._hash_checks[job_id] = self.hashes_valid
        failures = () if self.hashes_valid else ("synthetic hash mismatch",)
        return HashVerification(
            verified=self.hashes_valid,
            checked_artifact_ids=tuple(item.artifact_id for item in manifest),
            failures=failures,
            verification_mode="mock_scenario_no_bytes_hashed",
        )
