"""Pipeline-side Skill adapter contracts and synthetic mock implementations."""
from .adapters import CSTAdapter, DataAnalysisAdapter, HpcAdapter
from .integration import MockIntegrationResult, run_mock_integration
from .mocks import MockCSTAdapter, MockDataAnalysisAdapter, MockHpcAdapter
from .real_adapters import RealCSTAdapter, RealDataAnalysisAdapter, load_data_analysis_api
from .runner import (
    CSTValidationSpec, PipelineRunner, PipelineStageResult,
    PipelineTaskManifest, PipelineTaskResult,
)
from .models import *  # re-export the small public contract surface

__all__ = [
    "CSTAdapter", "DataAnalysisAdapter", "HpcAdapter",
    "MockIntegrationResult", "run_mock_integration",
    "MockCSTAdapter", "MockDataAnalysisAdapter", "MockHpcAdapter",
    "RealCSTAdapter", "RealDataAnalysisAdapter", "load_data_analysis_api",
    "CSTValidationSpec", "PipelineRunner", "PipelineStageResult",
    "PipelineTaskManifest", "PipelineTaskResult",
]
