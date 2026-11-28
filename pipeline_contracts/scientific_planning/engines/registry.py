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
    if not engine or not task:
        return {"engine": engine or None, "task_type": task or None, "software_supported": False,
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
    version = request.get("software_version")
    version_verified = request.get("runtime_version_verified") is True
    blockers = []
    if status != "AVAILABLE":
        blockers.append("This route is not covered by an AVAILABLE Pipeline execution adapter.")
    if not allows_real:
        blockers.append("Real execution-plan generation is disabled for this capability combination.")
    if not version:
        blockers.append("Exact software_version is missing; runtime version preflight is required.")
    elif not version_verified:
        blockers.append("Software version has not been verified against the actual local executable.")
    return {
        "engine": engine, "task_type": task, "software_supported": all(x.get("software_supported") is True for x in selected),
        "integration_status": status, "allows_real_execution_plan": allows_real,
        "can_enter_real_preflight": allows_real and status == "AVAILABLE" and bool(version) and version_verified,
        "capability_ids": [x["capability_id"] for x in selected],
        "requested_features": sorted(features),
        "documented_versions": sorted({str(v) for x in selected for v in x.get("version", {}).get("documented_versions", [])}),
        "software_version_declared": bool(version), "runtime_version_verified": version_verified,
        "requires_runtime_preflight": True,
        "pipeline_adapter": [x.get("pipeline_adapter") for x in selected],
        "parser_qc_plugins": sorted({v for x in selected for v in x.get("parser_qc_plugins", [])}),
        "blockers": blockers, "limitations": [v for x in selected for v in x.get("limitations", [])]
    }


__all__ = ["load_registry", "list_capabilities", "find_capabilities", "route_capability"]
