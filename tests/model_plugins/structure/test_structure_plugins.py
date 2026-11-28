from __future__ import annotations

import copy
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
from ase.constraints import FixAtoms, FixConstraint
from ase.io import read, write
from unittest.mock import patch

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




class _UnremappableConstraint(FixConstraint):
    def index_shuffle(self, atoms, ind):
        raise NotImplementedError("test constraint deliberately has no safe atom-index remap")

    def todict(self):
        return {"name": "UnremappableConstraint", "kwargs": {}}

    def adjust_positions(self, atoms, newpositions):
        return None

    def adjust_forces(self, atoms, forces):
        return None

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
    return {"initial": copy.deepcopy(common), "final": copy.deepcopy(common)}


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
            self.assertEqual(result["interpolation"]["neb_force_projection_method"], "improvedtangent")
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


    def test_real_ase_idpp_reorders_mixed_element_endpoint_and_remaps_constraints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial_atoms = Atoms(
                "HOH",
                positions=[
                    [0.9572, 0.0, 0.0],
                    [0.0, 0.0, 0.0],
                    [-0.239987, 0.927297, 0.0],
                ],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            # The first H is deliberately fixed in both aligned endpoints.
            initial_atoms.set_constraint(FixAtoms(indices=[0]))
            final_aligned_atoms = initial_atoms.copy()
            final_aligned_atoms.positions = np.array([
                [0.9572, 0.0, 0.0],
                [0.025, 0.015, 0.0],
                [-0.205, 0.950, 0.0],
            ])
            # Source file order is O/H/H; mapping [1, 0, 2] restores H/O/H.
            final_source_atoms = Atoms(
                symbols=[final_aligned_atoms[i].symbol for i in [1, 0, 2]],
                positions=final_aligned_atoms.positions[[1, 0, 2]],
                cell=final_aligned_atoms.cell,
                pbc=final_aligned_atoms.pbc,
            )
            final_source_atoms.set_constraint(FixAtoms(indices=[1]))
            initial = write_xyz(root / "initial_mixed.extxyz", initial_atoms)
            final = write_xyz(root / "final_reordered.extxyz", final_source_atoms)
            initial_bytes_before = Path(initial["path"]).read_bytes()
            final_bytes_before = Path(final["path"]).read_bytes()
            output = root / "neb-reordered-output"

            context = endpoint_context()
            context["initial"]["constraints"] = [
                constraint.todict() for constraint in initial_atoms.constraints
            ]
            context["final"]["constraints"] = [
                constraint.todict() for constraint in final_source_atoms.constraints
            ]
            recipe = {
                "atom_mapping_initial_to_final": [1, 0, 2],
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
            self.assertEqual(result["atom_mapping_initial_to_final"], [1, 0, 2])
            self.assertEqual(result["atom_mapping_direction"], "initial_index -> final_source_index")
            self.assertTrue(result["constraint_remapping"]["performed"])
            self.assertEqual(result["constraint_remapping"]["constraint_count"], 1)
            self.assertEqual(
                result["constraint_remapping"]["final_aligned_constraints"][0]["kwargs"]["indices"],
                [0],
            )

            # Input bytes and their original SHA-256 values remain untouched.
            self.assertEqual(Path(initial["path"]).read_bytes(), initial_bytes_before)
            self.assertEqual(Path(final["path"]).read_bytes(), final_bytes_before)
            self.assertEqual(sha256_file(initial["path"]), initial["sha256"])
            self.assertEqual(sha256_file(final["path"]), final["sha256"])
            self.assertEqual(result["endpoint_sha256"]["initial"], initial["sha256"])
            self.assertEqual(result["endpoint_sha256"]["final"], final["sha256"])

            # The final source copy is byte-identical to the original O/H/H endpoint.
            copied_final = output / "inputs" / "final_source.extxyz"
            self.assertTrue(copied_final.is_file())
            self.assertEqual(sha256_file(copied_final), final["sha256"])
            copied_final_atoms = read(str(copied_final), index=0)
            self.assertEqual(copied_final_atoms.get_chemical_symbols(), ["O", "H", "H"])

            images = [
                read(str(path), index=0)
                for path in sorted((output / "images").glob("image_*.extxyz"))
            ]
            self.assertEqual(len(images), 5)
            for image in images:
                self.assertEqual(image.get_chemical_symbols(), ["H", "O", "H"])
                self.assertEqual(len(image), 3)
                self.assertEqual(image.pbc.tolist(), [False, False, False])
                np.testing.assert_allclose(image.cell.array, initial_atoms.cell.array, atol=1e-10)
                self.assertTrue(np.isfinite(image.positions).all())
                # The identity of the fixed H must remain at initial index 0.
                np.testing.assert_allclose(image.positions[0], initial_atoms.positions[0], atol=1e-8)

            np.testing.assert_allclose(images[0].positions, initial_atoms.positions, atol=1e-10)
            np.testing.assert_allclose(
                images[-1].positions, final_aligned_atoms.positions, atol=1e-10
            )
            path_frames = read(str(output / "initial_path.extxyz"), index=":")
            self.assertEqual(len(path_frames), 5)
            self.assertTrue(all(frame.get_chemical_symbols() == ["H", "O", "H"] for frame in path_frames))

            manifest = json.loads((output / "path_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["atom_mapping_initial_to_final"], [1, 0, 2])
            self.assertEqual(manifest["endpoint_sha256"]["final"], final["sha256"])
            self.assertTrue(manifest["constraint_remapping"]["performed"])
            self.assertEqual(manifest["constraint_remapping"]["constraint_count"], 1)
            artifact_records = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
            self.assertEqual(artifact_records["inputs/final_source.extxyz"], final["sha256"])
            self.assertEqual(artifact_records["inputs/initial_source.extxyz"], initial["sha256"])
            for artifact in result["artifacts"]:
                artifact_path = output / artifact["path"]
                self.assertTrue(artifact_path.is_file(), artifact)
                self.assertEqual(sha256_file(artifact_path), artifact["sha256"])

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



    def test_nonidentity_mapping_with_unremappable_constraint_requires_decision_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial_atoms = Atoms(
                "HOH",
                positions=[[0.9572, 0.0, 0.0], [0.0, 0.0, 0.0], [-0.239987, 0.927297, 0.0]],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            final_source_atoms = Atoms(
                "OHH",
                positions=[[0.025, 0.015, 0.0], [0.9572, 0.0, 0.0], [-0.205, 0.950, 0.0]],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            initial_source = write_xyz(root / "initial.extxyz", initial_atoms)
            final_source = write_xyz(root / "final_reordered.extxyz", final_source_atoms)
            final_atoms_with_constraint = final_source_atoms.copy()
            final_atoms_with_constraint.set_constraint(_UnremappableConstraint())
            context = endpoint_context()
            context["final"]["constraints"] = [_UnremappableConstraint().todict()]
            output = root / "must_not_be_created"

            def source_reader(source, label):
                if label == "initial_structure":
                    return initial_atoms.copy(), initial_source
                return final_atoms_with_constraint.copy(), final_source

            recipe = {
                "atom_mapping_initial_to_final": [1, 0, 2],
                "number_of_images": 5,
                "endpoint_context": context,
                "idpp": {"steps": 20, "fmax_angstrom_per_step": 0.05, "mic": False},
                "validation": {"minimum_pair_distance_angstrom": 0.55},
            }
            with patch(
                "pipeline_contracts.model_plugins.structure.neb.read_ase_source",
                side_effect=source_reader,
            ):
                result = build_neb_initial_path(
                    initial_source, final_source, recipe, output
                )

            self.assertEqual(result["status"], "NEEDS_DECISION")
            self.assertTrue(
                any("cannot be safely remapped" in item for item in result["decision_required"])
            )
            self.assertFalse(output.exists())

    def test_missing_mapping_for_reordered_endpoint_returns_needs_decision_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial_atoms = Atoms(
                "HOH",
                positions=[[0.9572, 0.0, 0.0], [0.0, 0.0, 0.0], [-0.239987, 0.927297, 0.0]],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            final_source_atoms = Atoms(
                "OHH",
                positions=[[0.025, 0.015, 0.0], [0.9572, 0.0, 0.0], [-0.205, 0.950, 0.0]],
                cell=[12, 12, 12],
                pbc=[False, False, False],
            )
            initial = write_xyz(root / "initial.extxyz", initial_atoms)
            final = write_xyz(root / "final_reordered.extxyz", final_source_atoms)
            output = root / "must_not_be_created"
            result = build_neb_initial_path(
                initial,
                final,
                {
                    "number_of_images": 5,
                    "endpoint_context": endpoint_context(),
                    "idpp": {"steps": 20, "fmax_angstrom_per_step": 0.05, "mic": False},
                    "validation": {"minimum_pair_distance_angstrom": 0.55},
                },
                output,
            )
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
