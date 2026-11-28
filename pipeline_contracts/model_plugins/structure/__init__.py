"""Reusable, algorithm-backed structure preparation plugins.

The package is intentionally not imported by ProjectPipeline. Agent B can bind
these pure Mapping-in/Mapping-out entry points to ModelRecipe after review.
"""
from .adapters import (
    ase_to_pymatgen,
    build_adsorbate_candidates,
    build_molecule_conformer_from_smiles,
    build_supercell,
    find_adsorption_sites,
    generate_slabs,
    get_model_plugin_route,
    load_structure_model,
    plugin_routes,
    pymatgen_to_ase,
)
from .neb import build_neb_initial_path
from .solvent import build_explicit_solvent_box

__all__ = [
    "ase_to_pymatgen",
    "build_adsorbate_candidates",
    "build_explicit_solvent_box",
    "build_molecule_conformer_from_smiles",
    "build_neb_initial_path",
    "build_supercell",
    "find_adsorption_sites",
    "generate_slabs",
    "get_model_plugin_route",
    "load_structure_model",
    "plugin_routes",
    "pymatgen_to_ase",
]
