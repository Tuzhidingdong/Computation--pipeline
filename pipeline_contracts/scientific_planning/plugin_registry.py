"""Thin, lazy adapters for Agent A engine planners and Agent C model plugins."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping


def engine_planning(request: Mapping[str, Any]) -> dict:
    from .engines import build_engine_planning, evaluate_qc
    planning = build_engine_planning(dict(request))
    return {
        "capability_route": planning["capability_route"],
        "method_plan": planning["method_plan"],
        "resource_plan": planning["resource_plan"],
        "qc_contract": planning["qc_contract"],
        "qc_evaluator": evaluate_qc,
        "engine_planning_contract": {
            "interface": planning.get("interface"),
            "creates_calculation_plan": planning.get("creates_calculation_plan", False),
            "submits_or_executes_calculation": planning.get("submits_or_executes_calculation", False),
        },
    }


def structure_route(model_type: str) -> dict:
    from pipeline_contracts.model_plugins.structure import get_model_plugin_route
    return get_model_plugin_route(model_type)


def run_structure_plugin(operation: str, arguments: Mapping[str, Any],
                         output_dir: str | Path | None = None) -> dict:
    from pipeline_contracts.model_plugins.structure import (
        load_structure_model, build_explicit_solvent_box, build_neb_initial_path,
        build_supercell, generate_slabs, find_adsorption_sites, build_adsorbate_candidates,
        build_molecule_conformer_from_smiles,
    )
    args = dict(arguments)
    if operation == "load_structure_model":
        source = args["source"]
        if not isinstance(source, Mapping):
            raise TypeError("structure source must be a Mapping")
        artifact_id = source.get("artifact_id")
        artifact_sha = source.get("artifact_sha256")
        if (artifact_id is None) != (artifact_sha is None):
            raise ValueError("registered Artifact source requires both artifact_id and artifact_sha256")
        minimal_source = {"path": source["path"], "sha256": source["sha256"]}
        mapping = load_structure_model(minimal_source, structure_type=args.get("structure_type", "atomistic"))
        verified_sha = str((mapping.get("source") or {}).get("sha256") or "").lower()
        if artifact_id is not None:
            if not str(artifact_id).strip() or str(artifact_sha).lower() != verified_sha:
                raise ValueError("registered Artifact identity SHA does not match the verified structure bytes")
            mapping.setdefault("source", {}).update({
                "artifact_id": str(artifact_id), "artifact_sha256": verified_sha,
            })
        mapping.setdefault("plugin", "ase.structure_loader")
        mapping.setdefault("plugin_schema_version", "1.0.0")
        return mapping
    if operation == "build_explicit_solvent_box":
        if output_dir is None:
            raise ValueError("Packmol requires an explicit output directory")
        return build_explicit_solvent_box(args.get("recipe", {}), output_dir,
                                          packmol_executable=args.get("packmol_executable"))
    if operation == "build_neb_initial_path":
        if output_dir is None:
            raise ValueError("ASE IDPP requires an explicit output directory")
        return build_neb_initial_path(args.get("initial_structure", {}),
                                      args.get("final_structure", {}),
                                      args.get("recipe", {}), output_dir)
    if operation == "build_supercell":
        return build_supercell(args.get("source", {}), args.get("supercell_matrix"))
    if operation == "generate_slabs":
        return generate_slabs(args.get("source", {}), args.get("recipe", {}))
    if operation == "find_adsorption_sites":
        return find_adsorption_sites(args.get("slab_source", {}), args.get("recipe", {}))
    if operation == "build_adsorbate_candidates":
        return build_adsorbate_candidates(args.get("slab_source", {}),
                                          args.get("adsorbate_mapping", {}), args.get("recipe", {}))
    if operation == "build_molecule_conformer_from_smiles":
        if output_dir is None:
            raise ValueError("RDKit conformer generation requires an explicit output directory")
        output = Path(output_dir) / str(args.get("output_name") or "conformer.extxyz")
        return build_molecule_conformer_from_smiles(
            args.get("smiles", ""), random_seed=args.get("random_seed"),
            output_path=output, optimize=args.get("optimize", False),
            force_field=args.get("force_field"),
        )
    raise ValueError(f"unregistered structure plugin operation: {operation}")


def plugin_capability_status(route: Mapping[str, Any]) -> str:
    status = str(route.get("status") or "").upper()
    if status in {"UNSUPPORTED", "NOT_SUPPORTED", "NOT_INTEGRATED"}:
        return "UNSUPPORTED"
    if status in {"PLANNABLE_ONLY", "AVAILABLE_FOR_PLANNING"}:
        return "PLANNABLE_ONLY"
    if status in {"SUPPORTED", "AVAILABLE", "READY", "INTEGRATED"}:
        return "READY"
    return "UNSUPPORTED"



class ModelPluginRegistry:
    """Single runtime registry facade for the existing Agent C structure plugins."""

    def route(self, model_type: str) -> dict:
        return structure_route(model_type)

    def invoke(self, operation: str, arguments: Mapping[str, Any],
               output_dir: str | Path | None = None) -> dict:
        return run_structure_plugin(operation, arguments, output_dir)


MODEL_PLUGIN_REGISTRY = ModelPluginRegistry()
