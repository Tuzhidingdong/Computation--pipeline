"""Deterministic coordinate transforms over a supplied explicit chemical graph.

This module never infers bonds, donor atoms or missing coordinates. It only creates
candidates when the frozen project specification supplies complete topology, positions,
fragment membership and candidate transforms.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
import hashlib
import json
import math
import re

from .spec import ModelSpec


@dataclass(frozen=True)
class ModelCandidate:
    candidate_id: str
    structure_path: Path
    topology_path: Path
    metadata_path: Path
    sha256: str
    metadata: Mapping[str, Any]


class StructureWriter(Protocol):
    def write(self, path: Path, symbols: list[str], positions: list[list[float]], atom_ids: list[str]) -> None: ...


def _rotate(point, origin, axis, angle_degrees):
    norm = math.sqrt(sum(float(v) ** 2 for v in axis))
    if norm == 0:
        raise ValueError("rotation axis cannot be zero")
    ux, uy, uz = [float(v) / norm for v in axis]
    x, y, z = [float(point[i]) - float(origin[i]) for i in range(3)]
    a = math.radians(float(angle_degrees))
    c, s = math.cos(a), math.sin(a)
    dot = ux*x + uy*y + uz*z
    cross = (uy*z-uz*y, uz*x-ux*z, ux*y-uy*x)
    rotated = (
        x*c + cross[0]*s + ux*dot*(1-c),
        y*c + cross[1]*s + uy*dot*(1-c),
        z*c + cross[2]*s + uz*dot*(1-c),
    )
    return [rotated[i] + float(origin[i]) for i in range(3)]


def _ase_writer():
    try:
        from ase import Atoms
        from ase.io import write
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("ASE is required to write real model candidates") from exc

    class Writer:
        def write(self, path, symbols, positions, atom_ids):
            atoms = Atoms(symbols=symbols, positions=positions, pbc=False)
            atoms.new_array("atom_id", np.asarray(atom_ids, dtype=str))
            write(str(path), atoms, format="extxyz")
    return Writer()


def _canonical_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_candidates(
    spec: ModelSpec, output_dir: str | Path, *, writer: StructureWriter | None = None,
) -> list[ModelCandidate]:
    transforms = spec.build_constraints.get("candidate_transforms")
    if not isinstance(transforms, list) or len(transforms) != int(spec.expected["candidate_count"]):
        raise ValueError("candidate_transforms must contain exactly expected.candidate_count entries; planned candidates cannot be silently reduced")
    writer = writer or _ase_writer()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    atom_by_id = {str(atom["atom_id"]): atom for atom in spec.atoms}
    candidates = []
    seen_ids = set()
    for transform in transforms:
        candidate_id = str(transform.get("candidate_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", candidate_id):
            raise ValueError("candidate_id must be a safe filename component (letters, digits, dot, underscore, hyphen)")
        if candidate_id in seen_ids:
            raise ValueError("candidate_id values must be unique")
        seen_ids.add(candidate_id)
        fragment_id = str(transform.get("fragment_id", ""))
        fragment = spec.fragments.get(fragment_id)
        if not isinstance(fragment, Mapping) or not fragment.get("atom_ids"):
            raise ValueError(f"{candidate_id}: fragment {fragment_id!r} is not explicitly defined")
        atom_ids = list(fragment["atom_ids"])
        if len(set(atom_ids)) != len(atom_ids) or any(atom_id not in atom_by_id for atom_id in atom_ids):
            raise ValueError(f"{candidate_id}: fragment atom_ids are invalid")
        origin = transform.get("origin")
        axis = transform.get("axis")
        angle = transform.get("angle_degrees")
        translation = transform.get("translation", [0.0, 0.0, 0.0])
        if origin is None or axis is None or angle is None or len(translation) != 3:
            raise ValueError(f"{candidate_id}: origin, axis, angle_degrees and 3D translation are required")
        if len(origin) != 3 or len(axis) != 3:
            raise ValueError(f"{candidate_id}: origin and axis must each contain exactly three coordinates")
        try:
            origin = [float(value) for value in origin]
            axis = [float(value) for value in axis]
            angle = float(angle)
            translation = [float(value) for value in translation]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{candidate_id}: transform coordinates and angle must be numeric") from exc
        if not all(math.isfinite(value) for value in origin + axis + translation + [angle]):
            raise ValueError(f"{candidate_id}: transform values must all be finite")
        if math.sqrt(sum(value * value for value in axis)) == 0:
            raise ValueError(f"{candidate_id}: rotation axis cannot be zero")
        moved = {}
        for atom_id in atom_ids:
            position = atom_by_id[atom_id]["position"]
            point = _rotate(position, origin, axis, angle)
            moved[atom_id] = [point[i] + float(translation[i]) for i in range(3)]
        symbols, positions = [], []
        for atom in spec.atoms:
            atom_id = str(atom["atom_id"])
            symbols.append(str(atom["element"]))
            positions.append(moved.get(atom_id, [float(x) for x in atom["position"]]))
        folder = root / candidate_id
        folder.mkdir(parents=True, exist_ok=False)
        structure_path = folder / "structure.extxyz"
        writer.write(structure_path, symbols, positions,
                     [str(atom["atom_id"]) for atom in spec.atoms])
        topology = {
            "schema_version": "1.0.0", "model_id": spec.model_id,
            "atoms": [dict(atom, position=positions[i]) for i, atom in enumerate(spec.atoms)],
            "bonds": [dict(bond) for bond in spec.bonds],
            "fragments": dict(spec.fragments), "donor_atoms": list(spec.build_constraints.get("donor_atoms", [])),
        }
        topology_path = folder / "topology.json"
        topology_path.write_text(json.dumps(topology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metadata = {
            "schema_version": "1.0.0", "project_id": spec.project_id,
            "model_id": spec.model_id, "candidate_id": candidate_id,
            "transform": dict(transform), "random_seed": spec.build_constraints.get("random_seed"),
            "source_evidence": list(spec.evidence), "expected": dict(spec.expected),
        }
        metadata_path = folder / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        candidates.append(ModelCandidate(candidate_id, structure_path, topology_path,
                                          metadata_path, _canonical_hash(structure_path), metadata))
    return candidates
