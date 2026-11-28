"""Fail-closed resource planning; no synthetic cluster sizing or walltime defaults."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

_RESOURCE_FIELDS = (
    "nodes", "mpi_ranks", "openmp_threads", "gpu_count",
    "memory_gb", "walltime_seconds", "scratch_gb",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def plan_resources(request: Mapping[str, Any]) -> dict[str, Any]:
    """Accept an engine/task-specific verified profile; expose benchmarks as references only.

    Benchmark matching is exact across engine, task, software version, atom count,
    method fingerprint and hardware fingerprint. No scaling/extrapolation is performed.
    A benchmark cannot substitute for a local scheduler allocation profile.
    """
    if not isinstance(request, Mapping):
        raise TypeError("request must be a Mapping")
    structure = _mapping(request.get("structure"))
    engine, task = str(request.get("engine", "")).strip(), str(request.get("task_type", "")).strip()
    atom_count, system_type = structure.get("atom_count"), structure.get("system_type")
    execution_mode = str(request.get("execution_mode", "real")).strip().casefold() or "real"
    if execution_mode == "mock":
        allocation = {
            key: {
                "value": None, "provenance": "mock_only_not_estimated", "source_ref": None,
                "uncertainty": "NOT_ESTIMATED_FOR_MOCK", "status": "NOT_APPLICABLE",
            }
            for key in _RESOURCE_FIELDS
        }
        normalized_atom_count = (
            atom_count if isinstance(atom_count, int) and not isinstance(atom_count, bool) and atom_count > 0
            else None
        )
        return {
            "engine": engine or None, "task_type": task or None,
            "execution_mode": "mock", "planning_scope": "MOCK_ONLY", "mock_only": True,
            "structure": {"atom_count": normalized_atom_count, "system_type": system_type},
            "status": "MOCK_ONLY", "allocation": allocation,
            "verified_profile": False, "profile_id": None, "profile_source_ref": None,
            "historical_benchmark_reference": None, "quantitative_reference_available": False,
            "quantitative_estimate_available": False, "quantitative_estimate": None,
            "resource_estimate_policy": (
                "Mock-only planning does not estimate or allocate nodes, MPI ranks, OpenMP threads, "
                "GPUs, memory, walltime or scratch. Real execution requires a separate owner-verified "
                "engine/task-specific resource profile."
            ),
            "real_execution_preflight_allowed": False, "missing_profile_fields": [],
            "blockers": [], "notes": ["No resource values are inferred or copied from profiles/benchmarks in Mock mode."],
        }
    if execution_mode != "real":
        return {
            "engine": engine or None, "task_type": task or None,
            "execution_mode": execution_mode, "planning_scope": "BLOCKED",
            "status": "BLOCKED_INVALID_EXECUTION_MODE", "allocation": {},
            "verified_profile": False, "quantitative_estimate_available": False,
            "quantitative_estimate": None, "real_execution_preflight_allowed": False,
            "missing_profile_fields": list(_RESOURCE_FIELDS),
            "blockers": ["execution_mode must be 'mock' or 'real'."],
        }
    blockers: list[str] = []
    if not isinstance(atom_count, int) or isinstance(atom_count, bool) or atom_count <= 0:
        blockers.append("A positive integer structure.atom_count is required.")
        atom_count = None
    if not system_type:
        blockers.append("structure.system_type is required.")
    if not engine or not task:
        blockers.append("engine and task_type are required.")

    profile = _mapping(request.get("resource_profile"))
    if not profile:
        profile = _mapping(_mapping(request.get("execution")).get("resource_profile"))
    verified = (
        profile.get("verified") is True and bool(profile.get("source_ref"))
        and str(profile.get("engine", "")).casefold() == engine.casefold()
        and str(profile.get("task_type", "")).casefold() == task.casefold()
    )
    supplied = _mapping(profile.get("allocation"))
    allocation: dict[str, Any] = {}
    missing: list[str] = []
    for key in _RESOURCE_FIELDS:
        value = supplied.get(key) if verified else None
        if value is None:
            missing.append(key)
            allocation[key] = {"value": None, "provenance": "missing", "source_ref": None,
                               "uncertainty": "UNKNOWN", "status": "MISSING"}
        else:
            allocation[key] = {"value": deepcopy(value), "provenance": "verified_resource_profile",
                               "source_ref": profile.get("source_ref"),
                               "uncertainty": str(profile.get("uncertainty", "ALLOCATION_NOT_A_PERFORMANCE_GUARANTEE")),
                               "status": "PROFILE_PROVIDED"}

    benchmark_match = None
    benchmarks = request.get("benchmarks", [])
    if isinstance(benchmarks, (list, tuple)):
        for item in benchmarks:
            if not isinstance(item, Mapping) or item.get("verified") is not True:
                continue
            exact = (
                str(item.get("engine", "")).casefold() == engine.casefold()
                and str(item.get("task_type", "")).casefold() == task.casefold()
                and str(item.get("software_version", "")) == str(request.get("software_version", ""))
                and item.get("atom_count") == atom_count
                and item.get("method_fingerprint") == request.get("method_fingerprint")
                and item.get("hardware_fingerprint") == request.get("hardware_fingerprint")
                and bool(item.get("source_ref"))
            )
            if exact:
                benchmark_match = item
                break

    benchmark_reference = None
    if benchmark_match is not None:
        observed = _mapping(benchmark_match.get("observed_resources"))
        benchmark_reference = {
            "source_ref": benchmark_match.get("source_ref"),
            "observed_resources": {key: deepcopy(observed[key]) for key in _RESOURCE_FIELDS if key in observed},
            "interpretation": "Exact-match historical observation only; not extrapolated and not a scheduler allocation.",
            "uncertainty": benchmark_match.get("uncertainty", "NOT_REPORTED"),
        }

    if not verified:
        blockers.append("No verified engine/task-specific resource_profile is supplied; real execution preflight must remain blocked.")
    elif missing:
        blockers.append("Verified resource profile is incomplete: " + ", ".join(missing))
    if atom_count is None or not system_type:
        blockers.append("Structure size/type is incomplete; resource context cannot be evaluated.")

    ready = verified and not missing and not blockers
    return {
        "engine": engine or None, "task_type": task or None,
        "execution_mode": "real", "planning_scope": "REAL_PREFLIGHT_CANDIDATE",
        "structure": {"atom_count": atom_count, "system_type": system_type},
        "status": "READY_FOR_REAL_PREFLIGHT" if ready else "BLOCKED_MISSING_RESOURCE_PROFILE",
        "allocation": allocation, "verified_profile": bool(verified),
        "profile_id": profile.get("profile_id") if verified else None,
        "profile_source_ref": profile.get("source_ref") if verified else None,
        "historical_benchmark_reference": benchmark_reference,
        "quantitative_reference_available": bool(verified or benchmark_match),
        "quantitative_estimate_available": False, "quantitative_estimate": None,
        "resource_estimate_policy": "Profile values are supplied allocations, not performance predictions. Benchmark values are exact-match observations only. No nodes/MPI/OpenMP/GPU/memory/walltime/scratch estimate is synthesized.",
        "real_execution_preflight_allowed": bool(ready),
        "missing_profile_fields": missing if verified else list(_RESOURCE_FIELDS),
        "blockers": blockers,
    }


__all__ = ["plan_resources"]
