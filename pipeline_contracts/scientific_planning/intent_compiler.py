"""Compile confirmed Project Run evidence into schema-defined Intent and ModelRecipe."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from typing import Any, Mapping

from .bundle import seal_object
from .contracts import PLANNING_SCHEMA_VERSION
from .decision_policy import evidence_gap

_TASK_FAMILIES = {"STRUCTURE", "THERMODYNAMICS", "ELECTRONIC_STRUCTURE", "VIBRATIONAL",
                  "REACTION_PATH", "DYNAMICS", "SOLVATION", "ANALYSIS"}
_MODEL_TYPES = {"MOLECULE", "CONFORMER", "CRYSTAL", "SURFACE", "SLAB", "ADSORPTION",
                "INTERFACE", "EXPLICIT_SOLVENT", "IMPLICIT_SOLVATION_CONTEXT", "TRANSITION_STATE_PATH"}


def evidence_refs(manifest: Mapping[str, Any]) -> list[dict]:
    document = manifest.get("source_document") or {}
    digest = str(document.get("sha256") or "")
    if len(digest) != 64:
        return []
    confirmed_ids = {
        str(evidence_id)
        for confirmation in manifest.get("confirmations", [])
        for evidence_id in confirmation.get("evidence_ids", [])
    }
    refs = []
    for item in manifest.get("evidence", []):
        evidence_id = item.get("evidence_id")
        if not evidence_id or str(evidence_id) not in confirmed_ids:
            continue
        source_location = item.get("source") if isinstance(item.get("source"), Mapping) else {}
        part = str(source_location.get("part") or "word/document.xml")
        if source_location.get("paragraph") is not None:
            kind = "paragraph"
            value = f"{part}#paragraph={source_location['paragraph']}"
        elif source_location.get("table") is not None:
            kind = "table"
            value = (
                f"{part}#table={source_location['table']}"
                f";row={source_location.get('row', '?')};column={source_location.get('column', '?')}"
            )
        elif item.get("page") is not None:
            kind, value = "page", str(item["page"])
        else:
            kind = str(item.get("kind") or "other").casefold()
            if kind not in {"page", "section", "paragraph", "table", "figure", "record", "file", "uri", "fixture", "other"}:
                kind = "other"
            value = str(evidence_id)
        notes = "confirmed " + str(item.get("block_kind") or item.get("kind") or "source block")
        refs.append({
            "evidence_id": str(evidence_id), "source_type": "document",
            "source_uri": str(document.get("file_name") or "frozen-source-document"),
            "source_sha256": digest,
            "locator": {"kind": kind, "value": value},
            "scope": "confirmed frozen Project Run evidence",
            "notes": notes,
        })
    if not refs:
        file_name = str(document.get("file_name") or "frozen-source-document")
        refs.append({
            "evidence_id": "source-document-" + digest[:16],
            "source_type": "document",
            "source_uri": file_name,
            "source_sha256": digest,
            "locator": {"kind": "file", "value": file_name},
            "scope": "hash-pinned source document; no extracted claim was treated as confirmed",
            "notes": "Document-level source pointer only; does not assert any scientific content.",
        })
    return refs


def _provenance(refs: list[dict], transform_sha: str, component_id: str) -> dict:
    return {
        "source_evidence_refs": deepcopy(refs),
        "generated_by": {"component_id": component_id, "version": PLANNING_SCHEMA_VERSION},
        "transform_sha256": transform_sha if len(transform_sha) == 64 else "0" * 64,
    }


def compile_intent(project_id: str, manifest: Mapping[str, Any], config: Mapping[str, Any],
                   refs: list[dict]) -> tuple[dict, list[dict]]:
    intent_cfg = config.get("intent") or {}
    gaps: list[dict] = []
    question = intent_cfg.get("research_question")
    if not isinstance(question, str) or not question.strip():
        gaps.append(evidence_gap("RESEARCH_QUESTION_MISSING", "scientific_intent.research_question",
            "A research question is a user scientific decision target and cannot be invented from a project title.",
            "What exact scientific question should this Project Run answer?", refs))
        question = "UNRESOLVED: research question required"

    raw_goal = intent_cfg.get("research_goal") or {}
    goal = {}
    for field in ("research_object", "comparison", "target_conclusion"):
        value = raw_goal.get(field) if isinstance(raw_goal, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            gaps.append(evidence_gap("RESEARCH_GOAL_FIELD_MISSING", f"scientific_intent.research_goal.{field}",
                f"The explicit research_goal.{field} is required for scientific planning.",
                f"Provide the intended {field.replace('_', ' ')}.", refs))
            value = "UNRESOLVED"
        goal[field] = value
    observables = intent_cfg.get("requested_observables")
    if not isinstance(observables, list) or not observables:
        gaps.append(evidence_gap("OBSERVABLES_MISSING", "scientific_intent.requested_observables",
            "No explicit success observable has been declared.",
            "Which observable(s) must be calculated or compared?", refs))
        observables = ["UNRESOLVED: required success observable"]
    observables = [str(value) for value in observables if str(value).strip()]
    families = intent_cfg.get("requested_task_families")
    if not isinstance(families, list) or not families:
        gaps.append(evidence_gap("TASK_FAMILY_MISSING", "scientific_intent.requested_task_families",
            "A task family is required to construct a ResearchPlan DAG.",
            "Which scientific task family is required?", refs))
        families = []
    valid_families = []
    for index, family in enumerate(families):
        if family not in _TASK_FAMILIES:
            gaps.append(evidence_gap("TASK_FAMILY_UNSUPPORTED", f"scientific_intent.requested_task_families[{index}]",
                f"{family!r} is outside the approved task-family enumeration.",
                "Choose a task-family token from the declared ScientificIntent schema.", refs))
        else:
            valid_families.append(family)
    constraints = []
    for index, item in enumerate(intent_cfg.get("constraints") or []):
        if not isinstance(item, Mapping) or not all(item.get(key) for key in ("constraint_id", "description", "constraint_type")):
            gaps.append(evidence_gap("CONSTRAINT_INVALID", f"scientific_intent.constraints[{index}]",
                "Constraint records require explicit ID, description and type.",
                "Provide constraint_id, description and constraint_type.", refs))
            continue
        ctype = str(item["constraint_type"])
        if ctype not in {"REQUIRED", "PROHIBITED", "PREFERENCE", "BUDGET", "SCOPE"}:
            gaps.append(evidence_gap("CONSTRAINT_TYPE_UNSUPPORTED", f"scientific_intent.constraints[{index}].constraint_type",
                f"Unsupported constraint type {ctype!r}.", "Use REQUIRED, PROHIBITED, PREFERENCE, BUDGET or SCOPE.", refs))
            continue
        constraints.append({
            "constraint_id": str(item["constraint_id"]),
            "description": str(item["description"]),
            "constraint_type": ctype,
            "evidence_refs": deepcopy(item.get("evidence_refs") or refs),
        })
    gaps.extend(
        evidence_gap(str(item.get("code") or "MANIFEST_BLOCKER"),
                     str(item.get("field") or item.get("field_path") or "manifest"),
                     str(item.get("message") or "Manifest diagnostic blocks planning."),
                     "Resolve the cited Manifest definition before planning.",
                     [ref for ref in refs if ref["evidence_id"] in set(item.get("evidence_ids", []))])
        for item in manifest.get("diagnostics", []) if item.get("blocks_execution")
    )
    gaps.extend(
        evidence_gap("UNCONFIRMED_MANIFEST_DEFINITION", str(item.get("field") or "manifest.unresolved_definitions"),
                     "The extracted definition has not been confirmed.",
                     "Confirm or correct the cited source definition.",
                     [ref for ref in refs if ref["evidence_id"] in set(item.get("evidence_ids", []))])
        for item in manifest.get("unresolved_definitions", [])
    )
    if not refs:
        gaps.append(evidence_gap("SOURCE_EVIDENCE_MISSING", "scientific_intent.source_evidence_refs",
            "The frozen Project Run has no hash-pinned source evidence reference.",
            "Attach/confirm a source document before planning.", []))
    transform_sha = str((manifest.get("source_document") or {}).get("sha256") or "0" * 64)
    body = {
        "schema_version": PLANNING_SCHEMA_VERSION, "intent_id": "",
        "project_id": project_id, "research_question": question,
        "research_goal": goal, "requested_observables": observables,
        "requested_task_families": valid_families, "constraints": constraints,
        "source_evidence_refs": refs, "unresolved_questions": gaps,
        "status": "BLOCKED" if gaps else "READY_FOR_RESEARCH_PLANNING",
        "provenance": _provenance(refs, transform_sha, "pipeline.scientific_intent_compiler"),
    }
    intent = seal_object(body, object_type="ScientificIntent", id_field="intent_id", prefix="intent",
        status="BLOCKED" if gaps else "READY", source_evidence_refs=refs, missing_items=gaps)
    return intent, gaps


def compile_model_recipe(config: Mapping[str, Any], structure_mapping: Mapping[str, Any] | None,
                         refs: list[dict], upstream: Mapping[str, str],
                         plugin_result: Mapping[str, Any] | None = None) -> tuple[dict, list[dict]]:
    model_cfg = config.get("model") or {}
    gaps: list[dict] = []
    model_type = str(model_cfg.get("model_type") or "").upper()
    if model_type not in _MODEL_TYPES:
        gaps.append(evidence_gap("MODEL_TYPE_MISSING_OR_INVALID", "model_recipe.model_type",
            "The intended model family must be explicitly selected.",
            "Which model type is required?", refs))
        model_type = "MOLECULE"

    electronic_cfg = model_cfg.get("electronic_state") or {}
    electronic: dict[str, Any] = {}
    for name in ("charge", "multiplicity", "spin_label"):
        value = electronic_cfg.get(name) if isinstance(electronic_cfg, Mapping) else None
        valid = ((name == "charge" and isinstance(value, int) and not isinstance(value, bool))
                 or (name == "multiplicity" and isinstance(value, int) and not isinstance(value, bool) and value >= 1)
                 or (name == "spin_label" and isinstance(value, str) and bool(value.strip())))
        if not valid:
            gaps.append(evidence_gap("MODEL_ELECTRONIC_STATE_MISSING", f"model_recipe.electronic_state.{name}",
                f"{name} is decisive and cannot be inferred from geometry or composition.",
                f"What is the explicitly intended model {name}?", refs))
            electronic[name] = None
        else:
            electronic[name] = value

    target_cfg = model_cfg.get("target_definition") or {}
    target = {}
    for name in ("scientific_role", "model_origin"):
        value = target_cfg.get(name) if isinstance(target_cfg, Mapping) else None
        allowed_origin = {"SUPPLIED", "REPRODUCED", "DATABASE_DERIVED", "DESIGNED", "RECONSTRUCTED", "GENERATED"}
        valid = isinstance(value, str) and bool(value.strip())
        if name == "model_origin":
            valid = value in allowed_origin
        if not valid:
            gaps.append(evidence_gap("MODEL_TARGET_DEFINITION_MISSING", f"model_recipe.target_definition.{name}",
                f"Explicit target_definition.{name} is required.",
                f"Provide target_definition.{name}.", refs))
            target[name] = "UNRESOLVED" if name == "scientific_role" else "SUPPLIED"
        else:
            target[name] = value

    artifact_cfg = model_cfg.get("structure_artifact") or {}
    artifact_id = artifact_cfg.get("artifact_id") if isinstance(artifact_cfg, Mapping) else None
    artifact_sha = (artifact_cfg.get("sha256") or artifact_cfg.get("artifact_sha256")) if isinstance(artifact_cfg, Mapping) else None
    artifact_refs = []
    composition = model_cfg.get("composition")
    topology = model_cfg.get("topology")
    transform_sha = "0" * 64
    if structure_mapping is not None:
        symbols = structure_mapping.get("species") or []
        if symbols:
            composition = dict(sorted(Counter(symbols).items()))
        source = dict(structure_mapping.get("source") or {})
        # An explicit plugin output Artifact supersedes the original input selector.
        # It is bound only after Data_analysis registration and exact SHA verification.
        artifact_id = source.get("artifact_id") or artifact_id
        artifact_sha = source.get("artifact_sha256") or source.get("sha256") or artifact_sha
        transform_sha = str(artifact_sha or "0" * 64)
        if artifact_id and isinstance(artifact_sha, str) and len(artifact_sha) == 64:
            artifact_refs.append({"object_type": "DataAnalysisArtifact", "object_id": str(artifact_id),
                                  "schema_version": "1.0.0", "sha256": artifact_sha})
        else:
            gaps.append(evidence_gap("MODEL_ARTIFACT_ID_OR_SHA_MISSING", "model_recipe.input_artifact_refs",
                "A structure file without exact registered Artifact ID/SHA cannot be frozen.",
                "Provide the exact Data_analysis Artifact ID and SHA-256.", refs))
    else:
        gaps.append(evidence_gap("MODEL_ARTIFACT_MISSING", "model_recipe.input_artifact_refs",
            "No registered, SHA-verified structure Artifact was resolved.",
            "Provide a registered Data_analysis structure Artifact.", refs))

    if not isinstance(topology, Mapping) or not topology:
        gaps.append(evidence_gap("MODEL_TOPOLOGY_MISSING", "model_recipe.topology",
            "Coordinates/elements do not establish chemical connectivity or coordination topology.",
            "Provide the explicit atom/bond/coordination topology.", refs))
        topology = None
    if not isinstance(composition, Mapping) or not composition:
        gaps.append(evidence_gap("MODEL_COMPOSITION_MISSING", "model_recipe.composition",
            "A chemical composition is required and cannot be guessed.",
            "Provide model composition explicitly or through the verified structure Artifact.", refs))
        composition = None

    plugin_config = config.get("structure_plugin") or {}
    operation = plugin_config.get("operation") if isinstance(plugin_config, Mapping) else None
    result = dict(plugin_result or {})
    interpolation = result.get("interpolation") if isinstance(result.get("interpolation"), Mapping) else {}
    packmol_record = result.get("packmol") if isinstance(result.get("packmol"), Mapping) else {}
    plugin_provenance = result.get("provenance") if isinstance(result.get("provenance"), Mapping) else {}
    plugin_version = (
        result.get("plugin_version") or result.get("packmol_version")
        or packmol_record.get("version") or plugin_provenance.get("packmol_version")
        or interpolation.get("ase_version") or result.get("ase_version")
        or plugin_provenance.get("ase_version") or result.get("schema_version")
        or model_cfg.get("plugin_version") or "1.0.0"
    )
    plugin_id = str(result.get("plugin") or model_cfg.get("plugin_id") or operation or "ase.structure_loader")
    source_inputs = result.get("source_inputs") or result.get("provenance", {}).get("source_artifacts") or {}
    source_records: list[dict] = []

    def collect_source_artifacts(value: Any) -> None:
        if isinstance(value, Mapping):
            artifact_id = value.get("artifact_id")
            artifact_sha = value.get("artifact_sha256") or value.get("sha256")
            if artifact_id and isinstance(artifact_sha, str) and len(artifact_sha) == 64:
                candidate = {
                    "object_type": "DataAnalysisArtifact",
                    "object_id": str(artifact_id),
                    "schema_version": "1.0.0",
                    "sha256": artifact_sha,
                }
                if candidate not in source_records:
                    source_records.append(candidate)
            else:
                for child in value.values():
                    collect_source_artifacts(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect_source_artifacts(child)

    collect_source_artifacts(source_inputs)
    source_artifact_refs = source_records
    result_artifacts = result.get("artifacts") or []
    plugin_record = {
        "plugin_id": plugin_id,
        "plugin_version": str(plugin_version),
        "plugin_schema_version": result.get("schema_version"),
        "status": result.get("status"),
        "equilibration_status": result.get("equilibration_status"),
        "path_type": result.get("path_type"),
        "random_seed": result.get("random_seed"),
        "source_inputs": deepcopy(source_inputs),
        "output_artifacts": deepcopy(result_artifacts),
        "plugin_parameters": deepcopy(plugin_config.get("arguments") or {}),
        "plugin_provenance": deepcopy(result.get("provenance") or {}),
    }
    construction = model_cfg.get("construction_steps")
    if not isinstance(construction, list):
        construction = [{
            "step_id": "step-001", "operation_id": str(operation or "load_structure_model"),
            "inputs": (
                [item["object_id"] for item in source_artifact_refs]
                if plugin_result is not None and source_artifact_refs
                else ([str(artifact_id)] if artifact_id else [])
            ),
            "parameters": {"plugin_execution": plugin_record} if plugin_result is not None else {},
            "expected_artifacts": [
                str(item.get("path") or item.get("sha256") or "reviewable_model_structure")
                for item in result_artifacts if isinstance(item, Mapping)
            ] or ["reviewable_model_structure"],
        }]
    elif plugin_result is not None:
        construction = deepcopy(construction)
        if construction and isinstance(construction[0], Mapping):
            construction[0] = dict(construction[0])
            params = dict(construction[0].get("parameters") or {})
            params["plugin_execution"] = plugin_record
            construction[0]["parameters"] = params
    body = {
        "schema_version": PLANNING_SCHEMA_VERSION, "recipe_id": "",
        "model_type": model_type, "plugin_id": plugin_id,
        "plugin_version": str(plugin_version),
        "input_artifact_refs": artifact_refs,
        "source_artifact_refs": source_artifact_refs,
        "target_definition": target,
        "composition": dict(composition) if isinstance(composition, Mapping) else None,
        "topology": dict(topology) if isinstance(topology, Mapping) else None,
        "electronic_state": {**electronic, "source_evidence_refs": deepcopy(refs)},
        "construction_steps": construction,
        "constraints": [str(value) for value in (model_cfg.get("constraints") or [])],
        "validation_contract": {
            **deepcopy(model_cfg.get("validation_contract") or {}),
            "structure_plugin": plugin_record if plugin_result is not None else None,
        },
        "source_evidence_refs": deepcopy(refs),
        "decision_records": [],
        "evidence_gaps": gaps,
        "status": "BLOCKED" if gaps else "READY_FOR_REVIEW",
        "provenance": _provenance(refs, transform_sha, "pipeline.model_recipe_compiler"),
    }
    recipe = seal_object(body, object_type="ModelRecipe", id_field="recipe_id", prefix="model",
        status="BLOCKED" if gaps else "READY", source_evidence_refs=refs,
        upstream_sha256s=upstream, missing_items=gaps)
    return recipe, gaps
