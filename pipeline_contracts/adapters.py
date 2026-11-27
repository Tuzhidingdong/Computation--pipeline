"""Pipeline-side Protocols. Method names here are not upstream APIs."""
from __future__ import annotations

from typing import Protocol, Sequence

from .models import (
    AdapterOutcome,
    AnalysisOutcome,
    AnalysisRequest,
    CSTTaskRequest,
    HashVerification,
    HpcJobRecord,
    HpcPreflight,
    HpcStageResult,
    HpcStatus,
    HpcTaskManifest,
    JobReference,
    ArtifactRef,
)


class CSTAdapter(Protocol):
    def execute(self, request: CSTTaskRequest) -> AdapterOutcome:
        """Run one requested chem-scitoolkit operation through an adapter."""


class DataAnalysisAdapter(Protocol):
    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        """Register/execute analysis using Data_analysis-owned records."""


class HpcAdapter(Protocol):
    def preflight(self) -> HpcPreflight: ...

    def stage_inputs(self, task_manifest: HpcTaskManifest) -> HpcStageResult: ...

    def submit(self, task_manifest: HpcTaskManifest) -> JobReference: ...

    def get_status(self, job_reference: JobReference) -> HpcStatus: ...

    def get_record(self, job_reference: JobReference) -> HpcJobRecord: ...

    def retrieve_selected_outputs(
        self, job_reference: JobReference, output_selection: Sequence[str]
    ) -> tuple[ArtifactRef, ...]: ...

    def verify_hashes(self, manifest: Sequence[ArtifactRef]) -> HashVerification: ...
