"""Capability routing against documented software and Pipeline adapters."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_REGISTRY_PATH = Path(__file__).with_name("capability_registry.json")


def load_registry() -> dict[str, Any]:
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


def list_capabilities(engine: str | None = None) -> list[dict[str, Any]]:
    items = load_registry().get("capabilities", [])
    if engine is None:
        return items
    token = str(engine).strip().casefold()
    return [item for item in items if str(item.get("engine", "")).casefold() == token]


def find_capabilities(engine: str, task_type: str) -> list[dict[str, Any]]:
    engine_token, task_token = str(engine).strip().casefold(), str(task_type).strip().casefold()
    return [
        item for item in load_registry().get("capabilities", [])
        if str(item.get("engine", "")).casefold() == engine_token
        and item.get("capability_role", "task") != "method_feature"
        and task_token in {str(x).casefold() for x in item.get("supported_task_types", [])}
    ]


def _has_sccs(value: Any) -> bool:
    if isinstance(value, Mapping):
        model = str(value.get("model", "")).casefold()
        return model in {"sccs", "cp2k_sccs"}
    return str(value or "").casefold() in {"sccs", "cp2k_sccs"}


def requested_features(request: Mapping[str, Any]) -> set[str]:
    explicit = request.get("features", [])
    result = {str(x).strip().casefold() for x in explicit} if isinstance(explicit, (list, tuple, set)) else set()
    method = request.get("method", {})
    if isinstance(method, Mapping) and _has_sccs(method.get("solvation", {}).get("implicit") if isinstance(method.get("solvation"), Mapping) else None):
        result.add("sccs")
    # Method values may originate in frozen-source/profile Mapping records.
    sources = request.get("sources", [])
    if isinstance(sources, (list, tuple)):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            fields = source.get("fields", {})
            solvation = fields.get("solvation", {}) if isinstance(fields, Mapping) else {}
            if isinstance(solvation, Mapping) and _has_sccs(solvation.get("implicit")):
                result.add("sccs")
    return result


def route_capability(request: Mapping[str, Any]) -> dict[str, Any]:
    engine, task = str(request.get("engine", "")).strip(), str(request.get("task_type", "")).strip()
    execution_mode = str(request.get("execution_mode", "real")).strip().casefold() or "real"
    if not engine or not task:
        return {"engine": engine or None, "task_type": task or None,
                "execution_mode": execution_mode, "software_supported": False,
                "integration_status": "UNVERIFIED", "allows_real_execution_plan": False,
                "can_enter_real_preflight": False, "capability_ids": [],
                "blockers": ["engine and task_type are required for capability routing"]}

    matches = find_capabilities(engine, task)
    if not matches:
        return {"engine": engine, "task_type": task, "software_supported": False,
                "integration_status": "NOT_INTEGRATED", "allows_real_execution_plan": False,
                "can_enter_real_preflight": False, "capability_ids": [],
                "blockers": [f"No registered capability for {engine}:{task}"]}

    selected = list(matches)
    features = requested_features(request)
    for feature in features:
        feature_matches = [
            item for item in list_capabilities(engine)
            if item.get("capability_role") == "method_feature"
            and feature in {str(x).casefold() for x in item.get("supported_features", [])}
        ]
        if not feature_matches:
            return {"engine": engine, "task_type": task, "software_supported": False,
                    "integration_status": "UNVERIFIED", "allows_real_execution_plan": False,
                    "can_enter_real_preflight": False, "capability_ids": [x["capability_id"] for x in selected],
                    "requested_features": sorted(features),
                    "blockers": [f"Requested feature {feature!r} has no registered capability entry"]}
        selected.extend(feature_matches)

    rank = {"AVAILABLE": 0, "PLANNABLE_ONLY": 1, "NOT_INTEGRATED": 2, "UNVERIFIED": 3}
    statuses = [str(x.get("integration_status", "UNVERIFIED")) for x in selected]
    status = max(statuses, key=lambda x: rank.get(x, 3))
    allows_real = all(x.get("allows_real_execution_plan") is True for x in selected)
    version_raw = request.get("software_version")
    version = str(version_raw).strip() if version_raw is not None else ""
    version_verified = request.get("runtime_version_verified") is True
    runtime_verified_raw = request.get("runtime_verified_version")
    runtime_verified_version = str(runtime_verified_raw).strip() if runtime_verified_raw is not None else ""
    version_matches = bool(version and runtime_verified_version and runtime_verified_version == version)
    blockers = []
    if status != "AVAILABLE":
        blockers.append("This route is not covered by an AVAILABLE Pipeline execution adapter.")
    if not allows_real:
        blockers.append("Real execution-plan generation is disabled for this capability combination.")
    if execution_mode == "real":
        if not version:
            blockers.append("Exact software_version is missing; runtime version preflight is required.")
        if not version_verified:
            blockers.append("Software version has not been verified against the actual local executable.")
        if not version_matches:
            blockers.append("runtime_verified_version must exactly match the requested software_version.")
    elif execution_mode == "mock":
        blockers.append("Mock-only planning cannot enter Real execution preflight.")
    else:
        blockers.append("execution_mode must be 'mock' or 'real'.")
    return {
        "engine": engine, "task_type": task, "execution_mode": execution_mode,
        "software_supported": all(x.get("software_supported") is True for x in selected),
        "integration_status": status, "allows_real_execution_plan": allows_real,
        "can_enter_real_preflight": (
            execution_mode == "real" and allows_real and status == "AVAILABLE"
            and bool(version) and version_verified and version_matches
        ),
        "capability_ids": [x["capability_id"] for x in selected],
        "requested_features": sorted(features),
        "documented_versions": sorted({str(v) for x in selected for v in x.get("version", {}).get("documented_versions", [])}),
        "software_version_declared": bool(version),
        "runtime_version_verified": version_verified,
        "runtime_verified_version": runtime_verified_version or None,
        "runtime_version_matches": version_matches,
        "requires_runtime_preflight": True,
        "pipeline_adapter": [x.get("pipeline_adapter") for x in selected],
        "parser_qc_plugins": sorted({v for x in selected for v in x.get("parser_qc_plugins", [])}),
        "blockers": blockers, "limitations": [v for x in selected for v in x.get("limitations", [])]
    }


__all__ = ["load_registry", "list_capabilities", "find_capabilities", "route_capability"]
