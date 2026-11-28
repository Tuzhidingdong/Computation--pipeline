"""ASE/pymatgen/RDKit structure adapters and explicit model-plugin routing."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any, Mapping

from .core import (
    PLUGIN_SCHEMA_VERSION,
    artifact_record,
    ase_structure_mapping,
    atoms_from_mapping,
    decision_result,
    dependency_version,
    read_ase_source,
    sha256_file,
    write_json,
)


def plugin_routes() -> dict[str, dict[str, Any]]:
    """Return capability routes without silently substituting another algorithm."""
    import importlib.util
    ase_available = importlib.util.find_spec("ase") is not None
    rdkit_available = importlib.util.find_spec("rdkit") is not None
    pymatgen_available = importlib.util.find_spec("pymatgen") is not None
    return {
        "molecule/conformer": {
            "status": "SUPPORTED" if rdkit_available and ase_available else "UNSUPPORTED",
            "provider": "RDKit ETKDG + ASE I/O",
            "entrypoint": "build_molecule_conformer_from_smiles",
            "dependencies": ["rdkit", "ase"],
        },
        "crystal/supercell": {
            "status": "SUPPORTED" if pymatgen_available and ase_available else "UNSUPPORTED",
            "provider": "pymatgen Structure.make_supercell + ASE adapter",
            "entrypoint": "build_supercell",
            "dependencies": ["pymatgen", "ase"],
        },
        "slab/surface": {
            "status": "SUPPORTED" if pymatgen_available and ase_available else "UNSUPPORTED",
            "provider": "pymatgen SlabGenerator",
            "entrypoint": "generate_slabs",
            "dependencies": ["pymatgen", "ase"],
        },
        "adsorption": {
            "status": "SUPPORTED" if pymatgen_available and ase_available else "UNSUPPORTED",
            "provider": "pymatgen AdsorbateSiteFinder",
            "entrypoint": "find_adsorption_sites / build_adsorbate_candidates",
            "dependencies": ["pymatgen", "ase"],
        },
        "interface": {
            "status": "UNSUPPORTED",
            "provider": None,
            "entrypoint": None,
            "reason": "No interface lattice-matching/strain policy is implemented; an explicit approved mismatch strategy is required.",
            "dependencies": [],
        },
        "implicit solvation": {
            "status": "UNSUPPORTED",
            "provider": None,
            "entrypoint": None,
            "reason": "Implicit-solvation models are engine- and method-specific; this structure layer does not invent a dielectric or cavity model.",
            "dependencies": [],
        },
        "explicit solvation": {
            "status": "SUPPORTED" if ase_available and shutil.which("packmol") else "UNSUPPORTED",
            "provider": "Packmol + ASE",
            "entrypoint": "build_explicit_solvent_box",
            "dependencies": ["packmol==21.2.3", "ase"],
        },
        "transition-state initial path": {
            "status": "SUPPORTED" if ase_available else "UNSUPPORTED",
            "provider": "ASE NEB + IDPP",
            "entrypoint": "build_neb_initial_path",
            "dependencies": ["ase"],
        },
    }


def get_model_plugin_route(model_type: str) -> dict[str, Any]:
    routes = plugin_routes()
    if model_type not in routes:
        return {
            "model_type": model_type,
            "status": "UNSUPPORTED",
            "reason": "No registered structure plugin for this model type",
        }
    return {"model_type": model_type, **routes[model_type]}


def load_structure_model(
    source: Mapping[str, Any],
    *,
    structure_type: str = "atomistic",
) -> dict[str, Any]:
    """Load a SHA-pinned structure through ASE into the common ModelRecipe Mapping."""
    atoms, source_record = read_ase_source(source, "structure_source")
    mapping = ase_structure_mapping(
        atoms,
        structure_type=structure_type,
        source=source_record,
        metadata={"coordinate_units": "angstrom", "input_reader": "ASE"},
    )
    return mapping


def ase_to_pymatgen(atoms: Any):
    """Convert periodic ASE Atoms into pymatgen Structure without changing coordinates."""
    try:
        from pymatgen.core import Lattice, Structure
    except ImportError as exc:
        raise RuntimeError("pymatgen is optional; install the structure plugin requirements") from exc
    if not all(bool(flag) for flag in atoms.pbc):
        raise ValueError("pymatgen Structure conversion requires three-dimensional periodicity")
    if abs(float(atoms.cell.volume)) <= 1e-12:
        raise ValueError("periodic ASE structure has a zero-volume cell")
    return Structure(
        Lattice(atoms.cell.array),
        atoms.get_chemical_symbols(),
        atoms.get_positions(),
        coords_are_cartesian=True,
    )


def pymatgen_to_ase(structure: Any):
    """Convert pymatgen Structure/Molecule coordinates to ASE Atoms."""
    try:
        from ase import Atoms
        from pymatgen.core import Structure
    except ImportError as exc:
        raise RuntimeError("ASE and pymatgen are required for this conversion") from exc
    if isinstance(structure, Structure):
        return Atoms(
            symbols=[site.specie.symbol for site in structure],
            positions=structure.cart_coords,
            cell=structure.lattice.matrix,
            pbc=True,
        )
    # Molecule-like pymatgen objects have species and Cartesian coordinates but no cell.
    return Atoms(
        symbols=[site.specie.symbol if hasattr(site, "specie") else str(site.species_string)
                 for site in structure],
        positions=structure.cart_coords,
        pbc=False,
    )


def _read_pymatgen_structure(source: Mapping[str, Any], field_name: str = "structure"):
    from .core import validate_source_spec
    path, digest, issues = validate_source_spec(source, field_name)
    if issues:
        raise ValueError("; ".join(issues))
    try:
        from pymatgen.core import Structure
    except ImportError as exc:
        raise RuntimeError("pymatgen is optional; install pipeline_contracts/model_plugins/structure/requirements.txt") from exc
    structure = Structure.from_file(str(path))
    if len(structure) == 0:
        raise ValueError(f"{field_name} contains zero sites")
    return structure, {
        "path": str(path),
        "sha256": digest,
        "size_bytes": path.stat().st_size,
    }


def build_supercell(
    source: Mapping[str, Any],
    supercell_matrix: list[list[int]],
) -> dict[str, Any]:
    """Use pymatgen's mature Structure.make_supercell operation."""
    try:
        structure, source_record = _read_pymatgen_structure(source, "crystal_source")
        import numpy as np
        if (
            not isinstance(supercell_matrix, (list, tuple))
            or len(supercell_matrix) != 3
            or any(not isinstance(row, (list, tuple)) or len(row) != 3 for row in supercell_matrix)
            or any(isinstance(value, bool) or not isinstance(value, int) for row in supercell_matrix for value in row)
        ):
            return decision_result("supercell_matrix must contain nine explicit integers", plugin="pymatgen_supercell")
        matrix = np.asarray(supercell_matrix, dtype=int)
        if matrix.shape != (3, 3) or abs(round(float(np.linalg.det(matrix)))) < 1:
            return decision_result("supercell_matrix must be an explicit nonsingular 3x3 integer matrix", plugin="pymatgen_supercell")
        structure.make_supercell(matrix)
        atoms = pymatgen_to_ase(structure)
        mapping = ase_structure_mapping(
            atoms,
            structure_type="crystal/supercell",
            source=source_record,
            metadata={
                "builder": "pymatgen.Structure.make_supercell",
                "supercell_matrix": matrix.tolist(),
                "parent_site_count": len(structure) // abs(round(float(np.linalg.det(matrix)))),
            },
        )
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_supercell",
            "status": "STRUCTURE_BUILT_FOR_REVIEW",
            "structure": mapping,
            "provenance": {
                "source_sha256": source_record["sha256"],
                "pymatgen_version": dependency_version("pymatgen", "pymatgen"),
                "ase_version": dependency_version("ase", "ase"),
            },
        }
    except Exception as exc:
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_supercell",
            "status": "FAILED",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }


def generate_slabs(
    source: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate symmetry-distinct surfaces via pymatgen SlabGenerator."""
    required = (
        "miller_index", "min_slab_size_angstrom", "min_vacuum_size_angstrom",
        "center_slab", "primitive", "lll_reduce", "reorient_lattice",
        "symmetrically_distinct",
    )
    missing = [key for key in required if key not in recipe]
    if missing:
        return decision_result(
            "slab recipe lacks explicit settings: " + ", ".join(missing),
            plugin="pymatgen_slab_generator",
        )
    try:
        miller = recipe["miller_index"]
        if not isinstance(miller, (list, tuple)) or len(miller) != 3 or any(
            isinstance(x, bool) or not isinstance(x, int) for x in miller
        ):
            return decision_result("miller_index must be an explicit three-integer list", plugin="pymatgen_slab_generator")
        if not isinstance(recipe["center_slab"], bool) or not isinstance(recipe["primitive"], bool) or not isinstance(recipe["lll_reduce"], bool) or not isinstance(recipe["reorient_lattice"], bool) or not isinstance(recipe["symmetrically_distinct"], bool):
            return decision_result("slab boolean settings must be explicitly true/false", plugin="pymatgen_slab_generator")
        if float(recipe["min_slab_size_angstrom"]) <= 0 or float(recipe["min_vacuum_size_angstrom"]) < 0:
            return decision_result("slab and vacuum sizes must be positive/non-negative explicit values", plugin="pymatgen_slab_generator")
        structure, source_record = _read_pymatgen_structure(source, "bulk_structure")
        from pymatgen.core.surface import SlabGenerator
        generator = SlabGenerator(
            initial_structure=structure,
            miller_index=tuple(miller),
            min_slab_size=float(recipe["min_slab_size_angstrom"]),
            min_vacuum_size=float(recipe["min_vacuum_size_angstrom"]),
            lll_reduce=recipe["lll_reduce"],
            center_slab=recipe["center_slab"],
            primitive=recipe["primitive"],
            reorient_lattice=recipe["reorient_lattice"],
        )
        slabs = generator.get_slabs(symmetrically_distinct=recipe["symmetrically_distinct"])
        candidates = []
        for index, slab in enumerate(slabs):
            atoms = pymatgen_to_ase(slab)
            candidates.append(ase_structure_mapping(
                atoms,
                structure_type="slab/surface",
                source=source_record,
                metadata={
                    "builder": "pymatgen.SlabGenerator",
                    "candidate_index": index,
                    "miller_index": list(miller),
                    "min_slab_size_angstrom": float(recipe["min_slab_size_angstrom"]),
                    "min_vacuum_size_angstrom": float(recipe["min_vacuum_size_angstrom"]),
                    "center_slab": recipe["center_slab"],
                    "primitive": recipe["primitive"],
                    "lll_reduce": recipe["lll_reduce"],
                    "reorient_lattice": recipe["reorient_lattice"],
                    "symmetrically_distinct": recipe["symmetrically_distinct"],
                },
            ))
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_slab_generator",
            "status": "CANDIDATES_READY_FOR_REVIEW" if candidates else "NO_CANDIDATES",
            "source": source_record,
            "candidates": candidates,
            "provenance": {
                "pymatgen_version": dependency_version("pymatgen", "pymatgen"),
                "ase_version": dependency_version("ase", "ase"),
            },
        }
    except Exception as exc:
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_slab_generator",
            "status": "FAILED",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }


def find_adsorption_sites(
    slab_source: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Enumerate top/bridge/hollow candidates through pymatgen AdsorbateSiteFinder."""
    required = ("height_angstrom", "distance_angstrom", "positions", "symm_reduce", "near_reduce")
    missing = [key for key in required if key not in recipe]
    if missing:
        return decision_result(
            "adsorption recipe lacks explicit settings: " + ", ".join(missing),
            plugin="pymatgen_adsorption_sites",
        )
    if not isinstance(recipe["positions"], list) or not recipe["positions"]:
        return decision_result("positions must explicitly select adsorption site classes", plugin="pymatgen_adsorption_sites")
    if isinstance(recipe["symm_reduce"], bool) or isinstance(recipe["near_reduce"], bool):
        return decision_result("symm_reduce and near_reduce must be explicit numeric thresholds", plugin="pymatgen_adsorption_sites")
    try:
        slab, source_record = _read_pymatgen_structure(slab_source, "slab_source")
        from pymatgen.core.adsorption import AdsorbateSiteFinder
        finder = AdsorbateSiteFinder(slab, height=float(recipe["height_angstrom"]))
        sites = finder.find_adsorption_sites(
            distance=float(recipe["distance_angstrom"]),
            positions=list(recipe["positions"]),
            symm_reduce=float(recipe["symm_reduce"]),
            near_reduce=float(recipe["near_reduce"]),
        )
        candidates = []
        for site_type, coordinates in sites.items():
            for index, coordinate in enumerate(coordinates):
                record = {
                    "site_type": site_type,
                    "site_index": index,
                    "coordinate_angstrom": [float(x) for x in coordinate],
                    "source_sha256": source_record["sha256"],
                    "builder": "pymatgen.AdsorbateSiteFinder.find_adsorption_sites",
                    "settings": jsonable(recipe),
                }
                record["candidate_id"] = hashlib.sha256(
                    json.dumps(record, sort_keys=True).encode("utf-8")
                ).hexdigest()[:16]
                candidates.append(record)
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_adsorption_sites",
            "status": "CANDIDATES_READY_FOR_REVIEW" if candidates else "NO_CANDIDATES",
            "source": source_record,
            "candidates": candidates,
            "provenance": {
                "pymatgen_version": dependency_version("pymatgen", "pymatgen"),
            },
        }
    except Exception as exc:
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_adsorption_sites",
            "status": "FAILED",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }



def build_adsorbate_candidates(
    slab_source: Mapping[str, Any],
    adsorbate_mapping: Mapping[str, Any],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Place an explicit adsorbate at pymatgen-enumerated sites.

    No adsorption height, orientation, repeat, or site selection is guessed.
    The input adsorbate must already have explicit species and Cartesian
    coordinates in Angstrom.
    """
    required = (
        "height_angstrom", "distance_angstrom", "positions", "symm_reduce",
        "near_reduce", "translate", "reorient", "repeat",
    )
    missing = [key for key in required if key not in recipe]
    if missing:
        return decision_result(
            "adsorbate recipe lacks explicit settings: " + ", ".join(missing),
            plugin="pymatgen_adsorbate_builder",
        )
    if not isinstance(adsorbate_mapping, Mapping):
        return decision_result("adsorbate_mapping must be an explicit structure Mapping", plugin="pymatgen_adsorbate_builder")
    species = adsorbate_mapping.get("species")
    coordinates = adsorbate_mapping.get("positions_angstrom")
    if not isinstance(species, list) or not species or not isinstance(coordinates, list) or len(coordinates) != len(species):
        return decision_result("adsorbate_mapping requires matching non-empty species and positions_angstrom arrays", plugin="pymatgen_adsorbate_builder")
    if type(recipe["translate"]) is not bool or type(recipe["reorient"]) is not bool:
        return decision_result("translate and reorient must be explicit booleans", plugin="pymatgen_adsorbate_builder")
    repeat = recipe["repeat"]
    if repeat is not None and (
        not isinstance(repeat, (list, tuple)) or len(repeat) != 3
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in repeat)
    ):
        return decision_result("repeat must be null or an explicit three-positive-integer list", plugin="pymatgen_adsorbate_builder")
    try:
        slab, source_record = _read_pymatgen_structure(slab_source, "slab_source")
        from pymatgen.core import Molecule
        from pymatgen.core.adsorption import AdsorbateSiteFinder
        molecule = Molecule(species, coordinates)
        finder = AdsorbateSiteFinder(slab, height=float(recipe["height_angstrom"]))
        sites = finder.find_adsorption_sites(
            distance=float(recipe["distance_angstrom"]),
            positions=list(recipe["positions"]),
            symm_reduce=float(recipe["symm_reduce"]),
            near_reduce=float(recipe["near_reduce"]),
        )
        candidates = []
        for site_type, coordinates_list in sites.items():
            for site_index, coordinate in enumerate(coordinates_list):
                adsorbed = finder.add_adsorbate(
                    molecule,
                    coordinate,
                    repeat=repeat,
                    translate=recipe["translate"],
                    reorient=recipe["reorient"],
                )
                atoms = pymatgen_to_ase(adsorbed)
                metadata = {
                    "builder": "pymatgen.AdsorbateSiteFinder.add_adsorbate",
                    "site_type": site_type,
                    "site_index": site_index,
                    "adsorption_coordinate_angstrom": [float(x) for x in coordinate],
                    "adsorbate_structure": jsonable(adsorbate_mapping),
                    "settings": jsonable(recipe),
                    "source_sha256": source_record["sha256"],
                }
                structure_mapping = ase_structure_mapping(
                    atoms,
                    structure_type="adsorption",
                    source=source_record,
                    metadata=metadata,
                )
                candidate_id = hashlib.sha256(
                    json.dumps(structure_mapping, sort_keys=True).encode("utf-8")
                ).hexdigest()[:16]
                candidates.append({"candidate_id": candidate_id, "structure": structure_mapping})
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_adsorbate_builder",
            "status": "CANDIDATES_READY_FOR_REVIEW" if candidates else "NO_CANDIDATES",
            "source": source_record,
            "candidates": candidates,
            "provenance": {
                "pymatgen_version": dependency_version("pymatgen", "pymatgen"),
                "ase_version": dependency_version("ase", "ase"),
            },
        }
    except Exception as exc:
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "pymatgen_adsorbate_builder",
            "status": "FAILED",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

def build_molecule_conformer_from_smiles(
    smiles: str,
    *,
    random_seed: int,
    output_path: str | Path,
    optimize: bool = False,
    force_field: str | None = None,
) -> dict[str, Any]:
    """Optional organic conformer entry point using RDKit ETKDG; no metal chemistry."""
    if not isinstance(smiles, str) or not smiles.strip():
        return decision_result("SMILES must be explicit", plugin="rdkit_conformer")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed <= 0:
        return decision_result("random_seed must be an explicit positive integer", plugin="rdkit_conformer")
    if type(optimize) is not bool:
        return decision_result("optimize must explicitly be true or false", plugin="rdkit_conformer")
    if optimize and force_field not in {"MMFF94", "UFF"}:
        return decision_result("force_field must explicitly be MMFF94 or UFF when optimize=true", plugin="rdkit_conformer")
    try:
        from rdkit import Chem, rdBase
        from rdkit.Chem import AllChem, Descriptors
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            return decision_result("SMILES could not be parsed by RDKit", plugin="rdkit_conformer")
        molecule = Chem.AddHs(molecule)
        params = AllChem.ETKDGv3()
        params.randomSeed = int(random_seed)
        conformer_id = AllChem.EmbedMolecule(molecule, params)
        if conformer_id < 0:
            return {
                "schema_version": PLUGIN_SCHEMA_VERSION,
                "plugin": "rdkit_conformer",
                "status": "FAILED",
                "errors": ["RDKit ETKDG failed to generate a conformer"],
            }
        optimization = None
        if optimize:
            if force_field == "MMFF94":
                props = AllChem.MMFFGetMoleculeProperties(molecule)
                if props is None:
                    return decision_result("MMFF94 parameters are unavailable for this molecule; choose an explicitly supported force field", plugin="rdkit_conformer")
                optimization = {"force_field": force_field, "return_code": AllChem.MMFFOptimizeMolecule(molecule, mmffVariant="MMFF94")}
            else:
                if not AllChem.UFFHasMolecule(molecule):
                    return decision_result("UFF parameters are unavailable for this molecule", plugin="rdkit_conformer")
                optimization = {"force_field": force_field, "return_code": AllChem.UFFOptimizeMolecule(molecule)}
        from ase import Atoms
        from ase.io import write
        conformer = molecule.GetConformer(conformer_id)
        coordinates = conformer.GetPositions()
        symbols = [atom.GetSymbol() for atom in molecule.GetAtoms()]
        atoms = Atoms(symbols=symbols, positions=coordinates)
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        write(str(target), atoms, format="extxyz")
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "rdkit_conformer",
            "status": "STRUCTURE_BUILT_FOR_REVIEW",
            "structure": ase_structure_mapping(
                atoms,
                structure_type="molecule/conformer",
                metadata={
                    "smiles": Chem.MolToSmiles(Chem.RemoveHs(molecule)),
                    "random_seed": random_seed,
                    "conformer_id": conformer_id,
                    "optimization": optimization,
                    "warning": "A conformer is a starting geometry; it is not a conformer ensemble or a validated transition-metal coordination structure.",
                },
            ),
            "artifacts": [artifact_record(target, target.parent)],
            "provenance": {
                "rdkit_version": rdBase.rdkitVersion,
                "ase_version": dependency_version("ase", "ase"),
                "molecular_weight_amu": float(Descriptors.MolWt(Chem.RemoveHs(molecule))),
                "random_seed": random_seed,
            },
        }
    except Exception as exc:
        return {
            "schema_version": PLUGIN_SCHEMA_VERSION,
            "plugin": "rdkit_conformer",
            "status": "FAILED",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
