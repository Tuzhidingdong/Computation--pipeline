"""Independent model integrity, composition, electron-parity and geometry checks."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import math


def validate_candidate(
    structure_path: str | Path, topology_path: str | Path, expected: Mapping[str, Any],
    *, pseudopotential_valence: Mapping[str, int], minimum_distance_angstrom: float = 0.65,
) -> dict:
    try:
        from ase.io import read
    except ImportError as exc:
        raise RuntimeError("ASE is required for candidate validation") from exc
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
    charge = expected.get("charge")
    if not isinstance(charge, int):
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
    if not isinstance(multiplicity, int) or multiplicity < 1:
        diagnostics.append("SPIN_MULTIPLICITY_NOT_EXPLICIT")
    elif electron_count is not None and electron_count % 2 != (multiplicity + 1) % 2:
        diagnostics.append("ELECTRON_SPIN_PARITY_MISMATCH")

    n = len(atoms)
    overlaps = []
    for i in range(n):
        for j in range(i + 1, n):
            distance = float(atoms.get_distance(i, j, mic=False))
            if distance < minimum_distance_angstrom:
                overlaps.append({"i": i, "j": j, "distance_angstrom": distance})
    if overlaps:
        diagnostics.append("ATOMIC_OVERLAP")
    atom_ids = [str(item.get("atom_id", "")) for item in topology.get("atoms", [])]
    if len(atom_ids) != len(atoms) or len(set(atom_ids)) != len(atom_ids):
        diagnostics.append("TOPOLOGY_ATOM_MAPPING_INVALID")
    known = set(atom_ids)
    for bond in topology.get("bonds", []):
        if bond.get("atom1") not in known or bond.get("atom2") not in known:
            diagnostics.append("TOPOLOGY_BOND_ENDPOINT_MISSING")
            break
    donor_atoms = topology.get("donor_atoms", [])
    if any(item not in known for item in donor_atoms):
        diagnostics.append("DONOR_ATOM_MAPPING_INVALID")
    if len(atoms_again) != len(atoms):
        diagnostics.append("STRUCTURE_READBACK_MISMATCH")
    digest = hashlib.sha256(structure_path.read_bytes()).hexdigest()
    return {
        "status": "PASS" if not diagnostics else "FAIL",
        "diagnostics": sorted(set(diagnostics)), "atom_count": len(atoms),
        "composition": dict(counts), "formula": formula, "charge": charge,
        "pseudopotential_electron_count": electron_count, "multiplicity": multiplicity,
        "periodic": bool(atoms.pbc.any()), "overlaps": overlaps,
        "bond_count": len(topology.get("bonds", [])), "donor_atoms": donor_atoms,
        "structure_sha256": digest,
    }


def write_validation_report(report: Mapping[str, Any], path: str | Path) -> Path:
    """Persist the exact validation report that will be registered and approved."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2) + "\\n",
                      encoding="utf-8")
    return target
