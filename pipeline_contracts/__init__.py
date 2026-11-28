"""Pipeline contracts, adapters and calculation-plan workflow controller."""
from .adapters import CSTAdapter, DataAnalysisAdapter, HpcAdapter
from .integration import MockIntegrationResult, run_mock_integration
from .mocks import MockCSTAdapter, MockDataAnalysisAdapter, MockHpcAdapter
from .real_adapters import RealCSTAdapter, RealDataAnalysisAdapter, load_data_analysis_api
from .runner import CSTValidationSpec, PipelineRunner, PipelineStageResult, PipelineTaskManifest, PipelineTaskResult
from .calculation_plan import CalculationPlan, PlanValidationError, compile_initial_tasks, compile_energy_task
from .workflow import ExecutionResult, MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore

__all__ = [
    "CSTAdapter", "DataAnalysisAdapter", "HpcAdapter", "MockIntegrationResult", "run_mock_integration",
    "MockCSTAdapter", "MockDataAnalysisAdapter", "MockHpcAdapter", "RealCSTAdapter",
    "RealDataAnalysisAdapter", "load_data_analysis_api", "CSTValidationSpec", "PipelineRunner",
    "PipelineStageResult", "PipelineTaskManifest", "PipelineTaskResult", "CalculationPlan",
    "PlanValidationError", "compile_initial_tasks", "compile_energy_task", "ExecutionResult",
    "MockCP2KWorkflowAdapter", "WorkflowController", "WorkflowStore",
]

from .calculation_plan import CalculationPlan, PlanValidationError, compile_initial_tasks, compile_energy_task
from .workflow import ExecutionResult, MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore

__all__ += ["CalculationPlan", "PlanValidationError", "compile_initial_tasks", "compile_energy_task",
            "ExecutionResult", "MockCP2KWorkflowAdapter", "WorkflowController", "WorkflowStore"]

from .project_lifecycle import ProjectLifecycle
from .plan_compiler import CompilationResult, compile_confirmed_manifest, compile_docx, write_manifest

__all__ += ["ProjectLifecycle", "CompilationResult", "compile_confirmed_manifest",
            "compile_docx", "write_manifest"]
