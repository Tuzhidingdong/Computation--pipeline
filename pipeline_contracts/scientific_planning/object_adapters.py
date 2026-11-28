"""Schema adapters for Agent A planning results and existing project adapters."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _ref_map(refs: list[dict]) -> dict[str, dict]:
    return {str(item.get("evidence_id")): item for item in refs if item.get("evidence_id")}


def parameter_decision(name: str, record: Mapping[str, Any] | None,
                       refs: list[dict], *, value_override: Any = ...) -> dict:
    raw = dict(record or {})
    status = str(raw.get("status") or "MISSING").upper()
    normalized = {
        "SOURCE_CONFIRMED": "EVIDENCED",
        "APPROVED_POLICY": "POLICY_SELECTED",
        "VERSION_VERIFIED_RULE": "POLICY_SELECTED",
        "EVIDENCED": "EVIDENCED",
        "POLICY_SELECTED": "POLICY_SELECTED",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
        "MISSING": "MISSING",
        "PROPOSED": "NEEDS_APPROVAL",
        "CONFLICT": "NEEDS_APPROVAL",
        "DECLARED_UNVERIFIED": "NEEDS_APPROVAL",
        "UNRESOLVED": "NEEDS_APPROVAL",
        "BLOCKED": "MISSING",
    }.get(status, "NEEDS_APPROVAL")
    value = raw.get("value") if value_override is ... else value_override
    refs_by_id = _ref_map(refs)
    # Agent A uses these two stable internal source tokens for explicit
    # non-applicability decisions; bind them to the exact registry/artifact evidence.
    registry_ref = next((item for item in refs if item.get("source_type") == "software_registry"), None)
    artifact_ref = next((item for item in refs if item.get("source_type") == "artifact"), None)
    if registry_ref:
        refs_by_id.setdefault("registry:cp2k", registry_ref)
    if artifact_ref:
        refs_by_id.setdefault("request.structure.periodicity", artifact_ref)
    source_ref = raw.get("source_ref")
    raw_source_refs = raw.get("source_refs")
    if isinstance(raw_source_refs, (list, tuple)):
        evidence = [refs_by_id[str(item)] for item in raw_source_refs if str(item) in refs_by_id]
    elif source_ref is not None:
        source_tokens = [item.strip() for item in str(source_ref).split(",") if item.strip()]
        evidence = [refs_by_id[item] for item in source_tokens if item in refs_by_id]
    else:
        evidence = []
    scope = str(raw.get("applicability") or "UNSPECIFIED")
    decision = {
        "status": normalized, "value": deepcopy(value), "unit": raw.get("unit"),
        "source_evidence_refs": deepcopy(evidence), "applicable_scope": scope,
        "policy_ref": None, "decision_id": "parameter-" + name.replace(".", "-"),
        "uncertainty": str(raw.get("uncertainty") or "UNKNOWN"),
        "rationale": str(raw.get("rationale") or "No explicit source-backed decision was supplied."),
        "provenance": raw.get("provenance"), "source_ref": source_ref,
        "applicability": scope, "approval_required": bool(raw.get("approval_required", normalized == "NEEDS_APPROVAL")),
        "source_status": status,
    }
    return decision


def method_plan_object(*, method_raw: Mapping[str, Any], route: Mapping[str, Any],
                       engine_request: Mapping[str, Any], method_source_refs: list[dict],
                       all_refs: list[dict], structure_mapping: Mapping[str, Any] | None,
                       artifact_ref: Mapping[str, Any] | None, overall_status: str,
                       method_gaps: list[dict], selection_records: list[dict]) -> dict:
    fields = method_raw.get("fields") if isinstance(method_raw.get("fields"), Mapping) else {}
    def flattened_records(prefix: str, value: Any) -> dict[str, dict]:
        result: dict[str, dict] = {}
        if not isinstance(value, Mapping):
            return result
        if "value" in value:
            result[prefix] = deepcopy(dict(value))
            return result
        for child_name, child in value.items():
            name = f"{prefix}.{child_name}" if prefix else str(child_name)
            result.update(flattened_records(name, child))
        return result

    def record(*names: str) -> dict:
        for name in names:
            cursor: Any = fields.get(name)
            if not isinstance(cursor, Mapping):
                cursor = fields
                for part in name.split("."):
                    if not isinstance(cursor, Mapping) or part not in cursor:
                        cursor = None
                        break
                    cursor = cursor[part]
            if isinstance(cursor, Mapping):
                return dict(cursor)
        return {"value": None, "provenance": "missing", "source_ref": None,
                "rationale": "No source supplied this required method parameter.",
                "applicability": "APPLICABLE", "uncertainty": "UNKNOWN",
                "approval_required": True, "status": "MISSING"}
    def combined(name: str, source_names: list[str]) -> dict:
        rs = [record(key) for key in source_names]
        if any(x.get("status") not in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE", "NOT_APPLICABLE"} for x in rs):
            return {"value": None, "provenance": "combined_unresolved", "source_ref": None,
                    "rationale": "All constituent fields must be explicitly resolved.",
                    "applicability": "APPLICABLE", "uncertainty": "UNKNOWN",
                    "approval_required": True, "status": "MISSING"}
        values = {key: deepcopy(record(key).get("value")) for key in source_names}
        refs = sorted({str(x.get("source_ref")) for x in rs if x.get("source_ref")})
        return {"value": values, "provenance": "combined_source_records",
                "source_ref": refs[0] if len(refs) == 1 else None, "source_refs": refs,
                "rationale": "Combined only the explicitly source-backed constituent values.",
                "applicability": "APPLICABLE",
                "uncertainty": "; ".join(sorted({str(x.get("uncertainty") or "UNKNOWN") for x in rs})),
                "approval_required": any(bool(x.get("approval_required")) for x in rs),
                "status": "SOURCE_CONFIRMED" if all(x.get("status") == "SOURCE_CONFIRMED" for x in rs) else "APPROVED_POLICY"}
    params = {
        "xc_functional": parameter_decision("xc_functional", record("xc_functional"), all_refs),
        "dispersion": parameter_decision("dispersion", record("dispersion"), all_refs),
        "basis_set": parameter_decision("basis_set", record("basis_set"), all_refs),
        "pseudopotential": parameter_decision("pseudopotential", record("pseudopotential"), all_refs),
        "cutoff": parameter_decision("cutoff", record("cutoff_ry"), all_refs),
        "relative_cutoff": parameter_decision("relative_cutoff", record("rel_cutoff_ry"), all_refs),
        "scf_strategy": parameter_decision("scf_strategy", record("scf.method"), all_refs),
        "scf_convergence": parameter_decision("scf_convergence", combined("scf_convergence", ["scf.eps_scf", "scf.max_scf"]), all_refs),
        "charge": parameter_decision("charge", record("charge"), all_refs),
        "multiplicity": parameter_decision("multiplicity", record("multiplicity"), all_refs),
        "spin": parameter_decision("spin", record("spin"), all_refs),
        "uks": parameter_decision("uks", record("uks"), all_refs),
        "periodicity": parameter_decision("periodicity", record("periodicity"), all_refs),
        "poisson_solver": parameter_decision("poisson_solver", record("poisson_solver"), all_refs),
        "k_points": parameter_decision("k_points", record("kpoints"), all_refs),
        "smearing": parameter_decision("smearing", record("smearing"), all_refs),
        "solvation": parameter_decision("solvation", combined("solvation", ["solvation.implicit", "solvation.explicit"]), all_refs),
        "software_compatibility": parameter_decision("software_compatibility", {
            "value": deepcopy(dict(route)),
            "provenance": "AgentA.route_capability",
            "source_ref": None,
            "rationale": "Capability registry route; real runtime remains subject to executable preflight.",
            "applicability": "selected engine/task", "uncertainty": "runtime version verification required",
            "approval_required": not bool(route.get("can_enter_real_preflight")),
            "status": "SOURCE_CONFIRMED" if route.get("integration_status") == "AVAILABLE" else "MISSING",
        }, all_refs),
        "license_compatibility": parameter_decision("license_compatibility", {
            "value": "UNKNOWN", "provenance": "license_registry_not_verified",
            "source_ref": None, "rationale": "No explicit verified license compatibility evidence was supplied.",
            "applicability": "selected engine deployment", "uncertainty": "UNKNOWN",
            "approval_required": True, "status": "MISSING",
        }, all_refs),
    }
    for name, source_name in {
        "basis_file_name": "basis_file_name", "potential_file_name": "potential_file_name",
        "kind_definitions": "kind_definitions", "cutoff_ry": "cutoff_ry",
        "rel_cutoff_ry": "rel_cutoff_ry", "scf_method": "scf.method",
        "eps_scf": "scf.eps_scf", "max_scf": "scf.max_scf",
        "cell_periodicity": "cell_periodicity", "poisson_periodicity": "poisson_periodicity",
        "center_coordinates": "center_coordinates", "software_version": "software_version",
    }.items():
        params[name] = parameter_decision(name, record(source_name), all_refs)

    cell_value = None
    if structure_mapping is not None:
        try:
            from ase.cell import Cell
            cellpar = Cell(structure_mapping.get("cell_angstrom")).cellpar()
            if all(float(value) > 0 for value in cellpar[:3]):
                cell_value = {"a": float(cellpar[0]), "b": float(cellpar[1]), "c": float(cellpar[2]),
                              "alpha": float(cellpar[3]), "beta": float(cellpar[4]), "gamma": float(cellpar[5])}
        except Exception:
            cell_value = None
    cell_record = {
        "value": cell_value, "provenance": "hash_pinned_structure_artifact",
        "source_ref": "artifact-" + str((artifact_ref or {}).get("sha256", ""))[:16] if artifact_ref else None,
        "rationale": "Unit-cell geometry read from the SHA-verified registered structure Artifact; not a method default.",
        "applicability": "STRUCTURE_GEOMETRY", "uncertainty": "ARTIFACT_BYTES_HASH_VERIFIED",
        "approval_required": False, "status": "SOURCE_CONFIRMED" if cell_value else "MISSING",
    }
    params["cell"] = parameter_decision("cell", cell_record, all_refs)

    fields_status = str(method_raw.get("status") or "")
    method_ready = overall_status == "READY" and not method_gaps
    capability_status = "VERIFIED" if route.get("can_enter_real_preflight") else (
        "PARTIAL" if route.get("integration_status") == "AVAILABLE" else "UNVERIFIED")
    version = record("software_version").get("value")
    build_identity = str(route.get("build_or_binary_identity") or (
        "MOCK_ONLY_NOT_RUNTIME_VERIFIED" if engine_request.get("execution_mode") == "mock" else "UNVERIFIED_BUILD"
    ))
    method_engine = {
        "engine_id": str(engine_request.get("engine") or "unknown"),
        "version": str(version or "UNDECLARED"),
        "build_or_binary_identity": build_identity,
    }
    registry_path = Path(__file__).resolve().parent / "engines" / "capability_registry.json"
    capability_records = []
    license_values = set()
    try:
        registry_bytes = registry_path.read_bytes()
        registry_sha = hashlib.sha256(registry_bytes).hexdigest()
        registry = json.loads(registry_bytes.decode("utf-8"))
        capability_records = [
            item for item in registry.get("capabilities", [])
            if item.get("capability_id") in set(route.get("capability_ids") or [])
        ]
        license_values = {str(item.get("license")) for item in capability_records if item.get("license")}
        if capability_records:
            registry_ref = {
                "evidence_id": "engine-registry-" + registry_sha[:16],
                "source_type": "software_registry",
                "source_uri": str(registry_path),
                "source_sha256": registry_sha,
                "locator": {"kind": "file", "value": ",".join(item["capability_id"] for item in capability_records)},
                "scope": "Agent A versioned software capability registry",
            }
            if registry_ref["evidence_id"] not in {item["evidence_id"] for item in all_refs}:
                all_refs.append(registry_ref)
    except Exception:
        registry_ref = None
    else:
        if capability_records:
            method_source_refs = list(method_source_refs) + [registry_ref] if registry_ref else method_source_refs
            if len(license_values) == 1 and registry_ref:
                params["license_compatibility"] = parameter_decision("license_compatibility", {
                    "value": next(iter(license_values)), "provenance": "AgentA_capability_registry",
                    "source_ref": registry_ref["evidence_id"],
                    "rationale": "License identifier read from the versioned Agent A capability registry; deployment entitlement may still require local verification.",
                    "applicability": "selected engine software package", "uncertainty": "package license metadata; deployment entitlement not verified",
                    "approval_required": True, "status": "SOURCE_CONFIRMED",
                }, all_refs)
    if capability_records and registry_ref:
        params["software_compatibility"] = parameter_decision("software_compatibility", {
            "value": deepcopy(dict(route)),
            "provenance": "AgentA.route_capability",
            "source_ref": registry_ref["evidence_id"],
            "rationale": "Capability registry route; real runtime remains subject to executable preflight.",
            "applicability": "selected engine/task", "uncertainty": "runtime version verification required",
            "approval_required": not bool(route.get("can_enter_real_preflight")),
            "status": "SOURCE_CONFIRMED",
        }, all_refs)

    body = {
        "schema_version": "1.0.0", "method_plan_id": "",
        "engine": method_engine,
        "execution_mode": str(method_raw.get("execution_mode") or engine_request.get("execution_mode") or "real"),
        "planning_scope": str(method_raw.get("planning_scope") or ("MOCK_ONLY" if engine_request.get("execution_mode") == "mock" else "REAL_CANDIDATE")),
        "mock_only": bool(method_raw.get("execution_mode") == "mock"),
        "real_execution_preflight_allowed": bool(route.get("can_enter_real_preflight")),
        "software_version": str(method_raw.get("software_version") or version or ""),
        "runtime_version_verified": bool(method_raw.get("runtime_version_verified")),
        "runtime_verified_version": method_raw.get("runtime_verified_version"),
        "runtime_version_matches": bool(method_raw.get("runtime_version_matches")),
        "parameters": params,
        "agent_a_field_records": flattened_records("", fields),
        "agent_a_field_records_raw": deepcopy(dict(fields)),
        "capability_assessment": {
            "status": capability_status,
            "capability_record_ref": ({
                "object_type": "SoftwareCapabilityRecord",
                "object_id": ",".join(item["capability_id"] for item in capability_records),
                "schema_version": "1.0.0",
                "sha256": registry_sha,
            } if capability_records else None),
            "verified_version": (
                str(route.get("runtime_verified_version"))
                if route.get("runtime_version_verified") is True
                and route.get("runtime_version_matches") is True
                and route.get("runtime_verified_version") else None
            ),
            "verification_evidence_refs": [],
        },
        "license_assessment": {
            "status": "REVIEW_REQUIRED" if license_values and len(license_values) == 1 else "UNKNOWN",
            "license_identifier": next(iter(license_values)) if len(license_values) == 1 else None,
            "evidence_refs": ([registry_ref] if capability_records and registry_ref else []),
        },
        "source_evidence_refs": method_source_refs,
        "decision_records": deepcopy(selection_records),
        "evidence_gaps": deepcopy(method_gaps),
        "status": "READY_FOR_REVIEW" if method_ready and overall_status == "READY" else "BLOCKED",
        "provenance": {
            "source_evidence_refs": method_source_refs,
            "generated_by": {"component_id": "pipeline.scientific_method_plan_adapter", "version": "1.0.0"},
            "transform_sha256": str(method_raw.get("transform_sha256") or __import__("hashlib").sha256(
                __import__("json").dumps(method_raw, sort_keys=True, default=str).encode()).hexdigest()),
        },
    }
    return body


def build_qc_gates(qc_contract: Mapping[str, Any]) -> list[dict]:
    checks = list(qc_contract.get("checks") or [])
    groups = {
        "FILE_COMPLETENESS": {1},
        "PROGRAM_NORMAL_TERMINATION": {2},
        "TECHNICAL_CONVERGENCE": {3},
        "STRUCTURAL_PLAUSIBILITY": {4},
    }
    result = []
    for gate_type, levels in groups.items():
        required = [item["evidence_key"] for item in checks if item.get("level") in levels and item.get("required")]
        if required:
            result.append({
                "gate_id": "qc-" + gate_type.lower(), "gate_type": gate_type,
                "status": "NOT_ASSESSED", "contract_id": str(qc_contract.get("task_type") or "AgentA-QC"),
                "required_evidence_types": required,
                "failure_action": "BLOCK_DOWNSTREAM",
            })
    result.extend([
        {"gate_id": "qc-scientific-validity", "gate_type": "SCIENTIFIC_VALIDITY",
         "status": "NOT_ASSESSED", "contract_id": str(qc_contract.get("task_type") or "AgentA-QC"),
         "required_evidence_types": ["scientific_review"], "failure_action": "REQUEST_REVIEW"},
        {"gate_id": "qc-user-acceptance", "gate_type": "USER_ACCEPTANCE",
         "status": "NOT_ASSESSED", "contract_id": str(qc_contract.get("task_type") or "AgentA-QC"),
         "required_evidence_types": ["user_acceptance"], "failure_action": "REQUEST_REVIEW"},
    ])
    return result


def build_resource_profile(resource_result: Mapping[str, Any], *, structure_mapping: Mapping[str, Any] | None,
                           model_config: Mapping[str, Any], task_type: str,
                           refs: list[dict], resource_source_ref: str | None,
                           resource_config: Mapping[str, Any]) -> dict:
    values_raw = resource_result.get("allocation") or {}
    profile_refs = [item for item in refs if resource_source_ref and item.get("evidence_id") == resource_source_ref]
    structure_refs = [item for item in refs if item.get("source_type") == "artifact"]
    values: dict[str, dict] = {}

    def fixed(name: str, value: Any, unit: str | None, source_refs: list[dict], rationale: str) -> dict:
        status = "EVIDENCED" if value is not None and source_refs else "MISSING"
        return {
            "status": status, "value": value, "unit": unit,
            "source_evidence_refs": deepcopy(source_refs), "applicable_scope": "current task and system",
            "policy_ref": None, "decision_id": "resource-" + name,
            "uncertainty": "EXPLICIT_PROFILE_VALUE_NOT_PERFORMANCE_PREDICTION",
            "rationale": rationale, "provenance": "explicit_resource_profile" if profile_refs else "source_structure",
            "source_ref": resource_source_ref if profile_refs else (structure_refs[0]["evidence_id"] if structure_refs else None),
            "applicability": "APPLICABLE", "approval_required": False,
            "source_status": "PROFILE_PROVIDED" if profile_refs else ("SOURCE_CONFIRMED" if structure_refs else "MISSING"),
        }

    atom_count = structure_mapping.get("atom_count") if structure_mapping else None
    values["atom_count"] = fixed("atom_count", atom_count, "atoms", structure_refs,
                                 "Count from the loaded hash-pinned structure Artifact.")
    system_type = model_config.get("system_type") or model_config.get("model_type")
    values["system_type"] = fixed("system_type", system_type, None, profile_refs,
                                  "Declared model system type; not a scheduler allocation.")
    values["software_task_type"] = fixed("software_task_type", task_type, None, profile_refs,
                                         "Declared engine/task context; not a scheduler allocation.")

    if resource_result.get("mock_only") is True or str(resource_result.get("status") or "").upper() == "MOCK_ONLY":
        def mock_na(name: str, unit: str | None = None) -> dict:
            return {
                "status": "NOT_APPLICABLE", "value": None, "unit": unit,
                "source_evidence_refs": [], "applicable_scope": "MOCK_ONLY; no real scheduler allocation",
                "policy_ref": None, "decision_id": "resource-" + name,
                "uncertainty": "NOT_ESTIMATED_FOR_MOCK",
                "rationale": "Agent A ResourcePlanner declares real HPC allocation and resource estimation NOT_APPLICABLE in Mock mode.",
                "provenance": "mock_only_not_estimated", "source_ref": None,
                "applicability": "NOT_APPLICABLE", "approval_required": False,
                "source_status": "NOT_APPLICABLE",
            }

        for field, unit in (
            ("nodes", "nodes"), ("cpu_cores", None), ("mpi_ranks", None),
            ("openmp_threads", None), ("gpu_count", None), ("gpu_model", None),
            ("memory_bytes", "bytes"), ("walltime_seconds", "seconds"), ("scratch_bytes", "bytes"),
        ):
            values[field] = mock_na(field, unit)
        return {
            "values": values,
            "estimate_uncertainty": {
                "class": "UNKNOWN",
                "basis": "MOCK_ONLY: no resource allocation or numerical estimate was produced.",
                "limitations": [
                    "No nodes, CPU, MPI, OpenMP, GPU, memory, walltime or scratch allocation is made.",
                    "A separately verified Real resource profile is required before any Real preflight.",
                ],
            },
            # Supplied Real profiles are deliberately not treated as inputs in Mock mode.
            "provenance_refs": structure_refs,
            "profile_id": None, "profile_source_ref": None,
            "verified_profile": False, "status": "MOCK_ONLY",
            "execution_mode": "mock", "planning_scope": "MOCK_ONLY",
            "mock_only": True, "real_execution_preflight_allowed": False,
            "resource_estimate_policy": resource_result.get("resource_estimate_policy"),
        }

    nodes_record = values_raw.get("nodes")
    if isinstance(nodes_record, Mapping):
        node_source = [item for item in refs if item.get("evidence_id") == nodes_record.get("source_ref")]
        values["nodes"] = fixed(
            "nodes", nodes_record.get("value"), "nodes", node_source,
            "Exact nodes allocation validated by Agent A ResourcePlanner.",
        )
        values["nodes"]["source_ref"] = nodes_record.get("source_ref")
        values["nodes"]["source_status"] = nodes_record.get("status", "MISSING")
        if nodes_record.get("status") != "PROFILE_PROVIDED":
            values["nodes"]["status"] = "MISSING"
    else:
        values["nodes"] = fixed("nodes", None, "nodes", [], "Agent A ResourcePlanner did not resolve nodes.")

    allocation_sources = {
        "mpi_ranks": ("mpi_ranks", 1),
        "openmp_threads": ("openmp_threads", 1),
        "gpu_count": ("gpu_count", 1),
        "memory_bytes": ("memory_gb", 1_000_000_000),
        "walltime_seconds": ("walltime_seconds", 1),
        "scratch_bytes": ("scratch_gb", 1_000_000_000),
    }
    for field, (source_key, multiplier) in allocation_sources.items():
        value_record = values_raw.get(source_key)
        if isinstance(value_record, Mapping):
            raw_value = value_record.get("value")
            if raw_value is not None and multiplier != 1:
                raw_value = int(float(raw_value) * multiplier)
            source = [item for item in refs if item.get("evidence_id") == value_record.get("source_ref")]
            unit = "bytes" if field in {"memory_bytes", "scratch_bytes"} else None
            values[field] = fixed(field, raw_value, unit, source,
                                  "Exact Agent A ResourcePlanner allocation; GB values are converted to decimal bytes.")
            values[field]["source_ref"] = value_record.get("source_ref")
            values[field]["source_status"] = value_record.get("status", "MISSING")
            if value_record.get("status") != "PROFILE_PROVIDED":
                values[field]["status"] = "MISSING"
        else:
            values[field] = fixed(field, None, "bytes" if field.endswith("_bytes") else None, [],
                                  "Agent A ResourcePlanner did not resolve this allocation field.")

    alloc = resource_config.get("allocation") or {}
    values["cpu_cores"] = fixed(
        "cpu_cores", alloc.get("cpu_cores"), None, profile_refs,
        "Explicit CPU core allocation from the approved Project Profile.",
    )
    gpu_model = (resource_config.get("allocation") or {}).get("gpu_model")
    if gpu_model is None and (resource_config.get("allocation") or {}).get("gpu_count") == 0:
        gpu_record = {"value": None, "provenance": "explicit_zero_gpu_allocation",
                      "source_ref": resource_source_ref, "rationale": "GPU count is explicitly zero; no GPU model applies.",
                      "applicability": "NOT_APPLICABLE", "uncertainty": "NOT_APPLICABLE",
                      "approval_required": False, "status": "NOT_APPLICABLE"}
        values["gpu_model"] = parameter_decision("gpu_model", gpu_record, refs)
    else:
        values["gpu_model"] = fixed("gpu_model", gpu_model, None, profile_refs,
                                    "GPU model explicitly specified by resource profile.")
    uncertainty = {
        "class": "UNKNOWN",
        "basis": "The profile contains explicit scheduler allocation values; no performance predictor was run.",
        "limitations": ["Walltime is a user/profile allocation, not an elapsed-time prediction.",
                        "No nodes/MPI/OpenMP/GPU/memory/scratch estimate is synthesized."],
    }
    profile_status = "READY" if resource_result.get("verified_profile") and not resource_result.get("missing_profile_fields") and all(v["status"] in {"EVIDENCED", "NOT_APPLICABLE"} for v in values.values()) else "BLOCKED"
    return {"values": values, "estimate_uncertainty": uncertainty, "provenance_refs": profile_refs + structure_refs,
            "profile_id": resource_result.get("profile_id"), "profile_source_ref": resource_source_ref,
            "verified_profile": bool(resource_result.get("verified_profile")), "status": profile_status}


__all__ = ["parameter_decision", "method_plan_object", "build_qc_gates", "build_resource_profile"]


__all__ = ["parameter_decision", "method_plan_object", "build_qc_gates", "build_resource_profile"]
