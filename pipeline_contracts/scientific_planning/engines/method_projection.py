"""Strict projection from MethodPlan provenance records to CalculationPlan v1.0."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ...calculation_plan import CalculationPlan, REQUIRED_METHOD


_DIRECT_MAP = {
    "xc": "xc_functional",
    "basis_set": "basis_set",
    "pseudopotential": "pseudopotential",
    "cutoff_ry": "cutoff_ry",
    "rel_cutoff_ry": "rel_cutoff_ry",
    "charge": "charge",
    "multiplicity": "multiplicity",
    "kind_definitions": "kind_definitions",
    "basis_file_name": "basis_file_name",
    "potential_file_name": "potential_file_name",
    "poisson_solver": "poisson_solver",
    "poisson_periodicity": "poisson_periodicity",
    "uks": "uks",
    "center_coordinates": "center_coordinates",
}


def _usable_record(fields: Mapping[str, Any], name: str) -> tuple[bool, Any, dict[str, Any]]:
    raw = fields.get(name)
    if not isinstance(raw, Mapping):
        return False, None, {}
    record = dict(raw)
    if record.get("status") == "NOT_APPLICABLE":
        if record.get("value") is None and record.get("source_ref") and str(record.get("rationale") or "").strip():
            return True, None, record
        return False, None, record
    if record.get("status") in {"MISSING", "PROPOSED", "CONFLICT", "INVALID_NOT_APPLICABLE"}:
        return False, None, record
    if record.get("value") is None or not record.get("source_ref") or not record.get("provenance"):
        return False, None, record
    return True, deepcopy(record.get("value")), record


def _required_value(fields: Mapping[str, Any], name: str, blockers: list[str],
                    provenance: dict[str, Any]) -> Any:
    valid, value, record = _usable_record(fields, name)
    if not valid:
        blockers.append(f"{name}: field is missing, unresolved, or has no source_ref/provenance.")
        return None
    if record.get("status") == "NOT_APPLICABLE":
        blockers.append(f"{name}: NOT_APPLICABLE cannot satisfy CalculationPlan.REQUIRED_METHOD.")
        return None
    provenance[name] = {
        "source_field": name, "source_ref": record.get("source_ref"),
        "provenance": record.get("provenance"), "status": record.get("status"),
        "rationale": record.get("rationale"),
    }
    return deepcopy(value)


def to_cp2k_calculation_plan_method(method_plan: Mapping[str, Any]) -> dict[str, Any]:
    """Project a resolved MethodPlan to REQUIRED_METHOD and validate its real envelope.

    method_plan must include calculation_plan_context, containing all CalculationPlan
    v1.0 envelope fields except method. No synthetic context or scientific defaults
    are inserted by this adapter.
    """
    if not isinstance(method_plan, Mapping):
        raise TypeError("method_plan must be a Mapping")
    execution_mode = str(method_plan.get("execution_mode", "real")).strip().casefold() or "real"
    if execution_mode not in {"mock", "real"}:
        return {
            "status": "BLOCKED", "method": None, "calculation_plan": None,
            "execution_mode": execution_mode, "planning_scope": "BLOCKED",
            "mock_only": False, "real_execution_preflight_allowed": False,
            "field_provenance": {}, "preserved_fields": {},
            "blockers": ["execution_mode must be 'mock' or 'real'."],
            "validation": {"status": "NOT_RUN", "issues": []},
        }
    if str(method_plan.get("engine", "")).casefold() != "cp2k":
        return {
            "status": "BLOCKED", "method": None, "calculation_plan": None,
            "execution_mode": execution_mode, "planning_scope": "BLOCKED",
            "mock_only": execution_mode == "mock", "real_execution_preflight_allowed": False,
            "field_provenance": {}, "preserved_fields": {},
            "blockers": ["Projection supports CP2K MethodPlan only."],
            "validation": {"status": "NOT_RUN", "issues": []},
        }

    blockers: list[str] = []
    fields = method_plan.get("fields")
    if not isinstance(fields, Mapping):
        fields = {}
        blockers.append("MethodPlan.fields mapping is missing.")
    if method_plan.get("status") != "METHOD_FIELDS_RESOLVED" or method_plan.get("ready_for_core_compilation") is not True:
        blockers.append(
            "MethodPlan is not METHOD_FIELDS_RESOLVED/ready_for_core_compilation; "
            f"current status is {method_plan.get('status')!r}."
        )
    for item in method_plan.get("blockers", []) or []:
        blockers.append(f"MethodPlan blocker: {item}")
    if execution_mode == "real":
        if method_plan.get("runtime_version_verified") is not True:
            blockers.append("Real projection requires runtime_version_verified=True.")
        if method_plan.get("runtime_version_matches") is not True:
            blockers.append("Real projection requires runtime_verified_version to match software_version exactly.")

    projected: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for target, source in _DIRECT_MAP.items():
        projected[target] = _required_value(fields, source, blockers, provenance)

    # Cell periodicity and Poisson periodicity are distinct CP2K settings.
    # periodicity is an accepted alias only for cell_periodicity.
    has_cell, cell_value, cell_record = _usable_record(fields, "cell_periodicity")
    has_period, period_value, period_record = _usable_record(fields, "periodicity")
    if has_cell and has_period and cell_record.get("status") != "NOT_APPLICABLE" and period_record.get("status") != "NOT_APPLICABLE":
        if cell_value != period_value:
            blockers.append("cell_periodicity conflicts with periodicity; projection will not choose one.")
            projected["cell_periodicity"] = None
        else:
            projected["cell_periodicity"] = deepcopy(cell_value)
            provenance["cell_periodicity"] = {
                "source_field": "cell_periodicity+periodicity",
                "source_refs": [cell_record.get("source_ref"), period_record.get("source_ref")],
                "provenance": "consistent_explicit_sources",
            }
    elif has_cell:
        if cell_record.get("status") == "NOT_APPLICABLE":
            blockers.append("cell_periodicity: NOT_APPLICABLE cannot satisfy CalculationPlan.REQUIRED_METHOD.")
            projected["cell_periodicity"] = None
        else:
            projected["cell_periodicity"] = deepcopy(cell_value)
            provenance["cell_periodicity"] = {
                "source_field": "cell_periodicity", "source_ref": cell_record.get("source_ref"),
                "provenance": cell_record.get("provenance"), "status": cell_record.get("status"),
                "rationale": cell_record.get("rationale"),
            }
    elif has_period:
        if period_record.get("status") == "NOT_APPLICABLE":
            blockers.append("periodicity: NOT_APPLICABLE cannot satisfy CalculationPlan.method.cell_periodicity.")
            projected["cell_periodicity"] = None
        else:
            projected["cell_periodicity"] = deepcopy(period_value)
            provenance["cell_periodicity"] = {
                "source_field": "periodicity", "source_ref": period_record.get("source_ref"),
                "provenance": period_record.get("provenance"), "status": period_record.get("status"),
                "rationale": "Mapped to CalculationPlan.method.cell_periodicity; Poisson periodicity is mapped independently.",
            }
    else:
        blockers.append("cell_periodicity/periodicity: no sourced value for CalculationPlan.method.cell_periodicity.")
        projected["cell_periodicity"] = None

    scf: dict[str, Any] = {}
    scf_provenance: dict[str, Any] = {}
    for key in ("method", "eps_scf", "max_scf"):
        source_name = f"scf.{key}"
        scf[key] = _required_value(fields, source_name, blockers, scf_provenance)
    projected["scf"] = scf
    provenance["scf"] = scf_provenance

    consumed = set(_DIRECT_MAP.values()) | {
        "cell_periodicity", "periodicity", "scf.method", "scf.eps_scf", "scf.max_scf"
    }
    preserved = {key: deepcopy(value) for key, value in fields.items() if key not in consumed}

    missing_targets = sorted(set(REQUIRED_METHOD) - set(projected))
    extra_targets = sorted(set(projected) - set(REQUIRED_METHOD))
    if missing_targets:
        blockers.append("Projection omitted CalculationPlan.REQUIRED_METHOD keys: " + ", ".join(missing_targets))
    if extra_targets:
        blockers.append("Projection contains keys outside CalculationPlan.REQUIRED_METHOD: " + ", ".join(extra_targets))

    context = method_plan.get("calculation_plan_context")
    validation_issues: list[str] = []
    validation_status = "NOT_RUN"
    calculation_plan_data = None
    if not isinstance(context, Mapping):
        blockers.append("calculation_plan_context is required to validate the projected method in its actual CalculationPlan v1.0 envelope.")
    else:
        version_record = fields.get("software_version")
        if not isinstance(version_record, Mapping):
            blockers.append("MethodPlan.fields.software_version source evidence is required.")
        else:
            version_value = version_record.get("value")
            version_ref = version_record.get("source_ref")
            version_provenance = version_record.get("provenance")
            if (
                version_record.get("status") not in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE"}
                or version_value is None or not str(version_value).strip()
                or not version_ref or not str(version_ref).strip()
                or not version_provenance or not str(version_provenance).strip()
            ):
                blockers.append("software_version must retain a concrete value, source_ref and provenance.")
            elif str(version_value).strip() != str(method_plan.get("software_version", "")).strip():
                blockers.append("Projected software_version must match the request declaration.")
            else:
                plan_data = deepcopy(dict(context))
                for stage in plan_data.get("calculations", []):
                    if isinstance(stage, Mapping) and stage.get("operation") in {"cp2k.geo_opt", "cp2k.energy"}:
                        if str(stage.get("tool_version", "")).strip() != str(version_value).strip():
                            blockers.append(
                                f"CalculationPlan stage {stage.get('id')!r} tool_version must exactly match "
                                "the source-backed MethodPlan software_version."
                            )
                if execution_mode == "mock":
                    metadata = plan_data.get("metadata")
                    if not isinstance(metadata, Mapping):
                        blockers.append("Mock-only CalculationPlan requires a metadata mapping.")
                    else:
                        metadata = deepcopy(dict(metadata))
                        metadata.update({
                            "execution_mode": "mock",
                            "planning_scope": "MOCK_ONLY",
                            "mock_only": True,
                            "real_execution_preflight_allowed": False,
                            "runtime_verification_required_before_real_preflight": True,
                            "software_version_evidence": {
                                "value": deepcopy(version_value),
                                "provenance": version_provenance,
                                "source_ref": version_ref,
                                "rationale": version_record.get("rationale"),
                                "status": version_record.get("status"),
                                "approval_required": version_record.get("approval_required"),
                            },
                        })
                        plan_data["metadata"] = metadata
                if not blockers:
                    plan_data["method"] = deepcopy(projected)
                    try:
                        plan = CalculationPlan.from_mapping(plan_data)
                        validation_issues = plan.validate()
                        validation_status = "PASS" if not validation_issues else "FAIL"
                        if validation_issues:
                            blockers.extend(f"CalculationPlan.validate(): {issue}" for issue in validation_issues)
                        else:
                            calculation_plan_data = plan.as_dict()
                    except Exception as exc:
                        validation_status = "FAIL"
                        validation_issues = [f"{type(exc).__name__}: {exc}"]
                        blockers.extend(f"CalculationPlan.validate(): {issue}" for issue in validation_issues)

    ready = not blockers and validation_status == "PASS"
    return {
        "status": "READY" if ready else "BLOCKED",
        "method": deepcopy(projected) if ready else None,
        "calculation_plan": calculation_plan_data if ready else None,
        "execution_mode": execution_mode,
        "planning_scope": "MOCK_ONLY" if execution_mode == "mock" else "REAL_CANDIDATE",
        "mock_only": execution_mode == "mock",
        "real_execution_preflight_allowed": False if execution_mode == "mock" else None,
        "field_provenance": provenance,
        "preserved_fields": preserved,
        "blockers": blockers,
        "validation": {
            "status": validation_status, "issues": validation_issues,
            "validator": "pipeline_contracts.calculation_plan.CalculationPlan.validate",
        },
    }


__all__ = ["to_cp2k_calculation_plan_method"]
