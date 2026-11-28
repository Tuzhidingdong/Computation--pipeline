"""Initial transition-path construction using ASE NEB + IDPP only."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .core import (
    PLUGIN_SCHEMA_VERSION,
    artifact_record,
    decision_result,
    dependency_version,
    failed_result,
    jsonable,
    read_ase_source,
    sha256_file,
    write_json,
)


_REQUIRED_CONTEXT_KEYS = ("charge", "spin_multiplicity", "constraints", "method_fingerprint")


def _context_issues(context: Any, label: str) -> list[str]:
    if not isinstance(context, Mapping):
        return [f"endpoint_context.{label} must be an object"]
    issues = []
    for key in _REQUIRED_CONTEXT_KEYS:
        if key not in context or context[key] is None:
            issues.append(f"endpoint_context.{label}.{key} must be explicitly supplied")
    if not isinstance(context.get("method_fingerprint"), Mapping) or not context.get("method_fingerprint"):
        issues.append(f"endpoint_context.{label}.method_fingerprint must be a non-empty Mapping")
    if not isinstance(context.get("constraints"), list):
        issues.append(f"endpoint_context.{label}.constraints must be an explicit list")
    return issues


def _constraints_signature(atoms: Any) -> list[dict[str, Any]]:
    return [jsonable(constraint.todict()) for constraint in atoms.constraints]


def _minimum_pair_distance(atoms: Any, cutoff: float) -> tuple[float | None, list[dict[str, Any]]]:
    from ase.neighborlist import neighbor_list
    i_values, j_values, distances = neighbor_list(
        "ijd", atoms, cutoff, self_interaction=False
    )
    if len(distances) == 0:
        return None, []
    minimum = float(np.min(distances))
    close_pairs = []
    for i, j, distance in zip(i_values, j_values, distances):
        if int(i) < int(j) and float(distance) < cutoff:
            close_pairs.append({
                "atom_i": int(i),
                "atom_j": int(j),
                "distance_angstrom": float(distance),
            })
    return minimum, close_pairs


def build_neb_initial_path(
    initial_structure: Mapping[str, Any],
    final_structure: Mapping[str, Any],
    recipe: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build an IDPP-improved initial path from hash-pinned endpoint structures.

    Explicit recipe fields:
      atom_mapping_initial_to_final: bijection/list of final indices
      number_of_images: total images including both endpoints
      endpoint_context.initial/final: charge, spin_multiplicity, constraints,
        and method_fingerprint
      idpp: {steps, fmax, mic}
      validation.minimum_pair_distance_angstrom
    """
    plugin = "neb_initial_path"
    if not isinstance(initial_structure, Mapping) or not isinstance(final_structure, Mapping):
        return decision_result("initial_structure and final_structure must be hash-pinned source Mappings", plugin=plugin)
    if not isinstance(recipe, Mapping):
        return decision_result("recipe must be a Mapping", plugin=plugin)

    mapping = recipe.get("atom_mapping_initial_to_final")
    if not isinstance(mapping, list):
        return decision_result(
            "atom_mapping_initial_to_final must explicitly map every initial atom index to a final atom index",
            plugin=plugin,
        )
    image_count = recipe.get("number_of_images")
    if isinstance(image_count, bool) or not isinstance(image_count, int) or image_count < 3:
        return decision_result("number_of_images must explicitly be an integer >= 3, including both endpoints", plugin=plugin)

    endpoint_context = recipe.get("endpoint_context")
    if not isinstance(endpoint_context, Mapping):
        return decision_result("endpoint_context.initial and endpoint_context.final are required", plugin=plugin)
    context_issues = (
        _context_issues(endpoint_context.get("initial"), "initial")
        + _context_issues(endpoint_context.get("final"), "final")
    )
    if context_issues:
        return decision_result(*context_issues, plugin=plugin)
    if json.dumps(jsonable(endpoint_context["initial"]), sort_keys=True) != json.dumps(
        jsonable(endpoint_context["final"]), sort_keys=True
    ):
        return decision_result(
            "initial/final charge, spin, constraints and method_fingerprint must match exactly; an explicit approved conversion is required otherwise",
            plugin=plugin,
        )

    idpp = recipe.get("idpp")
    if not isinstance(idpp, Mapping):
        return decision_result("idpp must explicitly provide steps, fmax_angstrom_per_step and mic", plugin=plugin)
    steps = idpp.get("steps")
    fmax = idpp.get("fmax_angstrom_per_step")
    mic = idpp.get("mic")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        return decision_result("idpp.steps must be an explicitly supplied positive integer", plugin=plugin)
    if not isinstance(fmax, (int, float)) or not math.isfinite(float(fmax)) or float(fmax) <= 0:
        return decision_result("idpp.fmax_angstrom_per_step must be explicitly positive", plugin=plugin)
    if type(mic) is not bool:
        return decision_result("idpp.mic must be explicitly true or false", plugin=plugin)

    validation = recipe.get("validation")
    if not isinstance(validation, Mapping):
        return decision_result("validation.minimum_pair_distance_angstrom is required", plugin=plugin)
    minimum_distance = validation.get("minimum_pair_distance_angstrom")
    if not isinstance(minimum_distance, (int, float)) or not math.isfinite(float(minimum_distance)) or float(minimum_distance) <= 0:
        return decision_result("validation.minimum_pair_distance_angstrom must be explicitly positive", plugin=plugin)

    try:
        initial, initial_source = read_ase_source(initial_structure, "initial_structure")
        final_raw, final_source = read_ase_source(final_structure, "final_structure")
    except Exception as exc:
        return decision_result(f"endpoint input validation failed: {type(exc).__name__}: {exc}", plugin=plugin)

    natoms = len(initial)
    if len(final_raw) != natoms:
        return decision_result(
            f"endpoint atom counts differ: initial={natoms}, final={len(final_raw)}",
            plugin=plugin,
        )
    if initial.get_chemical_symbols() != final_raw.get_chemical_symbols():
        return decision_result(
            "endpoint element sequences differ; automatic atom reordering is prohibited",
            plugin=plugin,
        )
    if len(mapping) != natoms or any(
        isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= natoms
        for index in mapping
    ) or len(set(mapping)) != natoms:
        return decision_result(
            "atom mapping must be a complete bijection from initial atom indices to final atom indices",
            plugin=plugin,
        )
    if any(
        initial.get_chemical_symbols()[index] != final_raw.get_chemical_symbols()[mapping[index]]
        for index in range(natoms)
    ):
        return decision_result("explicit atom mapping maps unlike chemical elements", plugin=plugin)
    if mapping != list(range(natoms)) and (
        initial.constraints or final_raw.constraints
    ):
        return decision_result(
            "non-identity atom mapping with ASE constraints requires explicit constraint-index remapping; provide already aligned endpoint files",
            plugin=plugin,
        )

    initial_cell = np.asarray(initial.cell.array, dtype=float)
    final_cell = np.asarray(final_raw.cell.array, dtype=float)
    initial_pbc = np.asarray(initial.pbc, dtype=bool)
    final_pbc = np.asarray(final_raw.pbc, dtype=bool)
    if not np.allclose(initial_cell, final_cell, rtol=0.0, atol=1e-8) or not np.array_equal(initial_pbc, final_pbc):
        return decision_result(
            "endpoint cell and periodicity differ; this plugin does not interpolate or guess a cell conversion",
            plugin=plugin,
        )

    expected_constraints = endpoint_context["initial"]["constraints"]
    if _constraints_signature(initial) != jsonable(expected_constraints):
        return decision_result(
            "initial endpoint ASE constraints differ from endpoint_context.initial.constraints",
            plugin=plugin,
        )
    if _constraints_signature(final_raw) != jsonable(endpoint_context["final"]["constraints"]):
        return decision_result(
            "final endpoint ASE constraints differ from endpoint_context.final.constraints",
            plugin=plugin,
        )
    if not np.all(np.isfinite(initial.positions)) or not np.all(np.isfinite(final_raw.positions)):
        return decision_result("endpoint coordinates contain non-finite values", plugin=plugin)

    # Apply only the caller-supplied index mapping. No distance-based atom matching.
    final = final_raw[mapping]
    if initial.get_chemical_symbols() != final.get_chemical_symbols():
        return decision_result("explicit atom mapping did not produce identical ordered elements", plugin=plugin)

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    input_dir = target / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    from ase.io import write

    initial_copy = input_dir / f"initial_source{Path(initial_source['path']).suffix or '.structure'}"
    final_copy = input_dir / f"final_source{Path(final_source['path']).suffix or '.structure'}"
    import shutil
    shutil.copy2(initial_source["path"], initial_copy)
    shutil.copy2(final_source["path"], final_copy)
    if sha256_file(initial_copy) != initial_source["sha256"] or sha256_file(final_copy) != final_source["sha256"]:
        return failed_result("endpoint source copy SHA-256 mismatch", plugin=plugin, output_dir=target)

    original_initial_positions = initial.positions.copy()
    original_final_positions = final.positions.copy()
    image_list = [initial.copy()]
    image_list.extend(initial.copy() for _ in range(image_count - 2))
    image_list.append(final.copy())

    idpp_traj = target / "idpp_optimization.traj"
    idpp_log = target / "idpp_optimization.log"
    try:
        from ase.mep import NEB, idpp_interpolate
        neb = NEB(image_list)
        neb.interpolate(method="linear", mic=mic)
        idpp_interpolate(
            neb,
            traj=str(idpp_traj),
            log=str(idpp_log),
            fmax=float(fmax),
            steps=steps,
            mic=mic,
        )
        # IDPP is permitted to move only internal images.
        if not np.allclose(image_list[0].positions, original_initial_positions, rtol=0.0, atol=1e-10):
            raise RuntimeError("IDPP altered the initial endpoint")
        if not np.allclose(image_list[-1].positions, original_final_positions, rtol=0.0, atol=1e-10):
            raise RuntimeError("IDPP altered the final endpoint")

        geometry_records = []
        for image_index, image in enumerate(image_list):
            if image.get_chemical_symbols() != initial.get_chemical_symbols():
                raise RuntimeError(f"image {image_index} element ordering differs from the endpoints")
            if not np.all(np.isfinite(image.positions)):
                raise RuntimeError(f"image {image_index} contains non-finite coordinates")
            if not np.allclose(image.cell.array, initial.cell.array, rtol=0.0, atol=1e-8):
                raise RuntimeError(f"image {image_index} cell differs from endpoint cell")
            if not np.array_equal(image.pbc, initial.pbc):
                raise RuntimeError(f"image {image_index} periodicity differs from endpoints")
            minimum_found, close_pairs = _minimum_pair_distance(image, float(minimum_distance))
            if close_pairs:
                raise RuntimeError(
                    f"image {image_index} has {len(close_pairs)} pair(s) below the declared "
                    f"{float(minimum_distance):.6g} Å minimum; nearest={minimum_found:.6g} Å"
                )
            geometry_records.append({
                "image_index": image_index,
                "minimum_pair_distance_threshold_angstrom": float(minimum_distance),
                "pairs_below_threshold": 0,
                "minimum_pair_distance_observed_angstrom": minimum_found,
                "distance_statement": (
                    "no atom pair was found below the declared threshold"
                    if minimum_found is None else
                    f"all atom pairs are >= {float(minimum_distance):.6g} Å"
                ),
            })

        images_dir = target / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        image_artifacts = []
        for image_index, image in enumerate(image_list):
            image_path = images_dir / f"image_{image_index:03d}.extxyz"
            write(str(image_path), image, format="extxyz")
            image_artifacts.append(artifact_record(image_path, target))
        path_file = target / "initial_path.extxyz"
        write(str(path_file), image_list, format="extxyz")
    except Exception as exc:
        error_log = idpp_log
        if not error_log.exists():
            error_log.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {
            **failed_result(f"ASE IDPP path generation/validation failed: {type(exc).__name__}: {exc}", plugin=plugin, output_dir=target),
            "endpoint_sha256": {
                "initial": initial_source["sha256"],
                "final": final_source["sha256"],
            },
            "artifacts": [
                artifact_record(initial_copy, target),
                artifact_record(final_copy, target),
                artifact_record(error_log, target),
            ],
        }

    metadata = {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin": plugin,
        "status": "INITIAL_PATH_READY_FOR_REVIEW",
        "path_type": "IDPP_IMPROVED_INITIAL_GUESS",
        "number_of_images": image_count,
        "atom_count": natoms,
        "atom_mapping_initial_to_final": mapping,
        "element_sequence": initial.get_chemical_symbols(),
        "endpoint_sha256": {
            "initial": initial_source["sha256"],
            "final": final_source["sha256"],
        },
        "cell_angstrom": initial.cell.array.tolist(),
        "pbc": initial.pbc.tolist(),
        "endpoint_context": jsonable(endpoint_context),
        "interpolation": {
            "library": "ASE",
            "method": "ase.mep.neb.idpp_interpolate",
            "idpp_fmax_angstrom_per_step": float(fmax),
            "idpp_steps": steps,
            "mic": mic,
            "ase_version": dependency_version("ase", "ase"),
        },
        "geometry_validation": geometry_records,
        "artifacts": [
            artifact_record(initial_copy, target),
            artifact_record(final_copy, target),
            artifact_record(idpp_traj, target) if idpp_traj.exists() else None,
            artifact_record(idpp_log, target) if idpp_log.exists() else None,
            *image_artifacts,
            artifact_record(path_file, target),
        ],
        "scientific_limit": (
            "This is an ASE IDPP-improved initial path for review only. It is not a converged NEB, "
            "a transition state, a Dimer result, a frequency result, or an IRC pathway."
        ),
    }
    metadata["artifacts"] = [item for item in metadata["artifacts"] if item is not None]
    write_json(target / "path_manifest.json", metadata)
    metadata["artifacts"].append(artifact_record(target / "path_manifest.json", target))
    metadata["path_manifest_sha256"] = sha256_file(target / "path_manifest.json")
    return metadata
