"""Explicit-solvent initial packing using the external Packmol executable."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from .core import (
    PLUGIN_SCHEMA_VERSION,
    artifact_record,
    copy_verified_source,
    decision_result,
    dependency_version,
    executable_version,
    failed_result,
    read_ase_source,
    sha256_file,
    validate_source_spec,
    write_json,
)


def _positive_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0.0
    except (TypeError, ValueError):
        return False


def _resolve_counts(solvents: list[dict[str, Any]], box: Mapping[str, Any]) -> tuple[list[int] | None, list[str]]:
    """Use explicit counts or an explicit one-component density calculation."""
    issues: list[str] = []
    has_density = "target_density_g_cm3" in box or "accessible_volume_angstrom3" in box
    if has_density:
        if len(solvents) != 1:
            return None, ["density-based counts currently require exactly one solvent species"]
        item = solvents[0]
        if "count" in item:
            return None, ["specify either a molecule count or density, not both"]
        density = box.get("target_density_g_cm3")
        volume = box.get("accessible_volume_angstrom3")
        rounding = box.get("molecule_count_rounding")
        if not _positive_number(density):
            issues.append("target_density_g_cm3 must be explicitly supplied and positive")
        if not _positive_number(volume):
            issues.append("accessible_volume_angstrom3 must be explicitly supplied and positive")
        if rounding not in {"floor", "nearest", "ceil"}:
            issues.append("molecule_count_rounding must explicitly be floor, nearest, or ceil")
        if issues:
            return None, issues
        # Read the pinned solvent source to determine its actual molecular mass.
        atoms, _ = read_ase_source(item, "solvents[0]")
        molar_mass = float(atoms.get_masses().sum())
        if not _positive_number(molar_mass):
            return None, ["solvent molecular mass could not be calculated from its explicit structure"]
        import math as _math
        avogadro = 6.02214076e23
        raw_count = float(density) * float(volume) * 1.0e-24 * avogadro / molar_mass
        if rounding == "floor":
            count = _math.floor(raw_count)
        elif rounding == "ceil":
            count = _math.ceil(raw_count)
        else:
            count = int(_math.floor(raw_count + 0.5))
        if count <= 0:
            return None, [
                f"explicit density/accessible volume yields {raw_count:.6g} molecules and rounds to zero; supply a larger explicit volume or an explicit count"
            ]
        return [count], []
    counts: list[int] = []
    for index, item in enumerate(solvents):
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            issues.append(f"solvents[{index}].count must be an explicitly supplied positive integer")
        else:
            counts.append(count)
    if issues:
        return None, issues
    return counts, []



def _safe_species_id(value: Any, index: int) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or f"solvent{index}")).strip("._")
    if not token:
        token = f"solvent{index}"
    return token[:48]

def _normalise_template(atoms: Any, destination: Path, *, coordinate_shift: list[float]):
    """Write a plain single-molecule XYZ template for Packmol."""
    from ase.io import write
    template = atoms.copy()
    template.set_positions(template.get_positions() + coordinate_shift)
    template.set_cell([0.0, 0.0, 0.0])
    template.set_pbc(False)
    template.set_constraint()
    write(str(destination), template, format="xyz")
    return template


def _box_data(recipe: Mapping[str, Any]) -> tuple[list[float], list[float], list[float], list[bool], list[str]]:
    issues: list[str] = []
    box = recipe.get("box")
    if not isinstance(box, Mapping):
        return [], [], [], [], ["box must explicitly contain bounds_angstrom and pbc"]
    bounds = box.get("bounds_angstrom")
    pbc = box.get("pbc")
    if not isinstance(bounds, list) or len(bounds) != 2 or any(
        not isinstance(row, list) or len(row) != 3 for row in bounds
    ):
        issues.append("box.bounds_angstrom must be [[xmin,ymin,zmin],[xmax,ymax,zmax]]")
        lower, upper = [], []
    else:
        try:
            lower = [float(x) for x in bounds[0]]
            upper = [float(x) for x in bounds[1]]
            if not all(math.isfinite(x) for x in lower + upper):
                raise ValueError
            if any(upper[i] <= lower[i] for i in range(3)):
                raise ValueError
        except (TypeError, ValueError):
            lower, upper = [], []
            issues.append("box bounds must be finite and each upper bound must exceed its lower bound")
    if not isinstance(pbc, list) or len(pbc) != 3 or any(type(flag) is not bool for flag in pbc):
        issues.append("box.pbc must explicitly contain three booleans")
        periodic = []
    else:
        periodic = list(pbc)
        if any(periodic) and not all(periodic):
            issues.append("Packmol box mode supports either all three periodic axes or no periodic axes; partial PBC needs a specialist region definition")
    if issues:
        return lower, upper, [], periodic, issues
    lengths = [upper[i] - lower[i] for i in range(3)]
    shift = [-value for value in lower] if all(periodic) else [0.0, 0.0, 0.0]
    return lower, upper, lengths, periodic, []


def build_explicit_solvent_box(
    recipe: Mapping[str, Any],
    output_dir: str | Path,
    *,
    packmol_executable: str | None = None,
) -> dict[str, Any]:
    """Build and validate a Packmol initial solvent box.

    Recipe contract (all scientific choices explicit):
      solute: {path, sha256}
      solvents: [{id, path, sha256, count}, ...]
      box: {bounds_angstrom: [[lo...], [hi...]], pbc: [bool, bool, bool]}
      distance_tolerance_angstrom, random_seed, output_format
      validation: {minimum_inter_molecular_distance_angstrom}

    Alternatively, for a single solvent only, omit count and provide
    box.target_density_g_cm3, box.accessible_volume_angstrom3 and
    box.molecule_count_rounding. Density-derived counts are reported exactly.
    """
    plugin = "explicit_solvent_packmol"
    if not isinstance(recipe, Mapping):
        return decision_result("recipe must be a Mapping", plugin=plugin)

    solute_spec = recipe.get("solute")
    solvent_specs = recipe.get("solvents")
    if not isinstance(solvent_specs, list) or not solvent_specs:
        return decision_result("solvents must explicitly list at least one molecule structure", plugin=plugin)
    if any(not isinstance(item, Mapping) for item in solvent_specs):
        return decision_result("each solvents entry must be a Mapping", plugin=plugin)
    species_ids = [_safe_species_id(item.get("id"), index) for index, item in enumerate(solvent_specs)]
    if len(set(species_ids)) != len(species_ids):
        return decision_result("each solvent species must have a unique explicit id", plugin=plugin)
    if not isinstance(solute_spec, Mapping):
        return decision_result("solute must explicitly identify a structure file and SHA-256", plugin=plugin)

    lower, upper, lengths, pbc, box_issues = _box_data(recipe)
    if box_issues:
        return decision_result(*box_issues, plugin=plugin)

    tolerance = recipe.get("distance_tolerance_angstrom")
    seed = recipe.get("random_seed")
    output_format = str(recipe.get("output_format", "")).lower()
    validation = recipe.get("validation")
    if not _positive_number(tolerance):
        return decision_result("distance_tolerance_angstrom must be explicitly supplied and positive", plugin=plugin)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed <= 0:
        return decision_result("random_seed must be an explicitly supplied positive integer", plugin=plugin)
    if output_format not in {"xyz", "extxyz", "pdb"}:
        return decision_result("output_format must explicitly be xyz, extxyz, or pdb", plugin=plugin)
    if not isinstance(validation, Mapping) or not _positive_number(
        validation.get("minimum_inter_molecular_distance_angstrom")
    ):
        return decision_result(
            "validation.minimum_inter_molecular_distance_angstrom must explicitly set the severe-overlap threshold",
            plugin=plugin,
        )

    counts, count_issues = _resolve_counts(solvent_specs, recipe.get("box", {}))
    if count_issues:
        return decision_result(*count_issues, plugin=plugin)

    input_specs = [("solute", solute_spec)] + [
        (f"solvents[{i}]", item) for i, item in enumerate(solvent_specs)
    ]
    verified: list[tuple[str, Path, str]] = []
    for label, spec in input_specs:
        path, digest, issues = validate_source_spec(spec, label)
        if issues:
            return decision_result(*issues, plugin=plugin)
        verified.append((label, path, digest))

    # Read and check all source structures before creating output_dir.
    try:
        solute_atoms, solute_source = read_ase_source(solute_spec, "solute")
        solvent_atoms: list[Any] = []
        solvent_sources: list[dict[str, Any]] = []
        for index, spec in enumerate(solvent_specs):
            atoms, source = read_ase_source(spec, f"solvents[{index}]")
            solvent_atoms.append(atoms)
            solvent_sources.append(source)
    except Exception as exc:
        return decision_result(f"source structure validation failed: {type(exc).__name__}: {exc}", plugin=plugin)

    coordinate_shift = [-value for value in lower] if all(pbc) else [0.0, 0.0, 0.0]
    shifted_solute = solute_atoms.positions + coordinate_shift
    if any(
        (shifted_solute[:, axis] < -1e-6).any()
        or (shifted_solute[:, axis] > lengths[axis] + 1e-6).any()
        for axis in range(3)
    ):
        return decision_result(
            "the fixed solute structure is not entirely inside the explicitly declared packing box",
            plugin=plugin,
        )

    executable = packmol_executable or shutil.which("packmol")
    if not executable:
        return {
            **failed_result("Packmol executable not found; install the pinned Packmol package or supply packmol_executable", plugin=plugin),
            "status": "UNSUPPORTED_DEPENDENCY_MISSING",
            "required_dependency": "packmol==21.2.3 (or a separately verified Packmol executable)",
        }

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    inputs_dir = target / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    original_sources = []
    verified_source_records = [solute_source, *solvent_sources]
    for index, (label, path, digest) in enumerate(verified):
        original = path
        suffix = original.suffix or ".structure"
        copied = copy_verified_source(original, digest, inputs_dir / f"source_{index:02d}_{label.replace('[','_').replace(']','')}{suffix}")
        source_identity = {
            key: verified_source_records[index][key]
            for key in ("artifact_id", "artifact_sha256")
            if key in verified_source_records[index]
        }
        original_sources.append({"role": label, **copied, **source_identity})

    from ase.io import write
    template_records: list[dict[str, Any]] = []
    solute_template_path = inputs_dir / "solute_template.xyz"
    solute_template = _normalise_template(
        solute_atoms, solute_template_path, coordinate_shift=coordinate_shift
    )
    template_records.append({
        "role": "solute", "path": solute_template_path.name,
        "sha256": sha256_file(solute_template_path), "atom_count": len(solute_template),
        "molecule_count": 1,
    })
    for index, (spec, atoms, count) in enumerate(zip(solvent_specs, solvent_atoms, counts)):
        template_path = inputs_dir / f"solvent_{index:02d}_{_safe_species_id(spec.get('id'), index)}.xyz"
        template = _normalise_template(atoms, template_path, coordinate_shift=[0.0, 0.0, 0.0])
        template_records.append({
            "role": "solvent", "species_id": _safe_species_id(spec.get("id"), index),
            "path": template_path.name, "sha256": sha256_file(template_path),
            "atom_count": len(template), "molecule_count": count,
            "molecular_mass_amu": float(template.get_masses().sum()),
        })

    if all(pbc):
        packmol_bounds = [0.0, 0.0, 0.0, *lengths]
        pbc_line = "pbc " + " ".join(f"{x:.10g}" for x in lengths)
    else:
        packmol_bounds = [*lower, *upper]
        pbc_line = ""
    lines = [
        f"tolerance {float(tolerance):.10g}",
        "filetype xyz",
        f"output {target / 'packed.xyz'}",
        f"seed {seed}",
    ]
    if pbc_line:
        lines.append(pbc_line)
    lines.extend([
        "structure inputs/solute_template.xyz",
        "  number 1",
        "  fixed 0.0 0.0 0.0 0.0 0.0 0.0",
        "  inside box " + " ".join(f"{x:.10g}" for x in packmol_bounds),
        "end structure",
    ])
    for index, (record, count) in enumerate(zip(template_records[1:], counts)):
        lines.extend([
            f"structure inputs/solvent_{index:02d}_{_safe_species_id(solvent_specs[index].get('id'), index)}.xyz",
            f"  number {count}",
            "  inside box " + " ".join(f"{x:.10g}" for x in packmol_bounds),
            "end structure",
        ])
    packmol_input = "\n".join(lines) + "\n"
    input_path = target / "packmol.inp"
    input_path.write_text(packmol_input, encoding="utf-8")

    version = executable_version(str(executable), "packmol")
    log_path = target / "packmol.log"
    try:
        completed = subprocess.run(
            [str(executable), "-i", str(input_path)],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=float(recipe.get("timeout_seconds", 300)),
            check=False,
        )
    except Exception as exc:
        log_path.write_text(f"Packmol invocation failed: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {
            **failed_result(f"Packmol invocation failed: {type(exc).__name__}: {exc}", plugin=plugin, output_dir=target),
            "packmol_version": version,
            "random_seed": seed,
            "source_inputs": original_sources,
            "provenance": {
                "source_artifacts": [
                    {key: item[key] for key in ("role", "artifact_id", "artifact_sha256") if key in item}
                    for item in original_sources if "artifact_id" in item
                ]
            },
            "artifacts": [artifact_record(input_path, target), artifact_record(log_path, target)],
        }
    log_text = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    log_path.write_text(log_text, encoding="utf-8")
    packed_path = target / "packed.xyz"
    if completed.returncode != 0 or not packed_path.is_file():
        manifest = {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": plugin,
            "status": "PACKING_FAILED",
            "packmol_returncode": completed.returncode,
            "packmol_version": version,
            "random_seed": seed,
            "source_inputs": original_sources,
            "provenance": {
                "source_artifacts": [
                    {key: item[key] for key in ("role", "artifact_id", "artifact_sha256") if key in item}
                    for item in original_sources if "artifact_id" in item
                ]
            },
            "artifacts": [
                artifact_record(input_path, target),
                artifact_record(log_path, target),
            ],
        }
        write_json(target / "run_manifest.json", manifest)
        return manifest

    try:
        from ase.io import read as ase_read
        from ase.neighborlist import neighbor_list
        packed = ase_read(str(packed_path), index=0)
        expected_atoms = len(solute_atoms) + sum(
            len(atoms) * count for atoms, count in zip(solvent_atoms, counts)
        )
        expected_symbols = (
            solute_atoms.get_chemical_symbols()
            + [
                symbol
                for atoms, count in zip(solvent_atoms, counts)
                for _ in range(count)
                for symbol in atoms.get_chemical_symbols()
            ]
        )
        if len(packed) != expected_atoms:
            raise ValueError(f"atom count {len(packed)} differs from expected {expected_atoms}")
        if packed.get_chemical_symbols() != expected_symbols:
            raise ValueError("Packmol output atom order/elements do not match the explicit template block order")
        packed.set_cell(lengths)
        packed.set_pbc(pbc)

        if all(pbc):
            lower_check = [0.0, 0.0, 0.0]
            upper_check = lengths
        else:
            lower_check = lower
            upper_check = upper
        coords = packed.get_positions()
        for axis in range(3):
            if (coords[:, axis] < lower_check[axis] - 1e-4).any() or (
                coords[:, axis] > upper_check[axis] + 1e-4
            ).any():
                raise ValueError("one or more output atoms lie outside the declared packing region")

        import numpy as np
        molecule_ids: list[int] = []
        molecule_types: list[str] = []
        next_id = 0
        for atom_count in [len(solute_atoms)]:
            molecule_ids.extend([next_id] * atom_count)
            molecule_types.extend(["solute"] * atom_count)
            next_id += 1
        for index, (atoms, count) in enumerate(zip(solvent_atoms, counts)):
            species_id = _safe_species_id(solvent_specs[index].get("id"), index)
            for _ in range(count):
                molecule_ids.extend([next_id] * len(atoms))
                molecule_types.extend([species_id] * len(atoms))
                next_id += 1
        packed.new_array("molecule_id", np.asarray(molecule_ids, dtype=int))
        packed.new_array("molecule_type", np.asarray(molecule_types, dtype=f"U{max(1, max(len(value) for value in molecule_types))}"))

        threshold = float(validation["minimum_inter_molecular_distance_angstrom"])
        atom_i, atom_j, distances = neighbor_list(
            "ijd", packed, threshold, self_interaction=False
        )
        ids = packed.arrays["molecule_id"]
        violating = [
            float(distance) for i, j, distance in zip(atom_i, atom_j, distances)
            if ids[int(i)] != ids[int(j)]
        ]
        if violating:
            raise ValueError(
                f"inter-molecular atom overlap: minimum {min(violating):.6g} Å "
                f"is below the declared {threshold:.6g} Å threshold"
            )

        if output_format == "pdb":
            final_path = target / "structure.pdb"
        elif output_format == "extxyz":
            final_path = target / "structure.extxyz"
        else:
            final_path = target / "structure.xyz"
        write(str(final_path), packed, format=output_format)
        validation_report = {
            "status": "passed",
            "atom_count": len(packed),
            "molecule_count": 1 + sum(counts),
            "molecule_counts": {
                "solute": 1,
                **{
                    _safe_species_id(item.get("id"), i): counts[i]
                    for i, item in enumerate(solvent_specs)
                },
            },
            "box_bounds_angstrom": [lower, upper],
            "cell_angstrom": packed.cell.array.tolist(),
            "pbc": packed.pbc.tolist(),
            "minimum_inter_molecular_distance_threshold_angstrom": threshold,
            "no_inter_molecular_pairs_below_threshold": True,
            "minimum_inter_molecular_distance_observed_angstrom": (
                min(violating) if violating else None
            ),
            "minimum_distance_statement": (
                "no inter-molecular atom pair was found below the declared threshold"
            ),
        }
    except Exception as exc:
        result = {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": plugin,
            "status": "PACKED_NOT_EQUILIBRATED",
            "validation": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
            "equilibration_status": "NOT_EQUILIBRATED",
            "packmol_version": version,
            "random_seed": seed,
            "source_inputs": original_sources,
            "provenance": {
                "source_sha256": [item["sha256"] for item in original_sources],
                "source_artifacts": [
                    {key: item[key] for key in ("role", "artifact_id", "artifact_sha256") if key in item}
                    for item in original_sources if "artifact_id" in item
                ],
            },
            "artifacts": [
                artifact_record(input_path, target),
                artifact_record(log_path, target),
                artifact_record(packed_path, target),
            ],
        }
        write_json(target / "run_manifest.json", result)
        result["artifacts"].append(artifact_record(target / "run_manifest.json", target))
        return result

    result = {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin": plugin,
        "status": "VALIDATED_INITIAL_STRUCTURE",
        "structure_state": "VALIDATED_INITIAL_STRUCTURE",
        "equilibration_status": "PACKED_NOT_EQUILIBRATED",
        "validation": validation_report,
        "packmol": {
            "executable": str(executable),
            "version": version,
            "returncode": completed.returncode,
            "random_seed": seed,
            "distance_tolerance_angstrom": float(tolerance),
            "input_file": "packmol.inp",
            "log_file": "packmol.log",
        },
        "source_inputs": original_sources,
        "molecule_templates": template_records,
        "coordinate_origin_shift_angstrom": coordinate_shift,
        "artifacts": [
            artifact_record(input_path, target),
            artifact_record(log_path, target),
            artifact_record(packed_path, target),
            artifact_record(final_path, target),
        ],
        "provenance": {
            "ase_version": dependency_version("ase", "ase"),
            "packmol_version": version,
            "random_seed": seed,
            "source_sha256": [item["sha256"] for item in original_sources],
            "source_artifacts": [
                {key: item[key] for key in ("role", "artifact_id", "artifact_sha256") if key in item}
                for item in original_sources if "artifact_id" in item
            ],
        },
        "scientific_limit": (
            "Packmol creates an initial geometric packing only. This is not solvent equilibration, "
            "a stable solvent configuration, force-field relaxation, or AIMD."
        ),
    }
    write_json(target / "run_manifest.json", result)
    result["artifacts"].append(artifact_record(target / "run_manifest.json", target))
    result["run_manifest_sha256"] = sha256_file(target / "run_manifest.json")
    return result
