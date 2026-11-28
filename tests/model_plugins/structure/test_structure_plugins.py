from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from ase import Atoms
from ase.io import read, write

from pipeline_contracts.model_plugins.structure import (
    build_explicit_solvent_box,
    build_neb_initial_path,
    get_model_plugin_route,
    load_structure_model,
)
from pipeline_contracts.model_plugins.structure.core import atoms_from_mapping, sha256_file


def source_record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256_file(path)}


def write_xyz(path: Path, atoms: Atoms) -> dict:
    write(str(path), atoms, format="extxyz" if path.suffix.lower() == ".extxyz" else "xyz")
    return source_record(path)


def endpoint_context() -> dict:
    common = {
        "charge": 0,
        "spin_multiplicity": 1,
        "constraints": [],
        "method_fingerprint": {
            "engine": "synthetic-no-calculator",
            "xc": "PBE",
            "basis": "TEST_ONLY",
            "fingerprint_version": 1,
        },
    }
    return {"initial": dict(common), "final": dict(common)}


class StructureMappingAndRoutingTests(unittest.TestCase):
    def test_ase_structure_mapping_round_trip_keeps_symbols_positions_cell_and_pbc(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "molecule.extxyz"
            atoms = Atoms(
                "OH2",
                positions=[[0, 0, 0], [0.96, 0, 0], [-0.24, 0.93, 0]],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            source = write_xyz(path, atoms)
            mapping = load_structure_model(source, structure_type="molecule")
            round_trip = atoms_from_mapping(mapping)
            self.assertEqual(round_trip.get_chemical_symbols(), atoms.get_chemical_symbols())
            np.testing.assert_allclose(round_trip.positions, atoms.positions)
            np.testing.assert_allclose(round_trip.cell.array, atoms.cell.array)
            self.assertEqual(round_trip.pbc.tolist(), atoms.pbc.tolist())
            self.assertEqual(mapping["source"]["sha256"], source["sha256"])

    def test_registry_has_explicit_supported_and_unsupported_routes(self):
        interface = get_model_plugin_route("interface")
        implicit = get_model_plugin_route("implicit solvation")
        transition_path = get_model_plugin_route("transition-state initial path")
        self.assertEqual(interface["status"], "UNSUPPORTED")
        self.assertEqual(implicit["status"], "UNSUPPORTED")
        self.assertIn("lattice", interface["reason"])
        self.assertEqual(transition_path["provider"], "ASE NEB + IDPP")
        self.assertIn("entrypoint", transition_path)

    def test_unknown_model_type_is_not_silently_routed(self):
        route = get_model_plugin_route("invented-model-family")
        self.assertEqual(route["status"], "UNSUPPORTED")


class ExplicitSolventPreflightTests(unittest.TestCase):
    def _files(self, root: Path):
        solute = Atoms("C", positions=[[7.0, 7.0, 7.0]])
        water = Atoms(
            "OH2",
            positions=[[0.0, 0.0, 0.0], [0.9572, 0.0, 0.0], [-0.239987, 0.927297, 0.0]],
        )
        solute_source = write_xyz(root / "solute.xyz", solute)
        water_source = write_xyz(root / "water.xyz", water)
        return solute_source, water_source

    def test_missing_solvent_count_or_density_returns_needs_decision_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            solute, water = self._files(root)
            output = root / "must_not_be_created"
            result = build_explicit_solvent_box(
                {
                    "solute": solute,
                    "solvents": [{"id": "water", **water}],
                    "box": {
                        "bounds_angstrom": [[0, 0, 0], [14, 14, 14]],
                        "pbc": [True, True, True],
                    },
                    "distance_tolerance_angstrom": 1.2,
                    "random_seed": 20261128,
                    "output_format": "extxyz",
                    "validation": {"minimum_inter_molecular_distance_angstrom": 0.6},
                },
                output,
            )
            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertFalse(output.exists())
            self.assertTrue(any("count" in item or "density" in item for item in result["decision_required"]))

    def test_missing_seed_and_validation_threshold_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            solute, water = self._files(root)
            output = root / "must_not_be_created"
            recipe = {
                "solute": solute,
                "solvents": [{"id": "water", "count": 2, **water}],
                "box": {
                    "bounds_angstrom": [[0, 0, 0], [14, 14, 14]],
                    "pbc": [False, False, False],
                },
                "distance_tolerance_angstrom": 1.2,
                "output_format": "xyz",
                "validation": {},
            }
            result = build_explicit_solvent_box(recipe, output)
            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertFalse(output.exists())

    def test_wrong_source_sha_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            solute, water = self._files(root)
            solute["sha256"] = "0" * 64
            output = root / "must_not_be_created"
            result = build_explicit_solvent_box(
                {
                    "solute": solute,
                    "solvents": [{"id": "water", "count": 2, **water}],
                    "box": {
                        "bounds_angstrom": [[0, 0, 0], [14, 14, 14]],
                        "pbc": [False, False, False],
                    },
                    "distance_tolerance_angstrom": 1.2,
                    "random_seed": 20261128,
                    "output_format": "xyz",
                    "validation": {"minimum_inter_molecular_distance_angstrom": 0.6},
                },
                output,
            )
            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertFalse(output.exists())


class RealPackmolEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable = shutil.which("packmol")
        # The repository workflow installs ASE but not external scientific
        # executables. In GitHub Actions only, bootstrap the pinned official
        # PyPI Packmol wheel so this remains a real executable integration test.
        if executable is None and os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "packmol==21.2.3"],
                check=True,
                timeout=240,
                capture_output=True,
                text=True,
            )
            executable = shutil.which("packmol")
        if executable is None:
            raise unittest.SkipTest(
                "real Packmol E2E requires the packmol executable (install pipeline_contracts/model_plugins/structure/requirements.txt)"
            )
        cls.packmol_executable = executable

    def test_real_packmol_generates_hash_pinned_explicit_solvent_box(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            solute_atoms = Atoms("C", positions=[[7.0, 7.0, 7.0]])
            water_atoms = Atoms(
                "OH2",
                positions=[[0.0, 0.0, 0.0], [0.9572, 0.0, 0.0], [-0.239987, 0.927297, 0.0]],
            )
            solute = write_xyz(root / "solute.xyz", solute_atoms)
            water = write_xyz(root / "water.xyz", water_atoms)
            output = root / "packmol-output"
            recipe = {
                "solute": solute,
                "solvents": [{"id": "water", "count": 4, **water}],
                "box": {
                    "bounds_angstrom": [[0, 0, 0], [14, 14, 14]],
                    "pbc": [True, True, True],
                },
                "distance_tolerance_angstrom": 1.2,
                "random_seed": 20261128,
                "output_format": "extxyz",
                "validation": {
                    "minimum_inter_molecular_distance_angstrom": 0.6,
                },
            }
            result = build_explicit_solvent_box(
                recipe,
                output,
                packmol_executable=self.packmol_executable,
            )
            self.assertEqual(result["status"], "VALIDATED_INITIAL_STRUCTURE", result)
            self.assertEqual(result["equilibration_status"], "PACKED_NOT_EQUILIBRATED")
            structure = output / "structure.extxyz"
            self.assertTrue(structure.is_file())
            packed = read(str(structure), index=0)
            self.assertEqual(len(packed), 13)
            self.assertEqual(packed.get_chemical_symbols().count("C"), 1)
            self.assertEqual(packed.get_chemical_symbols().count("O"), 4)
            self.assertEqual(packed.get_chemical_symbols().count("H"), 8)
            self.assertTrue(packed.pbc.all())
            np.testing.assert_allclose(packed.cell.lengths(), [14, 14, 14], atol=1e-6)
            self.assertEqual(packed.arrays["molecule_id"].shape, (13,))
            molecule_ids = packed.arrays["molecule_id"]
            distance_matrix = packed.get_all_distances(mic=True)
            mask = molecule_ids[:, None] != molecule_ids[None, :]
            observed_minimum = float(np.min(distance_matrix[mask]))
            self.assertGreaterEqual(observed_minimum + 1e-7, 0.6)
            self.assertEqual(result["validation"]["molecule_counts"], {"solute": 1, "water": 4})
            self.assertEqual(result["source_inputs"][0]["sha256"], solute["sha256"])
            self.assertEqual(result["source_inputs"][1]["sha256"], water["sha256"])
            for artifact in result["artifacts"]:
                artifact_path = output / artifact["path"]
                self.assertTrue(artifact_path.is_file(), artifact)
                self.assertEqual(sha256_file(artifact_path), artifact["sha256"])
            self.assertTrue((output / "packmol.inp").is_file())
            self.assertTrue((output / "packmol.log").is_file())
            self.assertTrue((output / "run_manifest.json").is_file())
            self.assertEqual(result["packmol"]["random_seed"], 20261128)
            self.assertNotEqual(result["packmol"]["version"], "not-installed")


class RealASEIDPPEndToEndTests(unittest.TestCase):
    def _endpoint_files(self, root: Path):
        initial_atoms = Atoms(
            "OH2",
            positions=[
                [0.0, 0.0, 0.0],
                [0.9572, 0.0, 0.0],
                [-0.239987, 0.927297, 0.0],
            ],
            cell=[12, 12, 12],
            pbc=[False, False, False],
        )
        angle = np.deg2rad(38.0)
        rotation = np.array([
            [np.cos(angle), -np.sin(angle), 0.0],
            [np.sin(angle), np.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ])
        final_atoms = initial_atoms.copy()
        final_atoms.positions = initial_atoms.positions @ rotation.T + np.array([0.15, 0.0, 0.0])
        initial = write_xyz(root / "initial.extxyz", initial_atoms)
        final = write_xyz(root / "final.extxyz", final_atoms)
        return initial, final, initial_atoms, final_atoms

    def test_real_ase_idpp_generates_reviewable_images_and_preserves_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial, final, initial_atoms, final_atoms = self._endpoint_files(root)
            output = root / "neb-output"
            context = endpoint_context()
            recipe = {
                "atom_mapping_initial_to_final": [0, 1, 2],
                "number_of_images": 5,
                "endpoint_context": context,
                "idpp": {
                    "steps": 60,
                    "fmax_angstrom_per_step": 0.05,
                    "mic": False,
                },
                "validation": {
                    "minimum_pair_distance_angstrom": 0.55,
                },
            }
            result = build_neb_initial_path(initial, final, recipe, output)
            self.assertEqual(result["status"], "INITIAL_PATH_READY_FOR_REVIEW", result)
            self.assertEqual(result["interpolation"]["method"], "ase.mep.neb.idpp_interpolate")
            self.assertEqual(result["number_of_images"], 5)
            image_paths = sorted((output / "images").glob("image_*.extxyz"))
            self.assertEqual(len(image_paths), 5)
            all_images = [read(str(path), index=0) for path in image_paths]
            for image in all_images:
                self.assertEqual(image.get_chemical_symbols(), ["O", "H", "H"])
                self.assertTrue(np.isfinite(image.positions).all())
                self.assertEqual(image.pbc.tolist(), [False, False, False])
            np.testing.assert_allclose(all_images[0].positions, initial_atoms.positions, atol=1e-10)
            np.testing.assert_allclose(all_images[-1].positions, final_atoms.positions, atol=1e-10)
            path_frames = read(str(output / "initial_path.extxyz"), index=":")
            self.assertEqual(len(path_frames), 5)
            self.assertEqual(result["endpoint_sha256"]["initial"], initial["sha256"])
            self.assertEqual(result["endpoint_sha256"]["final"], final["sha256"])
            for artifact in result["artifacts"]:
                artifact_path = output / artifact["path"]
                self.assertTrue(artifact_path.is_file(), artifact)
                self.assertEqual(sha256_file(artifact_path), artifact["sha256"])
            self.assertTrue((output / "idpp_optimization.log").is_file())
            self.assertTrue((output / "path_manifest.json").is_file())

    def test_missing_or_ambiguous_atom_mapping_returns_needs_decision_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial, final, _, _ = self._endpoint_files(root)
            output = root / "must_not_be_created"
            recipe = {
                "number_of_images": 5,
                "endpoint_context": endpoint_context(),
                "idpp": {"steps": 20, "fmax_angstrom_per_step": 0.05, "mic": False},
                "validation": {"minimum_pair_distance_angstrom": 0.55},
            }
            result = build_neb_initial_path(initial, final, recipe, output)
            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertFalse(output.exists())

    def test_context_fingerprint_mismatch_returns_needs_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial, final, _, _ = self._endpoint_files(root)
            context = endpoint_context()
            context["final"]["method_fingerprint"]["xc"] = "PBE-D3(BJ)"
            output = root / "must_not_be_created"
            recipe = {
                "atom_mapping_initial_to_final": [0, 1, 2],
                "number_of_images": 5,
                "endpoint_context": context,
                "idpp": {"steps": 20, "fmax_angstrom_per_step": 0.05, "mic": False},
                "validation": {"minimum_pair_distance_angstrom": 0.55},
            }
            result = build_neb_initial_path(initial, final, recipe, output)
            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
