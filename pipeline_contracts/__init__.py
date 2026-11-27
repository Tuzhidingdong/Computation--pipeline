"""Pipeline-side Skill adapter contracts and synthetic mock implementations."""
from .adapters import CSTAdapter, DataAnalysisAdapter, HpcAdapter
from .integration import MockIntegrationResult, run_mock_integration
from .mocks import MockCSTAdapter, MockDataAnalysisAdapter, MockHpcAdapter
from .models import *  # re-export the small public contract surface

__all__ = [
    "CSTAdapter", "DataAnalysisAdapter", "HpcAdapter",
    "MockIntegrationResult", "run_mock_integration",
    "MockCSTAdapter", "MockDataAnalysisAdapter", "MockHpcAdapter",
]
