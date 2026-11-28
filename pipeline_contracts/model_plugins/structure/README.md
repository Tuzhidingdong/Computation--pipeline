# Reusable Structure / Model Plugins

This package contains **independent structure-preparation functions**. It does not import or modify ProjectPipeline, schemas, the CLI, scientific method planning, or HPC execution. Functions accept JSON-compatible Mapping inputs and return JSON-compatible Mapping results that Agent B can bind to ModelRecipe after interface review.

## Public API

~~~python
from pipeline_contracts.model_plugins.structure import (
    build_explicit_solvent_box,
    build_neb_initial_path,
    get_model_plugin_route,
    load_structure_model,
)

route = get_model_plugin_route("explicit solvation")
~~~

The functions are not connected to the Pipeline workflow automatically. They create local files only when explicit inputs pass preflight.

## 1. Explicit solvent packing — Packmol + ASE

### Required Mapping

~~~python
recipe = {
    "solute": {
        "path": "inputs/solute.extxyz",
        "sha256": "<64-char SHA-256 of exact source bytes>",
    },
    "solvents": [
        {
            "id": "water",
            "path": "inputs/water.xyz",
            "sha256": "<64-char SHA-256>",
            "count": 40,
        }
    ],
    "box": {
        "bounds_angstrom": [[0.0, 0.0, 0.0], [18.0, 18.0, 18.0]],
        "pbc": [True, True, True],
    },
    "distance_tolerance_angstrom": 1.2,
    "random_seed": 20261128,
    "output_format": "extxyz",
    "validation": {
        "minimum_inter_molecular_distance_angstrom": 0.7,
    },
}
result = build_explicit_solvent_box(recipe, "runs/solvent_box")
~~~

Supported output targets are xyz, pdb, and extxyz. Packmol writes an XYZ intermediate; ASE writes the requested final format. XYZ cell/PBC values are also recorded in run_manifest.json.

The solute is placed as one fixed structure and every solvent template is packed as a molecular species. Source coordinates are never guessed or regenerated. For fully periodic boxes with a non-zero lower bound, the plugin explicitly translates input templates into a zero-origin cell and records coordinate_origin_shift_angstrom. Only all-periodic or all-nonperiodic boxes are accepted; partial periodicity is returned as NEEDS_DECISION because the Packmol cell contract is three-dimensional.

Every input structure requires an exact source path and matching SHA-256. Every solvent species requires a positive integer count, unless a single-solvent density recipe is explicitly supplied:

~~~python
"box": {
    "bounds_angstrom": [[0, 0, 0], [20, 20, 20]],
    "pbc": [True, True, True],
    "target_density_g_cm3": 0.997,
    "accessible_volume_angstrom3": 8000.0,
    "molecule_count_rounding": "nearest",
}
~~~

Density-based mode accepts one solvent species only. The accessible volume and rounding policy (floor, nearest, or ceil) are explicit inputs. The module computes the molecule count from the actual template molecular mass; it does not guess composition or accessible volume. Multi-component mixtures must specify each exact molecule count.

Preflight failures such as missing count/density, missing SHA, missing seed, unknown output format, partial PBC, or missing QC threshold return NEEDS_DECISION before creating the output directory.

### Output

The successful result uses:

- status = VALIDATED_INITIAL_STRUCTURE
- structure_state = VALIDATED_INITIAL_STRUCTURE
- equilibration_status = PACKED_NOT_EQUILIBRATED

The output directory retains original source copies under inputs/, normalized Packmol templates, packmol.inp, packmol.log, packed.xyz, the requested output structure, and run_manifest.json. Every listed artifact has a SHA-256. Provenance includes source digests, Packmol version/probe, ASE version, tolerance and random seed.

The overlap check uses ASE's neighbour-list implementation and the explicitly supplied minimum_inter_molecular_distance_angstrom. It excludes atom pairs belonging to the same molecule. A successful result means no inter-molecular pair was found below the declared severe-overlap threshold; it does not claim a full minimum-distance distribution beyond that threshold.

**Scientific boundary:** Packmol creates an initial geometric packing. It does not equilibrate solvent, minimize a force field, establish stable solvent structure, run AIMD, or validate thermodynamics. PACKED_NOT_EQUILIBRATED remains recorded even when the initial geometry passes QC.

## 2. NEB initial path — ASE NEB + IDPP

### Required Mapping

Both endpoint arguments are source records with path and exact sha256. The recipe must carry:

~~~python
recipe = {
    "atom_mapping_initial_to_final": [0, 1, 2],
    "number_of_images": 5,
    "endpoint_context": {
        "initial": {
            "charge": 0,
            "spin_multiplicity": 1,
            "constraints": [],
            "method_fingerprint": {"engine": "CP2K", "xc": "PBE", "cutoff_ry": 500},
        },
        "final": {
            "charge": 0,
            "spin_multiplicity": 1,
            "constraints": [],
            "method_fingerprint": {"engine": "CP2K", "xc": "PBE", "cutoff_ry": 500},
        },
    },
    "idpp": {
        "steps": 100,
        "fmax_angstrom_per_step": 0.05,
        "mic": False,
    },
    "validation": {
        "minimum_pair_distance_angstrom": 0.55,
    },
}
result = build_neb_initial_path(
    {"path": "inputs/initial.extxyz", "sha256": "<initial SHA-256>"},
    {"path": "inputs/final.extxyz", "sha256": "<final SHA-256>"},
    recipe,
    "runs/neb_initial_path",
)
~~~

atom_mapping_initial_to_final is a complete bijection from each initial atom index to its corresponding final-source atom index. The plugin validates the bijection and each mapped element pair first, then reorders the final endpoint strictly with that mapping. Initial and final source files are preserved byte-for-byte with their original SHA-256 values. No distance-based atom matching, element sorting, or automatic mapping is attempted.

Endpoint atom counts, cell and PBC must match. Charge, spin multiplicity and the non-empty method fingerprint must be explicitly supplied and identical. Each source endpoint's ASE constraints must match its own endpoint_context record. For a non-identity mapping, the plugin deep-copies every final constraint and calls its ASE index_shuffle implementation with the explicit permutation. It then requires the remapped final constraints to match the initial constraints. If a constraint does not implement a safe remap, remapping raises, or the canonical constraints differ, the function returns NEEDS_DECISION before creating the output directory; no constraint is dropped or silently changed. Identity mapping preserves constraints without invoking a reordering operation.

Missing mapping/image count/context/IDPP controls/geometry threshold, ambiguous scope, or endpoint mismatch returns NEEDS_DECISION before creating the output directory.

### Output and boundary

A successful path has status = INITIAL_PATH_READY_FOR_REVIEW. It stores the original endpoint files, ASE IDPP trajectory/log, each images/image_NNN.extxyz, initial_path.extxyz, and path_manifest.json, with file hashes and source hashes.

The interpolation method is ase.mep.neb.idpp_interpolate, with the NEB force-projection method explicitly pinned to improvedtangent (not an ASE default), plus ASE version, image count, atom map, settings, cell/PBC and method fingerprint.

**Scientific boundary:** this is only an IDPP-improved initial guess. It is not a converged NEB, transition state, Dimer result, frequency result, or IRC pathway. No production calculator or HPC task is invoked.

## 3. Shared ASE / pymatgen / RDKit route

load_structure_model({"path": ..., "sha256": ...}) returns a canonical Mapping:

- species
- positions_angstrom
- cell_angstrom
- periodic_boundary_conditions
- arrays
- constraints
- source path and SHA-256

atoms_from_mapping, ase_to_pymatgen, and pymatgen_to_ase provide explicit conversion entry points. Pymatgen conversion to a periodic Structure requires all three PBC axes and a nonzero cell.

Reusable routes:

| Model type | Provider | Entry point / status |
|---|---|---|
| molecule/conformer | RDKit ETKDG + ASE | build_molecule_conformer_from_smiles |
| crystal/supercell | pymatgen + ASE | build_supercell |
| slab/surface | pymatgen SlabGenerator | generate_slabs |
| adsorption sites | pymatgen AdsorbateSiteFinder | find_adsorption_sites |
| adsorbate placement | pymatgen AdsorbateSiteFinder.add_adsorbate | build_adsorbate_candidates |
| interface | no registered algorithm/policy | UNSUPPORTED |
| implicit solvation | engine-specific, outside structure preparation | UNSUPPORTED |
| explicit solvation | Packmol + ASE | build_explicit_solvent_box |
| transition-state initial path | ASE NEB + IDPP | build_neb_initial_path |

For pymatgen surface generation, Miller index, slab/vacuum thicknesses, centering, primitive setting, lattice reduction, orientation and symmetry policy are required explicitly. Adsorption site class, height/distance, symmetry/near-site reductions, adsorbate coordinates, translation/reorientation and repeat are also explicit. Candidate records retain source SHA and construction metadata. Unsupported route types are never silently mapped to another plugin.

## 4. Dependencies and licenses

Install the optional structure dependency set from this directory:

~~~bash
python -m pip install -r pipeline_contracts/model_plugins/structure/requirements.txt
~~~

| Dependency | Use | License / note |
|---|---|---|
| Packmol 21.2.3 | Molecular packing executable | MIT. The m3g/packmol GitHub repository was archived read-only on 2026-11-17; its README points to a complete rewrite as Packmol.jl. This adapter pins the Python-distributed legacy executable 21.2.3; review maintenance/security status before future upgrades. |
| ASE >=3.23 | Atom model, file I/O, neighbour-list QC, NEB and IDPP | GNU LGPL. |
| pymatgen >=2024.1 | Structures, supercells, slab generation and adsorption-site finding | MIT. |
| RDKit >=2024.3 | Optional organic SMILES/conformer conversion | BSD 3-Clause. |

Packmol version and executable probe are stored in the solvent provenance. ASE and pymatgen/RDKit versions are stored in the corresponding plugin result. No third-party algorithm source is copied into this package.

## 5. Tests

The real Packmol test executes the packmol command; under GitHub Actions, the test bootstraps the pinned packmol==21.2.3 wheel when the executable is not preinstalled. It is not a mocked process. The ASE IDPP tests use real ASE NEB and idpp_interpolate, including a mixed-element endpoint whose source atom order differs and whose FixAtoms constraint index is remapped by ASE.

~~~bash
python -m unittest discover -s tests -p "test_structure_plugins.py" -v
python -m pytest -q tests/model_plugins/structure
python -m unittest discover -s tests -v
python -m compileall -q pipeline_contracts tests examples
~~~

The Packmol test may be skipped in an offline local environment without Packmol installed. For a local real run, install requirements.txt first. The pymatgen and RDKit routes are optional dependencies and return explicit UNSUPPORTED status when unavailable.
