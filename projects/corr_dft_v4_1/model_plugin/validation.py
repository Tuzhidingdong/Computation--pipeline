"""Independent model integrity, composition, electron-parity and geometry checks."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import math


def _array_string(value: Any) -> str:
    item = value.item() if hasattr(value, "item") else value
    return item.decode("utf-8") if isinstance(item, bytes) else str(item)


def validate_candidate(
    structure_path: str | Path, topology_path: str | Path, expected: Mapping[str, Any],
    *, pseudopotential_valence: Mapping[str, int], minimum_distance_angstrom: float = 0.65,
) -> dict:
    try:
        from ase.io import read
    except ImportError as exc:
        raise RuntimeError("ASE is required for candidate validation") from exc
    if not math.isfinite(float(minimum_distance_angstrom)) or float(minimum_distance_angstrom) <= 0:
        raise ValueError("minimum_distance_angstrom must be finite and positive")

    structure_path, topology_path = Path(structure_path), Path(topology_path)
    atoms = read(str(structure_path), index=0)
    atoms_again = read(str(structure_path), index=0)
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    symbols = atoms.get_chemical_symbols()
    counts = Counter(symbols)
    formula = atoms.get_chemical_formula(mode="hill")
    positions = atoms.get_positions()
    diagnostics = []

    if atoms.pbc.any():
        diagnostics.append("STRUCTURE_MUST_BE_NONPERIODIC")
    if len(atoms) != int(expected.get("atom_count", -1)):
        diagnostics.append("ATOM_COUNT_MISMATCH")
    if expected.get("composition") and dict(counts) != dict(expected["composition"]):
        diagnostics.append("ELEMENT_COMPOSITION_MISMATCH")
    if expected.get("formula") and formula != expected["formula"]:
        diagnostics.append("FORMULA_MISMATCH")

    topology_atoms = topology.get("atoms", [])
    topology_ids = [str(item.get("atom_id", "")) for item in topology_atoms]
    if len(topology_atoms) != len(atoms) or len(set(topology_ids)) != len(topology_ids) or any(not x for x in topology_ids):
        diagnostics.append("TOPOLOGY_ATOM_MAPPING_INVALID")
    else:
        topology_elements = [str(item.get("element", "")) for item in topology_atoms]
        if topology_elements != symbols:
            diagnostics.append("TOPOLOGY_ELEMENT_ORDER_MISMATCH")
        for index, item in enumerate(topology_atoms):
            try:
                expected_position = [float(value) for value in item["position"]]
                actual_position = [float(value) for value in positions[index]]
            except (KeyError, TypeError, ValueError, OverflowError):
                diagnostics.append("TOPOLOGY_COORDINATE_MAPPING_INVALID")
                break
            if len(expected_position) != 3 or any(
                not math.isfinite(value) for value in expected_position + actual_position
            ):
                diagnostics.append("NONFINITE_OR_INVALID_COORDINATES")
                break
            if any(abs(a - b) > 1e-8 for a, b in zip(expected_position, actual_position)):
                diagnostics.append("TOPOLOGY_COORDINATE_ORDER_MISMATCH")
                break

    stored_ids = atoms.arrays.get("atom_id")
    if stored_ids is None or len(stored_ids) != len(atoms):
        diagnostics.append("STRUCTURE_ATOM_IDS_MISSING")
    elif topology_ids and [_array_string(value) for value in stored_ids] != topology_ids:
        diagnostics.append("STRUCTURE_TOPOLOGY_ATOM_ID_MISMATCH")

    if any(not math.isfinite(float(value)) for row in positions for value in row):
        diagnostics.append("NONFINITE_OR_INVALID_COORDINATES")

    charge = expected.get("charge")
    if not isinstance(charge, int) or isinstance(charge, bool):
        diagnostics.append("TOTAL_CHARGE_NOT_EXPLICIT")
        electron_count = None
    else:
        missing = sorted(set(counts) - set(pseudopotential_valence))
        if missing:
            diagnostics.append("PSEUDOPOTENTIAL_VALENCE_MISSING")
            electron_count = None
        else:
            electron_count = sum(counts[element] * int(pseudopotential_valence[element])
                                 for element in counts) - charge
            if expected.get("pseudopotential_electron_count") is not None and (
                electron_count != int(expected["pseudopotential_electron_count"])
            ):
                diagnostics.append("PSEUDOPOTENTIAL_ELECTRON_COUNT_MISMATCH")
    multiplicity = expected.get("multiplicity")
    if not isinstance(multiplicity, int) or isinstance(multiplicity, bool) or multiplicity < 1:
        diagnostics.append("SPIN_MULTIPLICITY_NOT_EXPLICIT")
    elif electron_count is not None and electron_count % 2 != (multiplicity + 1) % 2:
        diagnostics.append("ELECTRON_SPIN_PARITY_MISMATCH")

    atom_index = {atom_id: index for index, atom_id in enumerate(topology_ids)}
    overlaps = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            distance = float(atoms.get_distance(i, j, mic=False))
            if distance < minimum_distance_angstrom:
                overlaps.append({"i": i, "j": j, "distance_angstrom": distance})
    if overlaps:
        diagnostics.append("ATOMIC_OVERLAP")

    bonds = topology.get("bonds", [])
    seen_bonds = set()
    coordination_checks = []
    donor_atoms = topology.get("donor_atoms", [])
    if any(item not in atom_index for item in donor_atoms):
        diagnostics.append("DONOR_ATOM_MAPPING_INVALID")
    for bond in bonds:
        atom1, atom2 = bond.get("atom1"), bond.get("atom2")
        if atom1 not in atom_index or atom2 not in atom_index or atom1 == atom2:
            diagnostics.append("TOPOLOGY_BOND_ENDPOINT_MISSING")
            continue
        pair = tuple(sorted((atom1, atom2)))
        if pair in seen_bonds:
            diagnostics.append("DUPLICATE_TOPOLOGY_BOND")
        seen_bonds.add(pair)
        kind = bond.get("kind")
        if kind not in {"covalent", "coordination"}:
            diagnostics.append("TOPOLOGY_BOND_KIND_INVALID")
            continue
        if kind == "covalent" and bond.get("order") not in {1, 1.5, 2, 3}:
            diagnostics.append("TOPOLOGY_COVALENT_BOND_ORDER_INVALID")
        if kind == "coordination" and atom1 not in donor_atoms and atom2 not in donor_atoms:
            diagnostics.append("COORDINATION_DONOR_NOT_DECLARED")
        distance_range = bond.get("distance_range_angstrom")
        if not isinstance(distance_range, list) or len(distance_range) != 2:
            diagnostics.append("BOND_DISTANCE_RANGE_MISSING")
            continue
        try:
            lower, upper = (float(value) for value in distance_range)
            distance = float(atoms.get_distance(atom_index[atom1], atom_index[atom2], mic=False))
        except (TypeError, ValueError, OverflowError):
            diagnostics.append("BOND_DISTANCE_RANGE_INVALID")
            continue
        if not math.isfinite(lower) or not math.isfinite(upper) or lower <= 0 or upper <= lower:
            diagnostics.append("BOND_DISTANCE_RANGE_INVALID")
        else:
            passed = lower <= distance <= upper
            if kind == "coordination":
                coordination_checks.append({
                    "atom1": atom1, "atom2": atom2, "distance_angstrom": distance,
                    "accepted_range_angstrom": [lower, upper], "passed": passed,
                })
            if not passed:
                diagnostics.append("BOND_DISTANCE_OUT_OF_RANGE")

    if (atoms_again.get_chemical_symbols() != symbols
            or len(atoms_again) != len(atoms)
            or atoms_again.pbc.tolist() != atoms.pbc.tolist()
            or any(abs(float(a) - float(b)) > 1e-12
                   for row_a, row_b in zip(atoms_again.get_positions(), positions)
                   for a, b in zip(row_a, row_b))):
        diagnostics.append("STRUCTURE_READBACK_MISMATCH")

    digest = hashlib.sha256(structure_path.read_bytes()).hexdigest()
    return {
        "status": "PASS" if not diagnostics else "FAIL",
        "diagnostics": sorted(set(diagnostics)), "atom_count": len(atoms),
        "composition": dict(counts), "formula": formula, "charge": charge,
        "pseudopotential_electron_count": electron_count, "multiplicity": multiplicity,
        "periodic": bool(atoms.pbc.any()), "overlaps": overlaps,
        "bond_count": len(bonds), "donor_atoms": donor_atoms,
        "coordination_checks": coordination_checks,
        "structure_sha256": digest,
    }


def write_validation_report(report: Mapping[str, Any], path: str | Path) -> Path:
    """Persist the exact validation report that will be registered and approved."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target
