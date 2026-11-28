"""Project Run -> seven planning objects using the existing lifecycle and plugin contracts."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .bundle import canonical_sha256, object_index, seal_object, write_immutable_json
from .contracts import PLANNING_SCHEMA_VERSION, validate_bundle
from .decision_policy import aggregate_status, evidence_gap
from .intent_compiler import compile_intent, compile_model_recipe, evidence_refs
from .object_adapters import method_plan_object, build_qc_gates, build_resource_profile
from .plugin_registry import engine_planning, MODEL_PLUGIN_REGISTRY, plugin_capability_status
from .research_planner import build_research_plan
from .execution_modes import agent_a_execution_mode, planning_mode_fields


def _sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _load_profile(project_id: str, run_root: Path, explicit: str | Path | None) -> tuple[dict, str, str]:
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve(strict=True))
    candidates.append(run_root / "project_profile.json")
    candidates.append(Path(__file__).resolve().parents[2] / "projects" / project_id / "project_profile.json")
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, Mapping):
                raise ValueError("Project Profile must be a JSON object")
            return dict(data), str(path.resolve()), _sha(path)
    return {}, "", "0" * 64


def _profile_evidence_ref(profile_path: str, profile_sha: str, project_id: str) -> dict | None:
    if not profile_path or len(profile_sha) != 64 or profile_sha == "0" * 64:
        return None
    return {
        "evidence_id": "profile-" + profile_sha[:16], "source_type": "approved_policy",
        "source_uri": profile_path, "source_sha256": profile_sha,
        "locator": {"kind": "file", "value": project_id},
        "scope": f"Project Profile for {project_id}",
    }


def _resolve_structure(model_cfg: Mapping[str, Any], api: Any, run_root: Path,
                       data_analysis_root: str | Path | None) -> tuple[dict | None, str | None, dict | None, list[dict]]:
    gaps = []
    artifact = model_cfg.get("structure_artifact") or {}
    if not isinstance(artifact, Mapping):
        return None, None, None, [evidence_gap(
            "STRUCTURE_ARTIFACT_INVALID", "model.structure_artifact",
            "A registered hash-pinned structure Artifact is required before calculation planning.",
            "Which registered Data_analysis structure Artifact should be used?",
        )]
    artifact_id = str(artifact.get("artifact_id") or "")
    expected_sha = str(artifact.get("sha256") or artifact.get("artifact_sha256") or "")
    source_path = artifact.get("path")
    if not artifact_id:
        gaps.append(evidence_gap(
            "STRUCTURE_ARTIFACT_ID_MISSING", "model.structure_artifact.artifact_id",
            "A file path alone does not establish Data_analysis Artifact custody.",
            "Provide the exact registered Data_analysis artifact_id.",
        ))
        return None, None, None, gaps
    if len(expected_sha) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected_sha):
        gaps.append(evidence_gap(
            "STRUCTURE_ARTIFACT_SHA_MISSING", "model.structure_artifact.sha256",
            "The exact structure Artifact SHA-256 must be recorded in the Project Profile.",
            "Provide the registered Artifact SHA-256; do not derive or replace it from a local path.",
        ))
        return None, None, None, gaps
    if api is None:
        gaps.append(evidence_gap(
            "DATA_ANALYSIS_ARTIFACT_RESOLVER_MISSING", "model.structure_artifact.artifact_id",
            "The existing Data_analysis Artifact API is required to resolve and verify the registered Artifact.",
            "Configure the existing Data_analysis integration factory for this Project Run.",
        ))
        return None, None, None, gaps
    resolver_root = str(data_analysis_root or artifact.get("project_root") or run_root)
    source_path = api.resolve_artifact_path(resolver_root, artifact_id)
    if not source_path:
        gaps.append(evidence_gap(
            "STRUCTURE_ARTIFACT_PATH_UNRESOLVED", "model.structure_artifact.path",
            "The existing Data_analysis Artifact could not be resolved to bytes.",
            "Provide a resolvable Artifact through the configured Data_analysis integration.",
        ))
        return None, None, None, gaps
    path = Path(source_path).expanduser().resolve(strict=True)
    actual_sha = _sha(path)
    if expected_sha.lower() != actual_sha.lower():
        gaps.append(evidence_gap(
            "STRUCTURE_ARTIFACT_SHA_MISMATCH", "model.structure_artifact.sha256",
            "The resolved file bytes do not match the Project Profile Artifact SHA-256.",
            "Restore the exact registered Artifact bytes or update the profile through an authorized change.",
        ))
        return None, str(path), None, gaps
    try:
        from .plugin_registry import run_structure_plugin
        source = {"path": str(path), "sha256": actual_sha,
                  "artifact_id": artifact_id, "artifact_sha256": actual_sha}
        mapping = MODEL_PLUGIN_REGISTRY.invoke(
            "load_structure_model",
            {"source": source, "structure_type": str(model_cfg.get("structure_type") or "atomistic")},
        )
        if not isinstance(mapping, Mapping) or not isinstance(mapping.get("atom_count"), int) or mapping.get("atom_count", 0) <= 0:
            raise ValueError("load_structure_model did not return a non-empty ASE structure Mapping")
        # Artifact identity is added only after Data_analysis resolution and exact
        # SHA verification. The Agent C adapter also receives these fields.
        mapping.setdefault("source", {}).update({
            "artifact_id": artifact_id, "artifact_sha256": actual_sha,
            "path": str(path), "sha256": actual_sha,
        })
        artifact_ref = {"artifact_id": artifact_id, "sha256": actual_sha,
                        "artifact_sha256": actual_sha, "source_system": "Data_analysis",
                        "verified": True, "uri": path.as_uri()}
        return mapping, str(path), artifact_ref, gaps
    except Exception as exc:
        gaps.append(evidence_gap(
            "STRUCTURE_PLUGIN_REJECTED_SOURCE", "model.structure_artifact",
            f"ASE structure adapter rejected the source: {type(exc).__name__}: {exc}",
            "Resolve the reported source/structure issue; the planner will not infer a replacement.",
        ))
        return None, str(path), None, gaps


def _source_refs_for_method(fields: Mapping[str, Any], refs: list[dict]) -> list[dict]:
    by_id = {item["evidence_id"]: item for item in refs}
    selected = []
    def walk(value: Any):
        if isinstance(value, Mapping):
            if "source_ref" in value:
                ref = str(value.get("source_ref") or "")
                if ref in by_id and by_id[ref] not in selected:
                    selected.append(by_id[ref])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(fields)
    return selected


def _method_sources(config: Mapping[str, Any], manifest: Mapping[str, Any], profile_ref: dict | None,
                    structure_mapping: Mapping[str, Any] | None = None) -> list[dict]:
    explicit = config.get("sources")
    if isinstance(explicit, list):
        sources = deepcopy(explicit)
    else:
        sources = []
    # Only explicitly user-confirmed Manifest claims can contribute method values.
    confirmed_ids = {
        str(evidence_id)
        for confirmation in manifest.get("confirmations", [])
        for evidence_id in confirmation.get("evidence_ids", [])
    }
    for claim in manifest.get("claims", []):
        if str(claim.get("status") or "").casefold() != "user_confirmed":
            continue
        field = str(claim.get("field") or "").strip().casefold().replace(" ", "_").replace("-", "_")
        if not field:
            continue
        if field in {"functional", "exchange_correlation", "xc"}:
            field = "xc_functional"
        evidence_ids = claim.get("evidence_ids") or [claim.get("evidence_id")]
        evidence_ids = [str(evidence_id) for evidence_id in evidence_ids if evidence_id and str(evidence_id) in confirmed_ids]
        for evidence_id in evidence_ids:
            if evidence_id:
                sources.append({
                    "source_kind": "frozen_source", "source_ref": str(evidence_id),
                    "fields": {field: claim.get("value")},
                })
    # Exact structure geometry is sourced from the hash-pinned Data_analysis Artifact.
    # It cannot supply electronic, KIND, basis/pseudopotential or Poisson choices.
    if structure_mapping and (structure_mapping.get("source") or {}).get("artifact_id"):
        source = structure_mapping["source"]
        artifact_source_ref = "artifact-" + str(source.get("artifact_sha256", ""))[:16]
        cell_matrix = structure_mapping.get("cell_angstrom")
        cell_value = None
        try:
            from ase.cell import Cell
            parameters = Cell(cell_matrix).cellpar()
            if all(float(value) > 0 for value in parameters[:3]):
                cell_value = {"a": float(parameters[0]), "b": float(parameters[1]), "c": float(parameters[2]),
                              "alpha": float(parameters[3]), "beta": float(parameters[4]), "gamma": float(parameters[5])}
        except Exception:
            cell_value = None
        periodic = _periodicity_from_structure(structure_mapping)
        geometry_fields = {}
        if cell_value is not None:
            geometry_fields["cell"] = cell_value
        if periodic is not None:
            geometry_fields["periodicity"] = periodic
            geometry_fields["cell_periodicity"] = periodic
        if geometry_fields:
            sources.append({"source_kind": "frozen_source", "source_ref": artifact_source_ref,
                            "fields": geometry_fields})
    # Project Profile is only authoritative when it explicitly declares approval.
    if profile_ref and config.get("approved_profile_fields") and config.get("approved") is True:
        sources.append({
            "source_kind": "approved_profile", "approved": True,
            "source_ref": profile_ref["evidence_id"],
            "fields": deepcopy(config["approved_profile_fields"]),
        })
    return sources


def _periodicity_from_structure(mapping: Mapping[str, Any]) -> str | None:
    pbc = mapping.get("periodic_boundary_conditions")
    if not isinstance(pbc, (list, tuple)) or len(pbc) != 3:
        return None
    return "".join(axis for axis, flag in zip(("X", "Y", "Z"), pbc) if bool(flag)) or "NONE"


def _qc_type(task_type: str) -> str:
    token = str(task_type).casefold()
    if "geo_opt" in token or "geometry" in token:
        return "geo_opt"
    if "energy" in token or "scf" in token:
        return "energy_scf"
    if "frequency" in token or "freq" in token:
        return "frequency"
    if "neb" in token or "band" in token or "dimer" in token:
        return "neb_band_dimer"
    if "aimd" in token:
        return "aimd"
    if "solvent" in token:
        return "explicit_solvent_preparation"
    if "analysis" in token:
        return "electronic_structure_analysis"
    return token


def _engine_request(config: Mapping[str, Any], structure: Mapping[str, Any] | None,
                    method_sources: list[dict], *,
                    runtime_verified_version: str | None = None) -> dict:
    model_cfg = config.get("model") or {}
    mapping = structure or {}
    pbc = mapping.get("periodic_boundary_conditions")
    axes = ["X", "Y", "Z"]
    periodicity = "".join(axis for axis, flag in zip(axes, pbc or []) if bool(flag)) if pbc is not None else None
    periodicity = periodicity or ("NONE" if pbc is not None else None)
    method_config = config.get("method") or {}
    execution_config = config.get("execution") or {}
    execution = config.get("execution") or {}
    backend = execution.get("backend")
    agent_mode = agent_a_execution_mode(backend)
    # This observation must be supplied independently by the caller. Never
    # promote software_version or source-document/Profile content to runtime evidence.
    observed_runtime_version = (
        runtime_verified_version.strip()
        if isinstance(runtime_verified_version, str) and runtime_verified_version.strip()
        else None
    )
    return {
        "engine": str(method_config.get("engine") or config.get("engine") or ""),
        "task_type": str(config.get("task_type") or ""),
        "execution_mode": agent_mode if agent_mode is not None else "blocked",
        "execution_backend": backend,
        "execution_backend_registered": agent_mode is not None,
        "runtime_verified_version": observed_runtime_version,
        "software_version": method_config.get("software_version") or config.get("software_version"),
        "software_version_provenance": method_config.get("software_version_provenance") or "project_profile_method_source",
        "software_version_source_ref": method_config.get("software_version_source_ref"),
        # Agent A's runtime_version_verified gate is authorized only by an
        # independently supplied runtime observation. Project Profile/document
        # declarations are not runtime evidence. Exact version equality is
        # evaluated separately by Agent A's method and capability planners.
        "runtime_version_verified": observed_runtime_version is not None,
        "features": list(config.get("features") or []),
        "sources": method_sources,
        "structure": {
            "atom_count": mapping.get("atom_count"),
            "system_type": model_cfg.get("system_type") or model_cfg.get("model_type"),
            "periodicity": periodicity,
        },
        "resource_profile": deepcopy(config.get("resource_profile") or execution_config.get("resource_profile") or {}),
        "method_fingerprint": config.get("method_fingerprint"),
        "hardware_fingerprint": config.get("hardware_fingerprint"),
        "benchmarks": list(config.get("benchmarks") or []),
    }


def _method_decisions(method_result: Mapping[str, Any], evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    decisions, gaps = [], []
    fields = method_result.get("fields") or {}
    by_id = {item["evidence_id"]: item for item in evidence}
    def flatten(prefix: str, mapping: Mapping[str, Any]):
        for key, value in mapping.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, Mapping) and "value" not in value:
                yield from flatten(name, value)
            elif isinstance(value, Mapping):
                yield name, value
    for name, value in flatten("", fields):
        if not isinstance(value, Mapping):
            continue
        status = str(value.get("status") or "").upper()
        source_ref = str(value.get("source_ref") or "")
        refs = [by_id[source_ref]] if source_ref in by_id else []
        if status in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE", "NOT_APPLICABLE"}:
            selected = deepcopy(value.get("value"))
            decisions.append({
                "decision_id": "method-" + str(name).replace(".", "-"),
                "subject": "MethodPlan.parameters." + str(name),
                "selection_mode": "A_EVIDENCE_OR_APPROVED_FACT" if refs else "B_APPROVED_POLICY",
                "status": "SELECTED_FROM_EVIDENCE" if refs else "SELECTED_BY_POLICY",
                "selected_value": selected,
                "source_evidence_refs": refs,
                "policy_ref": None,
                "applicable_scope": str(value.get("applicability") or "unspecified"),
                "candidates": [{
                    "candidate_id": "selected-" + str(name).replace(".", "-"),
                    "value": selected, "evidence_refs": refs, "compatibility_status": status,
                }],
                "excluded_candidates": [], "assumptions": [],
                "uncertainties": [str(value.get("uncertainty") or "UNKNOWN")],
                "requires_user_approval": bool(value.get("approval_required")),
                "approval_ref": None, "missing_information": [], "minimum_questions": [],
            })
        elif status in {"MISSING", "PROPOSED", "CONFLICT", "NEEDS_DECISION", "DECLARED_UNVERIFIED", "UNRESOLVED"}:
            gaps.append(evidence_gap(
                "METHOD_PARAMETER_" + status,
                "MethodPlan.parameters." + str(name),
                str(value.get("rationale") or "Agent A MethodPlanner did not resolve this parameter from an authorized source."),
                f"Provide a source-backed value or approved policy for {name}.",
                refs,
            ))
    for name in method_result.get("missing_fields", []):
        if not any(item["field_path"].endswith(str(name)) for item in gaps):
            gaps.append(evidence_gap(
                "METHOD_PARAMETER_MISSING", "MethodPlan.parameters." + str(name),
                "The Agent A MethodPlanner marked this required field missing.",
                f"Provide a source-backed value for {name}.", evidence,
            ))
    return decisions, gaps

def _planning_status_legacy(kind: str, status: str) -> str:
    if status == "BLOCKED" or status == "UNSUPPORTED":
        return "BLOCKED"
    if status == "NEEDS_DECISION":
        return "DRAFT"
    if status == "PLANNABLE_ONLY":
        return "READY_FOR_REVIEW"
    return {
        "ScientificIntent": "READY_FOR_RESEARCH_PLANNING",
        "ResearchPlan": "READY_FOR_MODEL_AND_METHOD_PLANNING",
        "ModelRecipe": "READY_FOR_REVIEW",
        "MethodPlan": "READY_FOR_REVIEW",
        "ExecutionPlan": "READY_FOR_REVIEW",
        "QCPlan": "READY",
    }.get(kind, "DRAFT")


def plan_project_run(pipeline, run_id: str, *, profile_path: str | Path | None = None,
                     data_analysis_api=None, data_analysis_project_root: str | Path | None = None,
                     runtime_verified_version: str | None = None) -> dict:
    """Compile a deterministic bundle from one existing Project Run and its Project Profile."""
    info = pipeline.lifecycle.run_info(run_id)
    project_id = str(info["project_id"])
    manifest = pipeline.lifecycle.manifest(run_id)
    run_root = pipeline._run_root(run_id)
    profile, resolved_profile_path, profile_sha = _load_profile(project_id, run_root, profile_path)
    config = profile.get("scientific_planning") or profile.get("planning") or {}
    if not isinstance(config, Mapping):
        raise ValueError("Project Profile scientific_planning section must be an object")
    config = dict(config)
    if runtime_verified_version is not None:
        if not isinstance(runtime_verified_version, str):
            raise TypeError("runtime_verified_version must be supplied as an independent version string")
        runtime_verified_version = runtime_verified_version.strip() or None
    refs = evidence_refs(manifest)
    profile_ref = _profile_evidence_ref(resolved_profile_path, profile_sha, project_id)
    all_refs = list(refs) + ([profile_ref] if profile_ref else [])
    resource_cfg_for_ref = (config.get("execution") or {}).get("resource_profile") or {}
    resource_source_ref = str(resource_cfg_for_ref.get("source_ref") or "")
    if resource_source_ref:
        all_refs.append({
            "evidence_id": resource_source_ref, "source_type": "approved_policy",
            "source_uri": resolved_profile_path, "source_sha256": profile_sha,
            "locator": {"kind": "file", "value": f"{project_id}:resource_profile"},
            "scope": f"Explicit resource allocation profile in {project_id} Project Profile",
        })

    # Same-input planning is a deterministic read of the existing immutable bundle.
    # Any changed Manifest/Profile/config/Artifact requires a new Project Run.
    generate_stage = pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")
    fingerprint_payload = {
        "project_run_id": run_id,
        "manifest_file_sha256": _sha(run_root / "manifest.json"),
        "project_profile_sha256": profile_sha,
        "planning_config": config,
    }
    # Preserve old same-input fingerprints when there is no external runtime
    # observation; a supplied observation becomes part of this frozen input.
    if runtime_verified_version is not None:
        fingerprint_payload["runtime_verified_version"] = runtime_verified_version
    input_fingerprint = canonical_sha256(fingerprint_payload)
    if generate_stage["status"] != "PENDING":
        outputs = generate_stage.get("outputs") or {}
        bundle_path = outputs.get("planning_bundle_path")
        context_path = outputs.get("planner_context_path")
        if not bundle_path or not context_path or not Path(bundle_path).is_file() or not Path(context_path).is_file():
            raise RuntimeError("existing Planning Core state is incomplete; refusing to create a second version")
        existing_bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        existing_context = json.loads(Path(context_path).read_text(encoding="utf-8"))
        if existing_context.get("input_fingerprint") != input_fingerprint:
            raise FileExistsError(
                "Manifest, Project Profile or planning input changed after this Project Run's Planning Bundle was created; "
                "start a new Project Run instead of replacing a frozen planning object"
            )
        prior_artifact = existing_context.get("artifact_ref") or {}
        prior_structure = existing_context.get("structure_path")
        if prior_artifact and prior_structure:
            structure_file = Path(prior_structure)
            if not structure_file.is_file() or _sha(structure_file).lower() != str(prior_artifact.get("sha256", "")).lower():
                raise ValueError("the structure Artifact bytes changed after Planning Bundle creation")
        calculation_outputs = pipeline.lifecycle.stage(run_id, "CALCULATION_PLAN").get("outputs") or {}
        missing = existing_bundle.get("planning_metadata", {}).get("missing_items", [])
        method = existing_bundle.get("method_plan") or {}
        execution = existing_bundle.get("execution_plan") or {}
        qc = existing_bundle.get("qc_plan") or {}
        planning_directory = str(Path(bundle_path).parent)
        return {
            "project_run_id": run_id, "bundle_id": existing_bundle.get("bundle_id"),
            "planning_status": existing_bundle["planning_metadata"]["planning_status"],
            "candidate_id": outputs.get("candidate_id"),
            "bundle_sha256": existing_bundle["planning_metadata"]["object_sha256"],
            "planning_directory": planning_directory,
            "files": {name: str(Path(planning_directory) / name) for name in (
                "scientific_intent.json", "research_plan.json", "model_recipe.json",
                "method_plan.json", "execution_plan.json", "qc_plan.json",
                "planning_bundle.json", "planning_index.json", "planner_context.json")},
            "missing_items": missing,
            "questions": [item["minimum_question"] for item in missing],
            "model_plugin_status": (existing_context.get("model_plugin_result") or {}).get("status"),
            "workflow_created": bool(calculation_outputs.get("workflow_run_id")),
            "calculation_plan_created": bool(calculation_outputs.get("plan_sha256")),
            "method_status": method["planning_metadata"]["planning_status"],
            "execution_status": execution["planning_metadata"]["planning_status"],
            "resource_profile_status": (execution.get("resource_profile") or {}).get("status"),
            "qc_status": qc["planning_metadata"]["planning_status"],
            "idempotent_reuse": True,
        }

    intent, intent_gaps = compile_intent(project_id, manifest, config, all_refs)
    research_config = config.get("research_plan") or {}
    research_dependencies = (
        research_config.get("dependencies", {})
        if isinstance(research_config, Mapping) else {}
    )
    research = build_research_plan(intent, intent_gaps, dependencies=research_dependencies)
    upstream = {
        "scientific_intent": intent["planning_metadata"]["object_sha256"],
        "research_plan": research["planning_metadata"]["object_sha256"],
    }

    downstream_statuses = [
        pipeline.lifecycle.stage(run_id, stage)["status"]
        for stage in ("MODEL_GENERATE", "MODEL_VALIDATE", "MODEL_REVIEW", "MODEL_APPROVAL",
                      "MODEL_ARTIFACT_FREEZE", "CALCULATION_PLAN", "WORKFLOW_EXECUTION", "RESULT_DELIVERY")
    ]
    if any(value not in {"PENDING", "BLOCKED"} for value in downstream_statuses):
        raise RuntimeError("Scientific planning is immutable after model approval or any downstream stage starts")

    review_complete = pipeline.lifecycle.stage(run_id, "EVIDENCE_REVIEW")["status"] == "COMPLETED"
    readiness_gaps = list(intent_gaps)
    if not review_complete:
        readiness_gaps.append(evidence_gap(
            "EVIDENCE_REVIEW_INCOMPLETE", "project_run.EVIDENCE_REVIEW",
            "Scientific planning must consume a confirmed Manifest, not unreviewed extracted claims.",
            "Complete explicit evidence confirmation for this Project Run.", all_refs,
        ))

    model_config = config.get("model") or {}
    model_type_token = str(model_config.get("model_type") or "").upper()
    if model_type_token in {"INTERFACE", "IMPLICIT_SOLVATION_CONTEXT"}:
        route_label = "interface" if model_type_token == "INTERFACE" else "implicit solvation"
        unsupported_route = MODEL_PLUGIN_REGISTRY.route(route_label)
        if plugin_capability_status(unsupported_route) == "UNSUPPORTED":
            readiness_gaps.append(evidence_gap(
                "MODEL_FAMILY_UNSUPPORTED", "model.model_type",
                str(unsupported_route.get("reason") or f"{route_label} is not implemented by the current structure plugin layer."),
                "Choose a currently supported model family or keep the work as a documented research plan.", all_refs,
            ))
    structure_mapping = None
    structure_path = None
    artifact_ref = None
    model_plugin_result = None
    plugin_config = config.get("structure_plugin") or {}
    operation = plugin_config.get("operation") if isinstance(plugin_config, Mapping) else None
    model_type_token = str(model_config.get("model_type") or "").upper()
    # Existing registered Artifact loading uses ASE directly and must not be
    # blocked by optional RDKit/pymatgen construction dependencies.
    # Route checks apply to an explicitly requested construction operation,
    # plus model families the current registry explicitly marks unsupported.
    route_labels = {
        "INTERFACE": "interface",
        "IMPLICIT_SOLVATION_CONTEXT": "implicit solvation",
        "EXPLICIT_SOLVENT": "explicit solvation",
        "TRANSITION_STATE_PATH": "transition-state initial path",
        "CRYSTAL": "crystal/supercell",
        "SURFACE": "slab/surface",
        "SLAB": "slab/surface",
        "ADSORPTION": "adsorption",
        "CONFORMER": "molecule/conformer",
        "MOLECULE": "molecule/conformer",
    }
    route_label = str((plugin_config or {}).get("route_type") or route_labels.get(model_type_token) or "")
    if operation == "load_structure_model":
        model_route_status = "READY"
    elif operation or model_type_token in {"INTERFACE", "IMPLICIT_SOLVATION_CONTEXT"}:
        model_route = structure_route(route_label)
        model_route_status = plugin_capability_status(model_route)
        if model_route_status == "UNSUPPORTED":
            readiness_gaps.append(evidence_gap(
                "MODEL_FAMILY_UNSUPPORTED", "model.model_type",
                str(model_route.get("reason") or f"The structure plugin route {route_label!r} is unsupported."),
                "Choose a currently supported model family or keep the work as a documented research plan.",
                all_refs,
            ))
    else:
        model_route_status = "READY"
    if operation and review_complete:
        plugin_config = dict(config.get("structure_plugin") or {})
        if operation == "load_structure_model":
            route_status = "READY"
        else:
            model_route = structure_route(route_label)
            route_status = plugin_capability_status(model_route)
        plugin_out = run_root / "structures" / str(plugin_config.get("output_name") or "generated")
        args = dict(plugin_config.get("arguments") or {})
        if data_analysis_api is not None and data_analysis_project_root:
            registry_root = str(data_analysis_project_root)
        else:
            registry_root = str(run_root / "model_candidates")
        model_plugin_result = MODEL_PLUGIN_REGISTRY.invoke(str(operation), args, plugin_out)
        raw_status = str(model_plugin_result.get("status") or "").upper()
        if raw_status in {"NEEDS_DECISION", "BLOCKED"}:
            readiness_gaps.append(evidence_gap(
                "STRUCTURE_PLUGIN_NEEDS_DECISION", "model.structure_plugin",
                "; ".join(model_plugin_result.get("decision_required", model_plugin_result.get("errors", []))),
                "Supply only the missing explicit structure recipe inputs reported by the plugin.",
                all_refs,
            ))
        elif raw_status.startswith("UNSUPPORTED"):
            route_status = "UNSUPPORTED"
        elif route_status == "UNSUPPORTED":
            readiness_gaps.append(evidence_gap(
                "STRUCTURE_PLUGIN_UNSUPPORTED", "model.structure_plugin.operation",
                "The selected model route is explicitly unsupported by the available plugin registry.",
                "Choose a supported model plugin or defer this model family.", all_refs,
            ))
        # Packmol and IDPP report a primary artifact but keep their raw status labels.
        artifacts = model_plugin_result.get("artifacts") or []
        primary = next((item for item in artifacts if str(item.get("path", "")).endswith((".extxyz", ".xyz", ".pdb"))), None)
        if primary:
            artifact_path = Path(primary["path"])
            if not artifact_path.is_absolute():
                artifact_path = plugin_out / artifact_path
            if artifact_path.is_file():
                artifact_sha = _sha(artifact_path)
                source_ids = []
                plugin_recipe = args.get("recipe") if isinstance(args.get("recipe"), Mapping) else {}
                source_candidates = [
                    args.get("solute"), args.get("initial_structure"), args.get("final_structure"),
                    plugin_recipe.get("solute"), *(plugin_recipe.get("solvents") or []),
                ]
                for source_value in source_candidates:
                    if isinstance(source_value, Mapping) and source_value.get("artifact_id"):
                        source_ids.append(str(source_value["artifact_id"]))
                if data_analysis_api is not None:
                    registered = data_analysis_api.register_derived_artifact(
                        registry_root, str(artifact_path), source_artifact_ids=source_ids,
                        format_id="extxyz", provenance={
                            "plugin": operation, "plugin_status": raw_status,
                            "not_equilibrated": model_plugin_result.get("equilibration_status") == "PACKED_NOT_EQUILIBRATED",
                            "not_transition_state": raw_status == "INITIAL_PATH_READY_FOR_REVIEW",
                        },
                    )
                    if str(registered.get("sha256", "")).lower() != artifact_sha.lower() or not registered.get("artifact_id"):
                        raise ValueError("Data_analysis registration did not preserve the generated structure Artifact SHA")
                    structure_ref = {"artifact_id": str(registered["artifact_id"]), "sha256": artifact_sha}
                    resolved_path = Path(data_analysis_api.resolve_artifact_path(registry_root, structure_ref["artifact_id"])).resolve(strict=True)
                    if _sha(resolved_path) != artifact_sha:
                        raise ValueError("resolved generated Artifact bytes failed SHA-256 verification")
                    structure_path = str(resolved_path)
                    artifact_ref = {"artifact_id": structure_ref["artifact_id"], "sha256": artifact_sha,
                                    "artifact_sha256": artifact_sha, "source_system": "Data_analysis",
                                    "verified": True, "uri": resolved_path.as_uri()}
                    structure_mapping = MODEL_PLUGIN_REGISTRY.invoke(
                        "load_structure_model",
                        {"source": {
                            "path": str(resolved_path), "sha256": artifact_sha,
                            "artifact_id": structure_ref["artifact_id"], "artifact_sha256": artifact_sha,
                        }},
                    )
                    structure_mapping.setdefault("source", {}).update({
                        "artifact_id": structure_ref["artifact_id"], "artifact_sha256": artifact_sha,
                        "path": str(resolved_path), "sha256": artifact_sha,
                    })
                else:
                    readiness_gaps.append(evidence_gap(
                        "DATA_ANALYSIS_ARTIFACT_REGISTRATION_REQUIRED", "model.structure_plugin.artifact",
                        "Generated structures must be registered and hash-verified by the existing Data_analysis Artifact API.",
                        "Configure the existing Data_analysis integration to register this generated structure.", all_refs,
                    ))
        # IDPP is a reviewable initial path only. Capability routing below
        # retains PLANNABLE_ONLY; it never becomes an executable NEB task.
    elif not operation and review_complete:
        structure_mapping, structure_path, artifact_ref, structure_gaps = _resolve_structure(
            model_config, data_analysis_api, run_root, data_analysis_project_root,
        )
        readiness_gaps.extend(structure_gaps)
    elif not review_complete:
        readiness_gaps.append(evidence_gap(
            "EVIDENCE_REVIEW_INCOMPLETE", "project_run.EVIDENCE_REVIEW",
            "Structure loading/construction is not allowed before Manifest evidence confirmation is complete.",
            "Complete the Project Run Evidence Review before creating or loading a model structure.",
            all_refs,
        ))

    if artifact_ref:
        artifact_evidence_id = "artifact-" + str(artifact_ref["sha256"])[:16]
        if not any(item.get("evidence_id") == artifact_evidence_id for item in all_refs):
            all_refs.append({
                "evidence_id": artifact_evidence_id,
                "source_type": "artifact",
                "source_uri": str(structure_path or ""),
                "source_sha256": str(artifact_ref["sha256"]),
                "locator": {"kind": "file", "value": artifact_evidence_id},
                "scope": "hash-verified Data_analysis structure Artifact",
            })
    if structure_mapping is not None:
        model_recipe, model_gaps = compile_model_recipe(
        config, structure_mapping, all_refs, upstream, plugin_result=model_plugin_result,
    )
    else:
        model_recipe, model_gaps = compile_model_recipe(config, None, all_refs, upstream)
    if artifact_ref:
        raw_cell = structure_mapping.get("cell_angstrom")
        cell_parameters = None
        try:
            from ase.cell import Cell
            parameters = Cell(raw_cell).cellpar()
            if all(float(value) > 0 for value in parameters[:3]):
                cell_parameters = {
                    "a": float(parameters[0]), "b": float(parameters[1]), "c": float(parameters[2]),
                    "alpha": float(parameters[3]), "beta": float(parameters[4]), "gamma": float(parameters[5]),
                }
        except Exception:
            cell_parameters = None
        model_recipe["validation_contract"] = {
            **dict(model_recipe.get("validation_contract") or {}),
            "status": "SOURCE_STRUCTURE_HASH_VERIFIED",
            "artifact_ref": artifact_ref,
            "atom_count": structure_mapping.get("atom_count") if structure_mapping else None,
            "plugin_status": (model_plugin_result or {}).get("status") or "STRUCTURE_LOADED",
            "equilibration_status": (model_plugin_result or {}).get("equilibration_status"),
            "cell": cell_parameters,
            "cell_source_ref": "artifact-" + str(artifact_ref["sha256"])[:16],
            "scientific_model_acceptance": "REQUIRES_EXPLICIT_USER_APPROVAL",
        }
        prior_metadata = model_recipe["planning_metadata"]
        model_recipe = seal_object(
            model_recipe, object_type="ModelRecipe", id_field="recipe_id", prefix="model",
            status=prior_metadata["planning_status"],
            source_evidence_refs=prior_metadata["source_evidence_refs"],
            upstream_sha256s=prior_metadata["upstream_sha256s"],
            selection_records=prior_metadata["selection_records"],
            missing_items=prior_metadata["missing_items"],
        )
    readiness_gaps.extend(model_gaps)
    model_status = "BLOCKED" if model_gaps or not artifact_ref else "READY"

    method_config = dict(config.get("method") or {})
    method_sources = _method_sources(method_config, manifest, profile_ref, structure_mapping)
    task_type = str(config.get("task_type") or "")
    engine_request = _engine_request(
        config, structure_mapping, method_sources,
        runtime_verified_version=runtime_verified_version,
    )
    if not engine_request["execution_backend_registered"]:
        backend_error = (
            f"Execution backend {engine_request.get('execution_backend')!r} is not registered; "
            "supported Planning Core backends are 'mock' and 'cp2k'."
        )
        readiness_gaps.append(evidence_gap(
            "EXECUTION_BACKEND_UNREGISTERED", "execution.backend",
            backend_error,
            "Select a registered backend id ('mock' or 'cp2k'); no backend will be inferred.",
            all_refs,
        ))
        engine_result = {
            "capability_route": {
                "engine": engine_request["engine"] or None,
                "task_type": task_type or None,
                "execution_mode": "blocked",
                "software_supported": False,
                "integration_status": "UNSUPPORTED_BACKEND",
                "allows_real_execution_plan": False,
                "can_enter_real_preflight": False,
                "capability_ids": [],
                "blockers": [backend_error],
            },
            "method_plan": {
                "engine": engine_request["engine"] or None,
                "task_type": task_type or None,
                "execution_mode": "blocked",
                "status": "BLOCKED_UNREGISTERED_EXECUTION_BACKEND",
                "fields": {}, "missing_fields": [], "proposed_fields": [],
                "conflicting_fields": [], "blockers": [backend_error],
                "ready_for_core_compilation": False,
                "parameter_defaults_applied": False,
            },
            "resource_plan": {
                "status": "BLOCKED_UNREGISTERED_EXECUTION_BACKEND",
                "values": {}, "missing_profile_fields": [], "blockers": [backend_error],
            },
            "qc_contract": {"status": "UNREGISTERED_QC_CONTRACT", "checks": []},
        }
    elif not engine_request["engine"] or not task_type:
        readiness_gaps.append(evidence_gap(
            "ENGINE_TASK_TYPE_MISSING", "method_plan.engine/task_type",
            "A calculation engine and task type must be explicitly selected.",
            "Which registered engine and calculation task type should be planned?", all_refs,
        ))
        engine_result = {
            "capability_route": {"integration_status": "UNVERIFIED", "blockers": ["engine/task missing"]},
            "method_plan": {"fields": {}, "missing_fields": [], "ready_for_core_compilation": False,
                            "blockers": ["engine/task missing"]},
            "resource_plan": {"status": "BLOCKED_MISSING_RESOURCE_PROFILE", "blockers": ["engine/task missing"]},
            "qc_contract": {"status": "UNREGISTERED_QC_CONTRACT", "checks": []},
        }
    else:
        engine_result = engine_planning(engine_request)
    route = engine_result["capability_route"]
    method_raw = engine_result["method_plan"]
    resource_raw = engine_result["resource_plan"]
    qc_raw = engine_result["qc_contract"]
    method_decisions, method_gaps = _method_decisions(method_raw, all_refs)
    # Existing CalculationPlan v1.0 requires these exact source-backed fields.
    # Check the runtime projection contract now, so a MethodPlan cannot be READY
    # while one of its required CP2K fields is absent or merely proposed.
    required_runtime_fields = [
        "xc_functional", "basis_set", "pseudopotential", "basis_file_name",
        "potential_file_name", "kind_definitions", "cutoff_ry", "rel_cutoff_ry",
        "scf.method", "scf.eps_scf", "scf.max_scf", "charge", "multiplicity",
        "uks", "cell_periodicity", "poisson_periodicity", "poisson_solver",
        "center_coordinates", "software_version",
    ]
    raw_fields = method_raw.get("fields") or {}
    known_method_source_ids = {str(item.get("evidence_id")) for item in all_refs if item.get("evidence_id")}
    # Agent A uses this internal identifier for the versioned CP2K registry rule.
    if engine_request.get("engine") and route.get("capability_ids"):
        known_method_source_ids.add("registry:" + str(engine_request["engine"]).casefold())

    def flatten_field_records(prefix: str, value: Any) -> dict[str, Mapping[str, Any]]:
        flattened: dict[str, Mapping[str, Any]] = {}
        if not isinstance(value, Mapping):
            return flattened
        if "value" in value:
            flattened[prefix] = value
            return flattened
        for child_name, child in value.items():
            path = f"{prefix}.{child_name}" if prefix else str(child_name)
            flattened.update(flatten_field_records(path, child))
        return flattened

    flat_raw_fields = flatten_field_records("", raw_fields)
    for field_name, field_record in flat_raw_fields.items():
        field_status = str(field_record.get("status") or "").upper()
        if field_status in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE"}:
            field_source = str(field_record.get("source_ref") or "")
            if not field_source or field_source not in known_method_source_ids:
                method_gaps.append(evidence_gap(
                    "METHOD_SOURCE_REFERENCE_UNRESOLVED",
                    "MethodPlan.parameters." + str(field_name),
                    "Agent A selected a parameter value but its source_ref does not resolve to a hash-pinned EvidenceRef in this Project Run.",
                    f"Attach a verified source reference for the selected method parameter {field_name}.",
                    all_refs,
                ))
    for field_name in required_runtime_fields:
        value = flat_raw_fields.get(field_name)
        if not isinstance(value, Mapping) or str(value.get("status") or "").upper() not in {
            "SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE", "NOT_APPLICABLE"
        } or value.get("approval_required") is True or (
            value.get("value") is None and str(value.get("status") or "").upper() != "NOT_APPLICABLE"
        ):
            if not any(item.get("field_path") == "MethodPlan.parameters." + field_name for item in method_gaps):
                method_gaps.append(evidence_gap(
                    "CALCULATION_PLAN_FIELD_UNRESOLVED",
                    "MethodPlan.parameters." + field_name,
                    "The existing CalculationPlan v1.0 contract requires this exact field with explicit provenance; no value is inferred.",
                    f"Provide an authorized source for the CP2K field {field_name}.", all_refs,
                ))
    readiness_gaps.extend(method_gaps)
    method_source_refs = _source_refs_for_method(method_raw.get("fields") or {}, all_refs)
    mock_execution = str((config.get("execution") or {}).get("backend") or "").casefold() == "mock"
    method_fields_resolved = (
        not method_raw.get("missing_fields")
        and not method_raw.get("proposed_fields")
        and not method_raw.get("conflicting_fields")
        and not method_gaps
    )
    software_record = flat_raw_fields.get("software_version") or {}
    software_source_backed = (
        str(software_record.get("status") or "").upper()
        in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE"}
        and bool(str(software_record.get("source_ref") or "").strip())
        and bool(str(software_record.get("provenance") or "").strip())
        and str(software_record.get("source_ref") or "") in known_method_source_ids
    )
    if mock_execution and not software_source_backed:
        method_gaps.append(evidence_gap(
            "MOCK_METHOD_SOFTWARE_VERSION_SOURCE_MISSING",
            "MethodPlan.parameters.software_version",
            "Mock-only planning may proceed only when the declared CP2K version is bound to a resolved source record.",
            "Supply an exact source-backed CP2K software version; request metadata alone is insufficient.",
            all_refs,
        ))
    method_fields_resolved = method_fields_resolved and software_source_backed
    method_planning_status = "READY" if (
        method_raw.get("ready_for_core_compilation") is True
        and method_fields_resolved
        and not method_gaps
    ) else (
        "NEEDS_DECISION" if method_raw.get("proposed_fields") or method_raw.get("conflicting_fields")
        else "BLOCKED"
    )
    route_status = str(route.get("integration_status") or "").upper()
    if route_status == "NOT_INTEGRATED":
        method_planning_status = "UNSUPPORTED"
    elif route_status == "PLANNABLE_ONLY" and method_planning_status == "READY":
        method_planning_status = "PLANNABLE_ONLY"
    method_plan_body = method_plan_object(
        method_raw=method_raw, route=route, engine_request=engine_request,
        method_source_refs=method_source_refs, all_refs=all_refs,
        structure_mapping=structure_mapping, artifact_ref=artifact_ref,
        overall_status=method_planning_status, method_gaps=method_gaps,
        selection_records=method_decisions,
    )
    method_plan = seal_object(
        method_plan_body, object_type="MethodPlan", id_field="method_plan_id", prefix="method",
        status=method_planning_status, source_evidence_refs=method_plan_body["source_evidence_refs"],
        upstream_sha256s=upstream, selection_records=method_decisions, missing_items=method_gaps,
    )

    execution_cfg = config.get("execution") or {}
    resource_cfg = execution_cfg.get("resource_profile") or {}
    resource_profile = build_resource_profile(
        resource_raw, structure_mapping=structure_mapping, model_config=model_config,
        task_type=task_type, refs=all_refs, resource_source_ref=resource_source_ref,
        resource_config=resource_cfg,
    )
    mock_execution = str(execution_cfg.get("backend") or "").casefold() == "mock"
    resource_profile_status = str(resource_profile.get("status") or "").upper()
    resource_status = "READY" if (
        resource_profile_status == "READY"
        or (mock_execution and resource_profile_status == "MOCK_ONLY"
            and resource_profile.get("mock_only") is True
            and resource_profile.get("real_execution_preflight_allowed") is False)
    ) else "BLOCKED"
    resource_gaps = []
    for name, decision in resource_profile.get("values", {}).items():
        if decision.get("status") == "MISSING":
            resource_gaps.append(evidence_gap(
                "RESOURCE_PROFILE_FIELD_MISSING",
                "execution_plan.resource_profile.values." + str(name),
                str(decision.get("rationale") or "Resource Planner did not resolve this field."),
                f"Provide a verified source-backed resource value for {name}.",
                decision.get("source_evidence_refs", all_refs),
            ))
    for missing in resource_raw.get("missing_profile_fields", []):
        resource_gaps.append(evidence_gap(
            "RESOURCE_PROFILE_FIELD_MISSING", "execution_plan.resource_profile.values." + str(missing),
            "Agent A ResourcePlanner requires this explicit scheduler allocation field.",
            f"Provide the verified resource profile field {missing}.", all_refs,
        ))
    readiness_gaps.extend(resource_gaps)

    execution_mode = str(execution_cfg.get("backend") or "").casefold()
    route_status = str(route.get("integration_status") or "UNVERIFIED").upper()
    if route_status == "PLANNABLE_ONLY":
        execution_status = "PLANNABLE_ONLY"
    elif route_status == "NOT_INTEGRATED":
        execution_status = "UNSUPPORTED"
    elif model_plugin_result and model_plugin_result.get("equilibration_status") == "PACKED_NOT_EQUILIBRATED":
        execution_status = "PLANNABLE_ONLY"
    elif route_status == "AVAILABLE" and resource_status == "READY" and execution_mode == "mock":
        execution_status = "READY"
    elif route_status == "AVAILABLE" and resource_status == "READY" and execution_mode == "cp2k" and route.get("can_enter_real_preflight") is True:
        # This Planning Core CLI does not dispatch real work. It records the
        # existing Real adapter only as a planning/preflight capability.
        execution_status = "PLANNABLE_ONLY"
    else:
        execution_status = "BLOCKED"
    runtime_calculations = (config.get("runtime") or {}).get("calculations") or []
    task_nodes = []
    artifact_input_refs = [
        {"object_type": "DataAnalysisArtifact", "object_id": item["object_id"],
         "schema_version": item["schema_version"], "sha256": item["sha256"]}
        for item in model_recipe.get("input_artifact_refs", [])
    ]
    for index, item in enumerate(runtime_calculations):
        if not isinstance(item, Mapping):
            continue
        task_id = str(item.get("id") or f"task-{index + 1:03d}")
        explicit_dependencies = item.get("depends_on")
        depends = list(explicit_dependencies) if isinstance(explicit_dependencies, list) else []
        output_files = item.get("output_files") or {}
        task_nodes.append({
            "task_id": task_id,
            "plugin_id": "pipeline_contracts.workflow",
            "plugin_version": "1.0.0",
            "operation_id": str(item.get("operation") or ""),
            "depends_on": depends,
            "input_refs": artifact_input_refs,
            "output_contracts": [str(value) for value in output_files.values() if value],
            "resource_profile_ref": (
                "MOCK_ONLY_NOT_APPLICABLE" if execution_mode == "mock"
                else (resource_source_ref or "UNRESOLVED_RESOURCE_PROFILE")
            ),
            "preflight_requirements": (
                ["explicit_user_model_approval", "source_complete_method_plan",
                 "mock_execution_only_no_real_preflight"]
                if execution_mode == "mock" else
                ["explicit_user_model_approval", "source_complete_method_plan",
                 "runtime_version_preflight", "resource_profile_verified"]
            ),
        })
    real_chain = (
        task_type.casefold() == "cp2k.geo_opt"
        and {"cp2k.geo_opt", "cp2k.energy"}.issubset({
            str(item.get("operation") or "").casefold()
            for item in runtime_calculations if isinstance(item, Mapping)
        })
    )
    backend = None
    if execution_status == "READY" and execution_mode == "mock":
        backend = {
            "backend_id": "mock",
            "adapter_id": "pipeline_contracts.workflow.MockCP2KWorkflowAdapter",
            "adapter_version": "1.0.0",
        }
    elif execution_status in {"READY", "PLANNABLE_ONLY"} and execution_mode == "cp2k" and route.get("can_enter_real_preflight") is True and real_chain:
        backend = {
            "backend_id": "cp2k",
            "adapter_id": "pipeline_contracts.real_workflow.RealCP2KWorkflowAdapter",
            "adapter_version": "1.0.0",
        }
    agent_execution_mode = agent_a_execution_mode(execution_cfg.get("backend"))
    execution_body = {
        "schema_version": PLANNING_SCHEMA_VERSION, "execution_plan_id": "",
        "backend": backend,
        **planning_mode_fields(execution_cfg.get("backend")),
        "real_execution_preflight_allowed": (
            bool(route.get("can_enter_real_preflight"))
            if agent_execution_mode == "real" else False
        ),
        "task_nodes": task_nodes,
        "resource_profile": resource_profile,
        "preflight_requirements": (
            ["explicit_user_model_approval", "method_parameter_provenance_complete",
             "mock_execution_only_no_real_preflight"]
            if execution_mode == "mock" else
            ["explicit_user_model_approval", "method_parameter_provenance_complete",
             "runtime_version_verification_before_real_execution", "verified_resource_profile",
             "adapter_scope_check"]
        ),
        "source_evidence_refs": all_refs,
        "decision_records": [], "evidence_gaps": resource_gaps,
        "status": "READY_FOR_REVIEW" if execution_status == "READY" else (
            "DRAFT" if execution_status == "PLANNABLE_ONLY" else "BLOCKED"),
        "provenance": {
            "source_evidence_refs": all_refs,
            "generated_by": {"component_id": "pipeline.resource_execution_planner", "version": PLANNING_SCHEMA_VERSION},
            "transform_sha256": canonical_sha256(resource_raw),
        },
    }
    execution_plan = seal_object(
        execution_body, object_type="ExecutionPlan", id_field="execution_plan_id", prefix="execution",
        status=execution_status, source_evidence_refs=all_refs, upstream_sha256s={
            **upstream, "method_plan": method_plan["planning_metadata"]["object_sha256"],
            "model_recipe": model_recipe["planning_metadata"]["object_sha256"],
        }, missing_items=resource_gaps,
    )

    qc_contract_status = str(qc_raw.get("status") or "").upper()
    qc_gates = build_qc_gates(qc_raw)
    qc_status = "READY" if qc_contract_status == "REGISTERED" and qc_gates else "UNSUPPORTED"
    qc_token = _qc_type(task_type).upper()
    qc_task_type = {
        "GEO_OPT": "GEO_OPT",
        "ENERGY_SCF": "ENERGY_SCF",
        "FREQUENCY": "FREQUENCY",
        "NEB_BAND_DIMER": "NEB",
        "DIMER": "DIMER",
        "TRANSITION_STATE": "TRANSITION_STATE",
        "AIMD": "AIMD",
        "EXPLICIT_SOLVENT_PREPARATION": "EXPLICIT_SOLVENT_PREPARATION",
        "ELECTRONIC_STRUCTURE_ANALYSIS": "ELECTRONIC_STRUCTURE_ANALYSIS",
    }.get(qc_token, "GEO_OPT")
    qc_body = {
        "schema_version": PLANNING_SCHEMA_VERSION, "qc_plan_id": "",
        "task_type": qc_task_type,
        "gates": qc_gates,
        "acceptance_policy": {
            "scientific_validity_owner": "human scientific reviewer",
            "user_acceptance_required": True,
        },
        "source_evidence_refs": all_refs,
        "status": "READY" if qc_status == "READY" else "BLOCKED",
        "provenance": {
            "source_evidence_refs": all_refs,
            "generated_by": {"component_id": "pipeline.task_qc_contract_adapter", "version": PLANNING_SCHEMA_VERSION},
            "transform_sha256": canonical_sha256(qc_raw),
        },
    }
    qc_plan = seal_object(
        qc_body, object_type="QCPlan", id_field="qc_plan_id", prefix="qc",
        status=qc_status, source_evidence_refs=all_refs,
        upstream_sha256s={"execution_plan": execution_plan["planning_metadata"]["object_sha256"]},
        missing_items=[] if qc_status == "READY" else [evidence_gap(
            "QC_CONTRACT_UNSUPPORTED", "qc_plan.task_type",
            "Agent A has no registered QC contract for this task type.",
            "Add or select a supported task-specific QC contract.", all_refs,
        )],
    )

    if not review_complete:
        overall = "BLOCKED"
    else:
        overall = aggregate_status(
            intent["planning_metadata"]["planning_status"],
            research["planning_metadata"]["planning_status"],
            model_recipe["planning_metadata"]["planning_status"],
            method_plan["planning_metadata"]["planning_status"],
            execution_plan["planning_metadata"]["planning_status"],
            qc_plan["planning_metadata"]["planning_status"],
            has_gaps=bool(readiness_gaps),
            has_proposals=bool(method_raw.get("proposed_fields") or method_raw.get("conflicting_fields")),
        )
    # A validated initial solvent box is not equilibrated; an IDPP path is not a TS.
    if model_plugin_result:
        raw_status = str(model_plugin_result.get("status") or "").upper()
        if raw_status == "INITIAL_PATH_READY_FOR_REVIEW":
            overall = "PLANNABLE_ONLY" if not readiness_gaps else "BLOCKED"
        if model_plugin_result.get("equilibration_status") == "PACKED_NOT_EQUILIBRATED":
            overall = "PLANNABLE_ONLY" if not readiness_gaps else "BLOCKED"


    base_bundle = {
        "bundle_schema_version": PLANNING_SCHEMA_VERSION,
        "status": "BLOCKED" if overall in {"BLOCKED", "NEEDS_DECISION", "UNSUPPORTED"} else "READY_FOR_REVIEW",
        "scientific_intent": intent, "research_plan": research,
        "model_recipes": [model_recipe], "method_plan": method_plan,
        "execution_plan": execution_plan, "qc_plan": qc_plan,
    }
    bundle = seal_object(
        base_bundle, object_type="PlanningBundle", id_field="bundle_id", prefix="bundle",
        status=overall, source_evidence_refs=all_refs,
        upstream_sha256s={
            "scientific_intent": intent["planning_metadata"]["object_sha256"],
            "research_plan": research["planning_metadata"]["object_sha256"],
            "model_recipe": model_recipe["planning_metadata"]["object_sha256"],
            "method_plan": method_plan["planning_metadata"]["object_sha256"],
            "execution_plan": execution_plan["planning_metadata"]["object_sha256"],
            "qc_plan": qc_plan["planning_metadata"]["object_sha256"],
        }, selection_records=method_decisions, missing_items=readiness_gaps,
    )
    validate_bundle(bundle)

    bundle_id = bundle["bundle_id"]
    generate_stage = pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")
    previous_bundle_sha = (generate_stage.get("outputs") or {}).get("planning_bundle_sha256")
    if previous_bundle_sha and previous_bundle_sha != bundle["planning_metadata"]["object_sha256"]:
        raise FileExistsError(
            "this Project Run already references a different frozen Scientific Planning Bundle; "
            "a changed Manifest/Profile/Artifact requires a new Project Run"
        )
    out_dir = run_root / "scientific_planning" / bundle_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_immutable_json(out_dir / "scientific_intent.json", intent)
    write_immutable_json(out_dir / "research_plan.json", research)
    write_immutable_json(out_dir / "model_recipe.json", model_recipe)
    write_immutable_json(out_dir / "method_plan.json", method_plan)
    write_immutable_json(out_dir / "execution_plan.json", execution_plan)
    write_immutable_json(out_dir / "qc_plan.json", qc_plan)
    write_immutable_json(out_dir / "planning_bundle.json", bundle)
    index = object_index(bundle)
    index["bundle"] = {
        "object_id": bundle_id, "schema_version": bundle["bundle_schema_version"],
        "sha256": bundle["planning_metadata"]["object_sha256"],
        "planning_status": overall,
        "source_evidence_refs": all_refs,
        "upstream_sha256s": bundle["planning_metadata"]["upstream_sha256s"],
        "selection_records": method_decisions, "missing_items": readiness_gaps,
    }
    write_immutable_json(out_dir / "planning_index.json", index)
    context = {
        "schema_version": PLANNING_SCHEMA_VERSION, "project_run_id": run_id,
        "project_id": project_id, "project_profile_path": resolved_profile_path,
        "project_profile_sha256": profile_sha, "planning_config": config,
        "runtime_verified_version": runtime_verified_version,
        "input_fingerprint": input_fingerprint,
        "data_analysis_project_root": str(data_analysis_project_root or (run_root / "model_candidates")),
        "structure_path": structure_path, "artifact_ref": artifact_ref,
        "model_plugin_result": model_plugin_result,
        "runtime_config": deepcopy(config.get("runtime") or {}),
        "runtime_execution": deepcopy(config.get("execution") or {}),
    }
    write_immutable_json(out_dir / "planner_context.json", context)

    # Prepare the existing ProjectLifecycle stages for a human model approval.
    current_generate_status = pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")["status"]
    if review_complete and overall in {"READY", "PLANNABLE_ONLY"} and structure_path and artifact_ref:
        candidate_id = "candidate-" + model_recipe["planning_metadata"]["object_sha256"][:16]
        candidate_result = {
            "candidate_id": candidate_id, "structure_path": structure_path,
            "artifact_id": artifact_ref["artifact_id"],
            "structure_sha256": artifact_ref["sha256"],
            "artifact_ref": artifact_ref,
            "validation_report": {
                "status": "PASS",
                "structure_sha256": artifact_ref["sha256"],
                "validation_scope": "source bytes and structure parser integrity only",
                "scientific_validity": "requires human review",
            },
        }
        pipeline_result = {
            "planning_mode": "scientific_planning_core",
            "status": "AWAITING_APPROVAL",
            "candidate_results": [candidate_result],
            "review_package": {
                "review_status": "PENDING", "candidate": candidate_result,
                "model_recipe_sha256": model_recipe["planning_metadata"]["object_sha256"],
                "explicit_user_approval_required": True,
            },
        }
        result_path = out_dir / "model_pipeline_result.json"
        write_immutable_json(result_path, pipeline_result)
        if current_generate_status in {"PENDING", "BLOCKED"}:
            outputs = {
                "planning_mode": "scientific_planning_core",
                "planning_bundle_path": str(out_dir / "planning_bundle.json"),
                "planning_bundle_sha256": bundle["planning_metadata"]["object_sha256"],
                "planner_context_path": str(out_dir / "planner_context.json"),
                "pipeline_result": str(result_path), "candidate_id": candidate_id,
                "model_recipe_sha256": model_recipe["planning_metadata"]["object_sha256"],
            }
            pipeline.lifecycle.transition(run_id, "MODEL_GENERATE", "COMPLETED", outputs=outputs)
            if pipeline.lifecycle.stage(run_id, "MODEL_VALIDATE")["status"] == "PENDING":
                pipeline.lifecycle.transition(run_id, "MODEL_VALIDATE", "COMPLETED",
                    outputs={"source_artifact_id": artifact_ref["artifact_id"],
                             "source_structure_sha256": artifact_ref["sha256"]})
            if pipeline.lifecycle.stage(run_id, "MODEL_REVIEW")["status"] == "PENDING":
                pipeline.lifecycle.transition(run_id, "MODEL_REVIEW", "COMPLETED",
                    outputs={"review_package": pipeline_result["review_package"],
                             "model_recipe_path": str(out_dir / "model_recipe.json")})
            if pipeline.lifecycle.stage(run_id, "MODEL_APPROVAL")["status"] == "PENDING":
                pipeline.lifecycle.transition(run_id, "MODEL_APPROVAL", "AWAITING_APPROVAL",
                                               outputs=outputs)
    elif review_complete and current_generate_status == "PENDING":
        pipeline.lifecycle.transition(
            run_id, "MODEL_GENERATE", "BLOCKED",
            outputs={"planning_bundle_path": str(out_dir / "planning_bundle.json"),
                     "planning_bundle_sha256": bundle["planning_metadata"]["object_sha256"],
                     "planning_status": overall, "missing_items": readiness_gaps},
            error=f"Scientific Planning Core status is {overall}; no ModelSpec/CalculationPlan/WorkflowRun was created.",
        )

    candidate_id = None
    candidate_pipeline_path = pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")["outputs"].get("pipeline_result")
    if candidate_pipeline_path and Path(candidate_pipeline_path).is_file():
        candidate_pipeline = json.loads(Path(candidate_pipeline_path).read_text(encoding="utf-8"))
        candidate_id = (candidate_pipeline.get("candidate_results") or [{}])[0].get("candidate_id")
    return {
        "project_run_id": run_id, "bundle_id": bundle_id, "planning_status": overall,
        "candidate_id": candidate_id,
        "bundle_sha256": bundle["planning_metadata"]["object_sha256"],
        "planning_directory": str(out_dir),
        "files": {name: str(out_dir / name) for name in (
            "scientific_intent.json", "research_plan.json", "model_recipe.json",
            "method_plan.json", "execution_plan.json", "qc_plan.json",
            "planning_bundle.json", "planning_index.json", "planner_context.json")},
        "missing_items": readiness_gaps,
        "questions": [item["minimum_question"] for item in readiness_gaps],
        "model_plugin_status": (model_plugin_result or {}).get("status"),
        "workflow_created": False,
        "calculation_plan_created": False,
        "method_status": method_plan["planning_metadata"]["planning_status"],
        "execution_status": execution_plan["planning_metadata"]["planning_status"],
        "resource_profile_status": resource_raw.get("status"),
        "qc_status": qc_plan["planning_metadata"]["planning_status"],
    }
