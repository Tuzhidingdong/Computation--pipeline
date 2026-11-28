"""Strict MethodPlan -> existing CalculationPlan v1.0 projection."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from pipeline_contracts.calculation_plan import CalculationPlan, PlanValidationError
from .bundle import canonical_sha256, object_ref
from .engines import to_cp2k_calculation_plan_method
from .execution_modes import agent_a_execution_mode

def _field_record(fields: Mapping[str, Any], name: str) -> dict:
    cursor: Any = fields.get(name)
    if not isinstance(cursor, Mapping):
        cursor = fields
        for part in name.split("."):
            if not isinstance(cursor, Mapping) or part not in cursor:
                cursor = None
                break
            cursor = cursor[part]
    if not isinstance(cursor, Mapping):
        raise PlanValidationError([f"MethodPlan.agent_a_field_records.{name} is missing"])
    required = ("value", "provenance", "source_ref", "rationale", "applicability",
                "uncertainty", "approval_required", "status")
    missing = [key for key in required if key not in cursor]
    if missing:
        raise PlanValidationError([
            f"MethodPlan.agent_a_field_records.{name} missing provenance fields: {', '.join(missing)}"
        ])
    status = str(cursor.get("status") or "").upper()
    if status in {"MISSING", "PROPOSED", "CONFLICT", "NEEDS_DECISION", "BLOCKED",
                  "DECLARED_UNVERIFIED", "UNRESOLVED", "INVALID_DECLARATION"}:
        raise PlanValidationError([f"MethodPlan.agent_a_field_records.{name} is not source-resolved ({status})"])
    if cursor.get("approval_required") is True:
        raise PlanValidationError([f"MethodPlan.agent_a_field_records.{name} still requires user approval"])
    source_ref = str(cursor.get("source_ref") or "").strip()
    # Engine applicability is not a science parameter source, and cannot satisfy
    # CalculationPlan requirements unless Agent A marked it NOT_APPLICABLE.
    if status != "NOT_APPLICABLE" and not source_ref:
        raise PlanValidationError([f"MethodPlan.agent_a_field_records.{name} has no source_ref"])
    if cursor.get("value") is None and status != "NOT_APPLICABLE":
        raise PlanValidationError([f"MethodPlan.agent_a_field_records.{name} has no source-backed value"])
    return dict(cursor)


def _get_fields(method_plan: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = method_plan.get("agent_a_field_records")
    if not isinstance(fields, Mapping):
        raise PlanValidationError(["MethodPlan.agent_a_field_records must retain Agent A's exact field records"])
    return fields


def project_method_fields(method_plan: Mapping[str, Any]) -> tuple[dict, dict]:
    fields = _get_fields(method_plan)
    method: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    issues: list[str] = []
    for source_name, target_name in FIELD_MAP.items():
        try:
            record = _field_record(fields, source_name)
            method[target_name] = deepcopy(record["value"])
            provenance[target_name] = record
        except PlanValidationError as exc:
            issues.extend(exc.issues)
    scf = {}
    for source_name, target_name in (
        ("scf.method", "method"), ("scf.eps_scf", "eps_scf"), ("scf.max_scf", "max_scf")
    ):
        try:
            record = _field_record(fields, source_name)
            scf[target_name] = deepcopy(record["value"])
            provenance["scf." + target_name] = record
        except PlanValidationError as exc:
            issues.extend(exc.issues)
    method["scf"] = scf

    try:
        periodicity_record = _field_record(fields, "periodicity")
        provenance["periodicity"] = periodicity_record
    except PlanValidationError as exc:
        issues.extend(exc.issues)
    if issues:
        raise PlanValidationError(issues)
    return method, {"field_provenance": provenance}


def _parameter_value(resource_values: Mapping[str, Any], name: str, *, allow_na: bool = False) -> Any:
    record = resource_values.get(name)
    if not isinstance(record, Mapping):
        raise PlanValidationError([f"ExecutionPlan.resource_profile.values.{name} is missing"])
    status = str(record.get("status") or "")
    if status == "NOT_APPLICABLE" and allow_na:
        return None
    if status != "EVIDENCED" or record.get("value") is None:
        raise PlanValidationError([f"ExecutionPlan.resource_profile.values.{name} is not source-resolved"])
    if not record.get("source_ref") or not record.get("source_evidence_refs"):
        raise PlanValidationError([f"ExecutionPlan.resource_profile.values.{name} has no source evidence"])
    return deepcopy(record["value"])


def compile_runtime_calculation_plan(
    *, project_id: str, project_root: str, title: str, scientific_question: str,
    model_recipe: Mapping[str, Any], method_plan: Mapping[str, Any],
    execution_plan: Mapping[str, Any], qc_plan: Mapping[str, Any],
    runtime_config: Mapping[str, Any], runtime_execution: Mapping[str, Any],
    approved_artifact: Mapping[str, Any], approval_ref: Mapping[str, Any],
) -> CalculationPlan:
    """Project only complete, approved and source-backed Planning objects to runtime v1.0."""
    if method_plan.get("planning_metadata", {}).get("planning_status") != "READY":
        raise PlanValidationError(["MethodPlan planning status must be READY"])
    if execution_plan.get("planning_metadata", {}).get("planning_status") != "READY":
        raise PlanValidationError(["ExecutionPlan planning status must be READY"])
    if qc_plan.get("planning_metadata", {}).get("planning_status") != "READY":
        raise PlanValidationError(["QCPlan planning status must be READY"])
    if model_recipe.get("planning_metadata", {}).get("planning_status") != "READY":
        raise PlanValidationError(["ModelRecipe planning status must be READY"])
    if not approval_ref or not approval_ref.get("object_id") or not approval_ref.get("sha256"):
        raise PlanValidationError(["explicit model approval ObjectRef is required before CalculationPlan compilation"])

    artifact_id = str(approved_artifact.get("artifact_id") or "")
    artifact_sha = str(approved_artifact.get("structure_sha256") or approved_artifact.get("sha256") or "")
    if not artifact_id or len(artifact_sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in artifact_sha):
        raise PlanValidationError(["approved Data_analysis Artifact ID and SHA-256 are required"])
    recipe_artifacts = model_recipe.get("input_artifact_refs") or []
    if not any(item.get("object_id") == artifact_id and item.get("sha256", "").lower() == artifact_sha.lower()
               for item in recipe_artifacts):
        raise PlanValidationError(["approved Artifact ID/SHA does not match the frozen ModelRecipe input Artifact reference"])

    validation = model_recipe.get("validation_contract") or {}
    cell = validation.get("cell") if isinstance(validation, Mapping) else None
    cell_source_ref = str(validation.get("cell_source_ref") or "") if isinstance(validation, Mapping) else ""
    expected_cell_ref = "artifact-" + artifact_sha[:16]
    if not isinstance(cell, Mapping) or any(cell.get(k) is None for k in ("a", "b", "c", "alpha", "beta", "gamma")):
        raise PlanValidationError(["ModelRecipe.validation_contract.cell must explicitly contain a,b,c,alpha,beta,gamma"])
    if cell_source_ref != expected_cell_ref:
        raise PlanValidationError(["ModelRecipe cell source must bind the exact approved structure Artifact SHA"])
    structure = {"artifact_id": artifact_id, "sha256": artifact_sha, "cell": deepcopy(dict(cell))}

    backend = execution_plan.get("backend")
    if not isinstance(backend, Mapping):
        raise PlanValidationError(["ExecutionPlan has no executable backend adapter"])
    backend_id = str(backend.get("backend_id") or "")
    agent_mode = agent_a_execution_mode(backend_id)
    if agent_mode is None:
        raise PlanValidationError([
            f"ExecutionPlan backend {backend_id!r} is not registered; refusing to infer an Agent A execution mode."
        ])
    if backend_id != "mock":
        raise PlanValidationError([
            "this ProjectPipeline resume path executes only Mock; Real CP2K remains a separately gated "
            "preflight capability and is never dispatched through MockCP2KWorkflowAdapter"
        ])
    task_nodes = execution_plan.get("task_nodes") or []
    runtime_calculations = runtime_config.get("calculations")
    if not isinstance(runtime_calculations, list) or not runtime_calculations:
        raise PlanValidationError(["Project Profile runtime.calculations must explicitly list task stages"])
    operations = {item.get("operation") for item in runtime_calculations if isinstance(item, Mapping)}
    if not {"cp2k.geo_opt", "cp2k.energy"}.issubset(operations):
        raise PlanValidationError(["runtime.calculations must explicitly include CP2K GEO_OPT and ENERGY"])

    raw_fields = _get_fields(method_plan)
    software = _field_record(raw_fields, "software_version")
    software_version = str(software["value"])
    if not software_version:
        raise PlanValidationError(["source-backed MethodPlan software_version must be non-empty"])
    calculations = []
    for index, item in enumerate(runtime_calculations):
        if not isinstance(item, Mapping) or item.get("operation") not in {"cp2k.geo_opt", "cp2k.energy"}:
            raise PlanValidationError([f"runtime.calculations[{index}] is not a supported CP2K GEO_OPT/ENERGY operation"])
        stage = deepcopy(dict(item))
        if str(stage.get("tool_version") or "") != software_version:
            raise PlanValidationError([f"runtime.calculations[{index}].tool_version must match source-backed MethodPlan software_version"])
        if not stage.get("id") or not isinstance(stage.get("output_files"), Mapping):
            raise PlanValidationError([f"runtime.calculations[{index}] requires id and explicit output_files"])
        if not stage["output_files"].get("cp2k_output"):
            raise PlanValidationError([f"runtime.calculations[{index}].output_files.cp2k_output is required"])
        if stage["operation"] == "cp2k.geo_opt" and not stage["output_files"].get("optimized_structure"):
            raise PlanValidationError(["GEO_OPT optimized_structure output path is required"])
        calculations.append(stage)

    resources_record = execution_plan.get("resource_profile") or {}
    resource_mode_mock = (
        str(execution_plan.get("execution_mode") or execution_plan.get("planning_scope") or "").casefold() == "mock"
        or (resources_record.get("status") == "MOCK_ONLY" and resources_record.get("mock_only") is True)
    )
    values = resources_record.get("values") or {}
    if resource_mode_mock:
        if (
            resources_record.get("status") != "MOCK_ONLY"
            or resources_record.get("verified_profile") is not False
            or resources_record.get("real_execution_preflight_allowed") is not False
        ):
            raise PlanValidationError(["Mock CalculationPlan requires an explicit MOCK_ONLY ResourcePlan with no Real preflight permission"])
        for name in ("nodes", "cpu_cores", "mpi_ranks", "openmp_threads", "gpu_count",
                     "gpu_model", "memory_bytes", "walltime_seconds", "scratch_bytes"):
            decision = values.get(name) or {}
            if decision.get("status") != "NOT_APPLICABLE" or decision.get("value") is not None:
                raise PlanValidationError([f"Mock ResourcePlan {name} must be NOT_APPLICABLE with no numeric value"])
        resources = {
            "resource_plan_status": "MOCK_ONLY",
            "planning_scope": "MOCK_ONLY",
            "mock_only": True,
            "real_execution_preflight_allowed": False,
            "resource_estimate_available": False,
            "allocation": None,
            "allocation_provenance": {
                "status": "NOT_APPLICABLE",
                "reason": "Agent A ResourcePlanner explicitly disables all HPC allocation and estimates in Mock mode.",
            },
        }
    else:
        if resources_record.get("status") != "READY" or resources_record.get("verified_profile") is not True:
            raise PlanValidationError(["ExecutionPlan Real ResourceProfile is not verified/ready"])
        allocation = {
            "cpu_cores": _parameter_value(values, "cpu_cores"),
            "mpi_ranks": _parameter_value(values, "mpi_ranks"),
            "openmp_threads": _parameter_value(values, "openmp_threads"),
            "gpu_count": _parameter_value(values, "gpu_count"),
            "memory_bytes": _parameter_value(values, "memory_bytes"),
            "walltime_seconds": _parameter_value(values, "walltime_seconds"),
            "scratch_bytes": _parameter_value(values, "scratch_bytes"),
            "atom_count": _parameter_value(values, "atom_count"),
            "system_type": _parameter_value(values, "system_type"),
        }
        if values.get("gpu_model", {}).get("status") == "NOT_APPLICABLE":
            allocation["gpu_model"] = None
        else:
            allocation["gpu_model"] = _parameter_value(values, "gpu_model")
        explicit_runtime_resources = runtime_execution.get("resource_profile")
        if not isinstance(explicit_runtime_resources, Mapping) or not explicit_runtime_resources:
            raise PlanValidationError(["Project Profile execution.resource_profile must supply explicit nodes and scheduler allocation fields"])
        for field in ("nodes", "mpi_ranks", "openmp_threads", "gpu_count", "memory_gb", "walltime_seconds", "scratch_gb"):
            if explicit_runtime_resources.get("allocation", {}).get(field) is None:
                raise PlanValidationError([f"Project Profile execution.resource_profile.allocation.{field} is required"])
        planner_allocation_checks = {
            "nodes": "nodes",
            "mpi_ranks": "mpi_ranks",
            "openmp_threads": "openmp_threads",
            "gpu_count": "gpu_count",
            "walltime_seconds": "walltime_seconds",
        }
        for profile_field, allocation_field in planner_allocation_checks.items():
            planned_value = _parameter_value(values, profile_field)
            declared_value = explicit_runtime_resources.get("allocation", {}).get(allocation_field)
            if planned_value != declared_value:
                raise PlanValidationError([
                    f"Project Profile allocation.{allocation_field} differs from Agent A ResourcePlanner's source-backed value"
                ])
        for profile_field, allocation_field in (("memory_bytes", "memory_gb"), ("scratch_bytes", "scratch_gb")):
            planned_bytes = _parameter_value(values, profile_field)
            declared_gb = explicit_runtime_resources.get("allocation", {}).get(allocation_field)
            expected_bytes = int(float(declared_gb) * 1_000_000_000) if declared_gb is not None else None
            if planned_bytes != expected_bytes:
                raise PlanValidationError([
                    f"Project Profile allocation.{allocation_field} differs from Agent A ResourcePlanner's source-backed value"
                ])
        resources = deepcopy(dict(explicit_runtime_resources["allocation"]))
        resources.update({
            "profile_id": str(resources_record.get("profile_id") or ""),
            "profile_source_ref": str(resources_record.get("profile_source_ref") or ""),
            "uncertainty": deepcopy(resources_record.get("estimate_uncertainty")),
            "allocation_provenance": deepcopy(allocation),
        })
        if not resources["profile_id"] or not resources["profile_source_ref"]:
            raise PlanValidationError(["ExecutionPlan Real ResourceProfile ID/source_ref are required"])

    analysis = runtime_config.get("analysis")
    if not isinstance(analysis, Mapping) or analysis.get("operation") != "dft.artifact.read":
        raise PlanValidationError(["Project Profile runtime.analysis must explicitly use dft.artifact.read"])
    retry = runtime_config.get("retry_policy")
    if not isinstance(retry, Mapping) or "infrastructure_retries" not in retry:
        raise PlanValidationError(["Project Profile runtime.retry_policy.infrastructure_retries is required"])
    try:
        if int(retry["infrastructure_retries"]) < 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise PlanValidationError(["runtime.retry_policy.infrastructure_retries must be a non-negative integer"])

    qc_gates = qc_plan.get("gates") or []
    required_technical = any(
        gate.get("gate_type") == "TECHNICAL_CONVERGENCE"
        and gate.get("status") == "NOT_ASSESSED"
        and "technical_convergence" in gate.get("required_evidence_types", [])
        for gate in qc_gates
    )
    if not required_technical:
        raise PlanValidationError(["QCPlan must include a technical-convergence gate"])
    quality_gates = {
        "geo_opt_converged": {
            "source": "AgentA:geo_opt.technical_convergence",
            "required": True,
            "qc_plan_sha256": qc_plan["planning_metadata"]["object_sha256"],
        },
        "qc_contract": deepcopy(qc_gates),
        "automatic_scientific_acceptance": False,
        "automatic_user_acceptance": False,
    }
    runtime_plan_id = "scientific-" + canonical_sha256({
        "project_id": project_id, "artifact_id": artifact_id, "artifact_sha": artifact_sha,
        "model_recipe_sha": model_recipe["planning_metadata"]["object_sha256"],
        "method_plan_sha": method_plan["planning_metadata"]["object_sha256"],
        "execution_plan_sha": execution_plan["planning_metadata"]["object_sha256"],
        "qc_plan_sha": qc_plan["planning_metadata"]["object_sha256"],
        "runtime_config": runtime_config, "runtime_execution": runtime_execution,
    })[:20]
    projection_context = {
        "schema_version": "1.0",
        "plan_id": runtime_plan_id,
        "title": title,
        "scientific_question": scientific_question,
        "project_root": project_root,
        "structure": deepcopy(structure),
        "method": {},
        "calculations": deepcopy(calculations),
        "execution": {"backend": backend["backend_id"], "resources": deepcopy(resources)},
        "analysis": deepcopy(dict(analysis)),
        "quality_gates": deepcopy(quality_gates),
        "retry_policy": deepcopy(dict(retry)),
        "metadata": {},
    }
    projection_method = to_cp2k_calculation_plan_method({
        "engine": str((method_plan.get("engine") or {}).get("engine_id") or ""),
        "status": "METHOD_FIELDS_RESOLVED",
        "ready_for_core_compilation": True,
        "blockers": [],
        "fields": deepcopy(dict(_get_fields(method_plan))),
        "calculation_plan_context": projection_context,
        "execution_mode": agent_mode,
        "software_version": software_version,
        "runtime_version_verified": method_plan.get("runtime_version_verified") is True,
        "runtime_verified_version": method_plan.get("runtime_verified_version"),
        "runtime_version_matches": method_plan.get("runtime_version_matches") is True,
    })
    if projection_method.get("status") != "READY":
        raise PlanValidationError(list(projection_method.get("blockers") or [
            "Agent A to_cp2k_calculation_plan_method did not resolve a valid CalculationPlan method."
        ]))
    method = deepcopy(projection_method["method"])
    method_meta = {"field_provenance": deepcopy(projection_method.get("field_provenance") or {})}
    if projection_method.get("validation", {}).get("status") != "PASS":
        raise PlanValidationError(["Agent A CalculationPlan projection did not pass CalculationPlan.validate()."])
    raw = {
        "schema_version": "1.0",
        "plan_id": runtime_plan_id,
        "title": title,
        "scientific_question": scientific_question,
        "project_root": project_root,
        "structure": structure,
        "method": method,
        "calculations": calculations,
        "execution": {"backend": backend["backend_id"], "resources": resources},
        "analysis": deepcopy(dict(analysis)),
        "quality_gates": quality_gates,
        "retry_policy": deepcopy(dict(retry)),
        "metadata": {
            "project_id": project_id, "planning_core_schema_version": "1.0.0",
            "execution_mode": agent_mode,
            "planning_scope": "MOCK_ONLY" if backend.get("backend_id") == "mock" else "REAL_PREFLIGHT_CANDIDATE",
            "mock_only": backend.get("backend_id") == "mock",
            "real_execution_preflight_allowed": False if backend.get("backend_id") == "mock" else False,
            "model_recipe_sha256": model_recipe["planning_metadata"]["object_sha256"],
            "method_plan_sha256": method_plan["planning_metadata"]["object_sha256"],
            "execution_plan_sha256": execution_plan["planning_metadata"]["object_sha256"],
            "qc_plan_sha256": qc_plan["planning_metadata"]["object_sha256"],
            "method_parameter_provenance": method_meta["field_provenance"],
            "software_version_provenance": software,
            "source_periodicity_record": method_meta["field_provenance"].get("cell_periodicity"),
            "engine_binding": deepcopy(method_plan.get("engine")),
            "resource_profile_provenance": {
                "profile_id": resources_record.get("profile_id"),
                "source_ref": resources_record.get("profile_source_ref"),
                "values": deepcopy(values),
            },
            "approval_ref": deepcopy(dict(approval_ref)),
            "method_projection_validator": "AgentA.to_cp2k_calculation_plan_method -> CalculationPlan.validate",
        },
    }
    plan = CalculationPlan.from_mapping(raw)
    plan.require_valid()
    return plan



def build_frozen_calculation_plan_object(
    *, bundle: Mapping[str, Any], runtime_plan: CalculationPlan,
    approval_ref: Mapping[str, Any], frozen_at: str | None = None,
) -> dict:
    """Create the schema-level frozen CalculationPlan object after model approval."""
    from .contracts import load_schema

    intent = bundle["scientific_intent"]
    research = bundle["research_plan"]
    recipes = list(bundle.get("model_recipes") or [])
    method = bundle["method_plan"]
    execution = bundle["execution_plan"]
    qc = bundle["qc_plan"]
    component_refs = {
        "scientific_intent": object_ref(intent, object_type="ScientificIntent", id_field="intent_id"),
        "research_plan": object_ref(research, object_type="ResearchPlan", id_field="plan_id"),
        "model_recipes": [object_ref(item, object_type="ModelRecipe", id_field="recipe_id") for item in recipes],
        "method_plan": object_ref(method, object_type="MethodPlan", id_field="method_plan_id"),
        "execution_plan": object_ref(execution, object_type="ExecutionPlan", id_field="execution_plan_id"),
        "qc_plan": object_ref(qc, object_type="QCPlan", id_field="qc_plan_id"),
    }
    backend = execution.get("backend")
    if not isinstance(backend, Mapping):
        raise PlanValidationError(["frozen CalculationPlan requires an explicit execution adapter binding"])
    capability_ref = (method.get("capability_assessment") or {}).get("capability_record_ref")
    if not isinstance(capability_ref, Mapping):
        raise PlanValidationError(["frozen CalculationPlan requires a registered Agent A capability record reference"])
    nodes = execution.get("task_nodes") or []
    if not nodes:
        raise PlanValidationError(["frozen CalculationPlan requires at least one task DAG node"])
    task_graph = []
    for node in nodes:
        task_graph.append({
            "task_id": node["task_id"],
            "operation_id": node["operation_id"],
            "depends_on": list(node.get("depends_on") or []),
            "input_refs": deepcopy(node.get("input_refs") or []),
            "parameter_sha256": str(method["planning_metadata"]["object_sha256"]),
            "resource_profile_ref": str(node.get("resource_profile_ref") or ""),
            "qc_contract_ref": object_ref(qc, object_type="QCPlan", id_field="qc_plan_id"),
        })
    if not approval_ref.get("object_id") or not approval_ref.get("sha256"):
        raise PlanValidationError(["frozen CalculationPlan requires an immutable explicit approval reference"])
    approval = {
        "object_type": str(approval_ref.get("object_type") or "ModelApproval"),
        "object_id": str(approval_ref["object_id"]),
        "schema_version": str(approval_ref.get("schema_version") or "1.0.0"),
        "sha256": str(approval_ref["sha256"]),
    }
    if len(approval["sha256"]) != 64:
        raise PlanValidationError(["approval record SHA-256 is invalid"])
    runtime_payload_sha = runtime_plan.sha256
    base = {
        "schema_version": "1.0.0",
        "plan_id": "calculation-" + canonical_sha256({
            "components": component_refs, "approval": approval,
            "runtime_projection_sha256": runtime_payload_sha,
        })[:20],
        "project_id": str(intent["project_id"]),
        "title": str(runtime_plan.title),
        "scientific_question": str(intent["research_question"]),
        "component_refs": component_refs,
        "engine_binding": {
            "engine_id": str(method["engine"]["engine_id"]),
            "engine_version": str(method["engine"]["version"]),
            "plugin_id": str(backend["adapter_id"]),
            "plugin_version": str(backend["adapter_version"]),
            "capability_record_ref": deepcopy(dict(capability_ref)),
        },
        "task_graph": task_graph,
        "approval_refs": [approval],
        "canonicalization": {
            "algorithm": "SHA-256",
            "canonical_json_profile": "PIPELINE_CANONICAL_JSON_V1",
        },
        "frozen_at": frozen_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime_projection": {
            "target": "pipeline_contracts.calculation_plan.CalculationPlan",
            "runtime_schema_version": runtime_plan.schema_version,
            "payload_sha256": runtime_payload_sha,
        },
    }
    digest = canonical_sha256(base)
    base["sha256"] = digest
    upstream = {
        name: ref["sha256"] for name, ref in component_refs.items()
        if name != "model_recipes"
    }
    upstream["model_recipes"] = canonical_sha256(component_refs["model_recipes"])
    base["planning_metadata"] = {
        "object_type": "CalculationPlan",
        "object_sha256": digest,
        "source_evidence_refs": deepcopy(bundle.get("planning_metadata", {}).get("source_evidence_refs", [])),
        "upstream_sha256s": dict(sorted(upstream.items())),
        "selection_records": deepcopy(bundle.get("planning_metadata", {}).get("selection_records", [])),
        "missing_items": [],
        "planning_status": "READY",
    }
    schema = load_schema()
    wrapper = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/CalculationPlan",
    }
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise RuntimeError("CalculationPlan schema validation requires jsonschema") from exc
    errors = sorted(
        Draft202012Validator(wrapper, format_checker=FormatChecker()).iter_errors(base),
        key=lambda item: (list(item.absolute_path), item.message),
    )
    if errors:
        details = [f"{'.'.join(str(x) for x in e.absolute_path) or '$'}: {e.message}" for e in errors]
        raise ValueError("Frozen CalculationPlan object does not satisfy PR #6 schema: " + "; ".join(details))
    return base
