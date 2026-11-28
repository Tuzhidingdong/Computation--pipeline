"""Capability, method, resource and QC planning plugins for Planning Core.

The boundary is Mapping-in/Mapping-out. This package does not own a Plan schema,
instantiate CalculationPlan, launch software, or communicate with an HPC scheduler.
"""
from __future__ import annotations

from typing import Any, Mapping

from .method_planner import plan_method
from .qc_planner import evaluate_qc, get_qc_contract
from .registry import find_capabilities, list_capabilities, load_registry, route_capability
from .resource_planner import plan_resources


def build_engine_planning(request: Mapping[str, Any]) -> dict[str, Any]:
    """Compose the independent planners without creating or mutating a CalculationPlan."""
    if not isinstance(request, Mapping):
        raise TypeError("request must be a Mapping")
    task_type = str(request.get("task_type", ""))
    return {
        "capability_route": route_capability(request),
        "method_plan": plan_method(request),
        "resource_plan": plan_resources(request),
        "qc_contract": get_qc_contract(task_type),
        "interface": "Mapping-in/Mapping-out; Planning Core schema adaptation is owned by Agent B",
        "creates_calculation_plan": False,
        "submits_or_executes_calculation": False,
    }


__all__ = [
    "build_engine_planning", "plan_method", "plan_resources", "get_qc_contract",
    "evaluate_qc", "load_registry", "list_capabilities", "find_capabilities",
    "route_capability",
]
