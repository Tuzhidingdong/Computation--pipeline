"""Shared I/O, hashing, validation, and JSON helpers for structure plugins.

No scientific construction algorithms are implemented here. Geometry algorithms
are delegated to ASE, pymatgen, RDKit, and Packmol through their public APIs.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

PLUGIN_SCHEMA_VERSION = "1.0.0"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dependency_version(distribution: str, import_name: str | None = None) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        if import_name:
            try:
                module = __import__(import_name)
                return str(getattr(module, "__version__", "installed-version-unknown"))
            except Exception:
                pass
        return "not-installed"


def jsonable(value: Any) -> Any:
    """Convert common NumPy/ASE values to JSON-safe Python primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "tolist"):
        return jsonable(value.tolist())
    if hasattr(value, "todict"):
        return jsonable(value.todict())
    return str(value)


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(jsonable(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def artifact_record(path: str | Path, root: str | Path) -> dict[str, Any]:
    target = Path(path)
    base = Path(root)
    return {
        "path": target.relative_to(base).as_posix(),
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def decision_result(*reasons: str, plugin: str) -> dict[str, Any]:
    return {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin": plugin,
        "status": "NEEDS_DECISION",
        "decision_required": list(reasons),
        "artifacts": [],
        "provenance": {},
    }


def failed_result(reason: str, *, plugin: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin": plugin,
        "status": "FAILED",
        "errors": [reason],
        "artifacts": [],
        "provenance": {},
    }
    if output_dir is not None:
        result["output_dir"] = str(output_dir)
    return result


def validate_source_spec(source: Any, field_name: str) -> tuple[Path | None, str | None, list[str]]:
    """Validate local path/SHA and an optional paired upstream Artifact identity.

    Optional artifact_id and artifact_sha256 preserve compatibility with local
    {path, sha256} callers. When present, the Artifact digest must exactly equal
    the SHA-256 of the verified local bytes. This function creates no output.
    """
    issues: list[str] = []
    if not isinstance(source, Mapping):
        return None, None, [f"{field_name} must be an object containing path and sha256"]
    raw_path = source.get("path")
    expected = source.get("sha256")
    artifact_id = source.get("artifact_id")
    artifact_digest = source.get("artifact_sha256")
    has_artifact_id = artifact_id is not None
    has_artifact_digest = artifact_digest is not None
    if has_artifact_id != has_artifact_digest:
        issues.append(
            f"{field_name}.artifact_id and {field_name}.artifact_sha256 must be provided together"
        )
    elif has_artifact_id:
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            issues.append(f"{field_name}.artifact_id must be a non-empty string identifier")
        if not validate_sha256(artifact_digest):
            issues.append(f"{field_name}.artifact_sha256 must be a 64-character hexadecimal SHA-256")

    if not isinstance(raw_path, str) or not raw_path.strip():
        issues.append(f"{field_name}.path is missing")
        path = None
    else:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            issues.append(f"{field_name}.path does not exist or is not a file: {raw_path}")

    expected_valid = isinstance(expected, str) and len(expected) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in expected
    )
    if not expected_valid:
        issues.append(f"{field_name}.sha256 must be an explicit 64-character hexadecimal digest")

    if path is not None and path.is_file():
        actual = sha256_file(path)
        if expected_valid and actual.lower() != expected.lower():
            issues.append(f"{field_name}.sha256 does not match the source file")
        if has_artifact_id and has_artifact_digest and validate_sha256(artifact_digest):
            if artifact_digest != actual:
                issues.append(
                    f"{field_name}.artifact_sha256 does not exactly match the verified source file SHA-256"
                )
    return path, expected.lower() if expected_valid else None, issues


def read_ase_source(source: Mapping[str, Any], field_name: str):
    """Read one hash-pinned structure using ASE; return Atoms and verified source info."""
    path, expected, issues = validate_source_spec(source, field_name)
    if issues:
        raise ValueError("; ".join(issues))
    try:
        from ase.io import read
    except ImportError as exc:
        raise RuntimeError("ASE is required; install the structure plugin requirements") from exc
    atoms = read(str(path), index=0)
    if len(atoms) == 0:
        raise ValueError(f"{field_name} contains zero atoms")
    if not all(math.isfinite(float(x)) for x in atoms.positions.flatten()):
        raise ValueError(f"{field_name} contains non-finite coordinates")
    source_record = {
        "path": str(path),
        "sha256": expected,
        "size_bytes": path.stat().st_size,
    }
    if source.get("artifact_id") is not None:
        source_record["artifact_id"] = source["artifact_id"]
        source_record["artifact_sha256"] = source["artifact_sha256"]
    return atoms, source_record


def ase_structure_mapping(atoms: Any, *, structure_type: str = "atomistic",
                          source: Mapping[str, Any] | None = None,
                          metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Convert ASE Atoms to a stable JSON Mapping for ModelRecipe hand-off."""
    arrays = {}
    for key, value in getattr(atoms, "arrays", {}).items():
        if key not in {"numbers", "positions"}:
            arrays[key] = jsonable(value)
    result = {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "backend": "ase",
        "structure_type": structure_type,
        "atom_count": len(atoms),
        "species": list(atoms.get_chemical_symbols()),
        "positions_angstrom": jsonable(atoms.get_positions()),
        "cell_angstrom": jsonable(atoms.cell.array),
        "periodic_boundary_conditions": jsonable(atoms.pbc),
        "arrays": arrays,
        "constraints": jsonable([constraint.todict() for constraint in atoms.constraints]),
    }
    if source is not None:
        result["source"] = jsonable(source)
    if metadata is not None:
        result["metadata"] = jsonable(metadata)
    return result


def atoms_from_mapping(mapping: Mapping[str, Any]):
    """Create ASE Atoms from the common JSON structure Mapping."""
    try:
        from ase import Atoms
    except ImportError as exc:
        raise RuntimeError("ASE is required; install the structure plugin requirements") from exc
    species = mapping.get("species")
    positions = mapping.get("positions_angstrom")
    if not isinstance(species, list) or not species:
        raise ValueError("structure Mapping requires a non-empty species list")
    if not isinstance(positions, list) or len(positions) != len(species):
        raise ValueError("species and positions_angstrom must have equal lengths")
    cell = mapping.get("cell_angstrom", [[0, 0, 0]] * 3)
    pbc = mapping.get("periodic_boundary_conditions", [False, False, False])
    atoms = Atoms(symbols=species, positions=positions, cell=cell, pbc=pbc)
    arrays = mapping.get("arrays", {})
    for name, values in arrays.items():
        if name in {"numbers", "positions"}:
            continue
        atoms.new_array(str(name), values)
    return atoms


def copy_verified_source(source_path: Path, source_sha: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    copied_sha = sha256_file(destination)
    if copied_sha != source_sha:
        raise IOError(f"copied source hash changed for {source_path}")
    return {
        "path": destination.as_posix(),
        "sha256": copied_sha,
        "size_bytes": destination.stat().st_size,
    }


def executable_version(executable: str, distribution: str | None = None) -> dict[str, Any]:
    """Capture package metadata, or a bounded --version probe for other tools."""
    package_version = dependency_version(distribution, distribution) if distribution else "not-associated"
    if distribution == "packmol" and package_version != "not-installed":
        # The Packmol 21.2.3 CLI does not implement --version. Its Python
        # distribution pins the bundled executable and provides authoritative
        # version metadata; use that rather than invoking an invalid CLI option.
        return {
            "version": package_version,
            "package_version": package_version,
            "probe": {
                "command": ["python", "-m", "importlib.metadata", "version", "packmol"],
                "returncode": 0,
                "output": f"Packmol executable supplied by Python distribution packmol=={package_version}",
            },
        }
    probe: dict[str, Any] = {"command": [executable, "--version"], "returncode": None, "output": ""}
    import subprocess
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        probe.update({
            "returncode": completed.returncode,
            "output": (completed.stdout + completed.stderr).strip()[:4000],
        })
    except Exception as exc:
        probe["output"] = f"version probe failed: {type(exc).__name__}: {exc}"
    discovered = probe["output"] or ""
    version = package_version if package_version not in {"not-installed", "not-associated"} else "unknown"
    import re
    match = re.search(r"\b\d+\.\d+(?:\.\d+)?\b", discovered)
    if match:
        version = match.group(0)
    return {"version": version, "package_version": package_version, "probe": probe}


def validate_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )
