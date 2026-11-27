"""Small end-to-end adapter handoff; deliberately not a workflow engine."""
from __future__ import annotations

from dataclasses import dataclass

from .adapters import CSTAdapter, DataAnalysisAdapter
from .models import AnalysisOutcome, AnalysisRequest, ArtifactRef, AdapterOutcome, CSTTaskRequest, ContractError, TaskStatus
from .mocks import MockCSTAdapter, MockDataAnalysisAdapter


@dataclass(frozen=True)
class MockIntegrationResult:
    cst: AdapterOutcome
    analysis: AnalysisOutcome


def run_mock_integration(
    cst_adapter: CSTAdapter | None = None,
    analysis_adapter: DataAnalysisAdapter | None = None,
) -> MockIntegrationResult:
    """Pass a mock computation ArtifactRef into a mock analysis request."""
    cst = cst_adapter or MockCSTAdapter()
    analysis = analysis_adapter or MockDataAnalysisAdapter()
    source = ArtifactRef(
        artifact_id="mock-input-structure-v1",
        uri="mock://input/structure",
        source_system="MockFixture",
        mock=True,
    )
    cst_request = CSTTaskRequest(
        task_id="mock-computation-001",
        operation="mock.computation-operation",
        task_config={"kind": "interface-only"},
        input_artifacts=(source,),
        parameters={"mode": "mock"},
        metadata={"contract_version": "0.1.0"},
    )
    cst_result = cst.execute(cst_request)
    if cst_result.status not in {TaskStatus.SUCCEEDED, TaskStatus.WARNING} or not cst_result.output_artifacts:
        raise ContractError("mock CST stage did not produce an artifact reference")
    analysis_request = AnalysisRequest(
        task_id="mock-analysis-001",
        operation="mock.analysis-registration",
        input_artifacts=cst_result.output_artifacts,
        analysis_task={"kind": "record-and-link-only", "source_task_id": cst_result.task_id},
        parameters={"mode": "mock"},
        structure_metadata={"source_artifact_id": source.artifact_id},
        metadata={"upstream_task_id": cst_result.task_id},
    )
    analysis_result = analysis.analyze(analysis_request)
    if analysis_result.status not in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}:
        raise ContractError("mock Data_analysis stage failed")
    return MockIntegrationResult(cst_result, analysis_result)
