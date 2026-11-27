"""Strict, versioned explicit atom-graph and candidate-transform contract."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ModelSpec:
    schema_version: str
    project_id: str
    model_id: str
    atoms: tuple[Mapping[str, Any], ...]
    bonds: tuple[Mapping[str, Any], ...]
    fragments: Mapping[str, Any]
    expected: Mapping[str, Any]
    build_constraints: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelSpec":
        if raw.get("schema_version") != "1.0.0":
            raise ValueError("model spec schema_version must be '1.0.0'")
        required = ("project_id", "model_id", "atoms", "bonds", "fragments", "expected", "build_constraints", "evidence")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError("model spec missing fields: " + ", ".join(missing))
        atoms = tuple(dict(item) for item in raw["atoms"])
        bonds = tuple(dict(item) for item in raw["bonds"])
        if not atoms:
            raise ValueError("explicit atom graph is empty")
        ids = [str(atom.get("atom_id", "")) for atom in atoms]
        if any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("atom_id values must be non-empty and unique")
        known = set(ids)
        for atom in atoms:
            if not atom.get("element"):
                raise ValueError(f"{atom.get('atom_id')}: element is required")
            if atom.get("position") is None:
                raise ValueError(f"{atom.get('atom_id')}: explicit 3D position is required")
            if len(atom["position"]) != 3:
                raise ValueError(f"{atom.get('atom_id')}: position must contain x,y,z")
        for bond in bonds:
            if bond.get("atom1") not in known or bond.get("atom2") not in known:
                raise ValueError("bond references an unknown atom_id")
            if bond.get("atom1") == bond.get("atom2"):
                raise ValueError("self-bonds are invalid")
            if bond.get("kind") not in {"covalent", "coordination"}:
                raise ValueError("bond.kind must be covalent or coordination")
            if bond.get("kind") == "covalent" and bond.get("order") not in {1, 1.5, 2, 3}:
                raise ValueError("covalent bond.order must be 1, 1.5, 2 or 3")
        if int(expected["atom_count"]) != len(atoms):
            raise ValueError("expected.atom_count differs from explicit atom graph")
        if int(expected["candidate_count"]) < 1:
            raise ValueError("expected.candidate_count must be >= 1")
        if not isinstance(raw["build_constraints"], Mapping):
            raise ValueError("build_constraints must be an object")
        return cls("1.0.0", str(raw["project_id"]), str(raw["model_id"]), atoms, bonds,
                   dict(raw["fragments"]), dict(raw["expected"]),
                   dict(raw["build_constraints"]), tuple(dict(x) for x in raw["evidence"]))
