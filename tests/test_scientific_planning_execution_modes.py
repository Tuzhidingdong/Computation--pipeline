from __future__ import annotations

import unittest

from pipeline_contracts.scientific_planning.execution_modes import agent_a_execution_mode
from pipeline_contracts.scientific_planning.engines import plan_method, to_cp2k_calculation_plan_method
from pipeline_contracts.scientific_planning.planning_orchestrator import _engine_request


def _source_fields():
    return {
        "xc_functional": "PBE",
        "dispersion": "NONE",
        "basis_set": "DZVP-MOLOPT-SR-GTH",
        "pseudopotential": "GTH-PBE",
        "basis_file_name": "BASIS_MOLOPT",
        "potential_file_name": "GTH_POTENTIALS",
        "kind_definitions": {
            "Cu": {"element": "Cu", "basis_set": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"},
            "O": {"element": "O", "basis_set": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"},
        },
        "cutoff_ry": 400,
        "rel_cutoff_ry": 60,
        "scf": {"method": "OT", "eps_scf": 1e-6, "max_scf": 120},
        "charge": 0,
        "multiplicity": 1,
        "spin": "SINGLET",
        "uks": False,
        "center_coordinates": True,
        "periodicity": "NONE",
        "poisson_solver": "MT",
        "poisson_periodicity": "NONE",
        "solvation": {"implicit": "NONE", "explicit": "NONE"},
        "software_version": "2025.2",
    }


def _request(backend="cp2k", *, verified=False, runtime_version=None):
    config = {
        "method": {
            "engine": "cp2k",
            "software_version": "2025.2",
            "software_version_source_ref": "profile:cp2k-version",
            "runtime_version_verified": verified,
            # Misleading Profile value: must never be forwarded as runtime evidence.
            "runtime_verified_version": "PROFILE-MUST-NOT-BE-USED",
        },
        "task_type": "cp2k.geo_opt",
        "execution": {"backend": backend},
    }
    sources = [{
        "source_kind": "approved_profile",
        "approved": True,
        "source_ref": "approved-profile-fixture",
        "fields": _source_fields(),
    }]
    return _engine_request(
        config,
        {"atom_count": 2, "periodic_boundary_conditions": [False, False, False]},
        sources,
        runtime_verified_version=runtime_version,
    )


class ScientificPlanningExecutionModeTests(unittest.TestCase):
    def test_backend_mapping_is_explicit_and_preserves_original_backend(self):
        mock = _request("mock")
        cp2k = _request("cp2k", runtime_version="2025.2")
        unknown = _request("orca", verified=True, runtime_version="2025.2")

        self.assertEqual(mock["execution_mode"], "mock")
        self.assertEqual(mock["execution_backend"], "mock")
        self.assertTrue(mock["execution_backend_registered"])

        self.assertEqual(cp2k["execution_mode"], "real")
        self.assertEqual(cp2k["execution_backend"], "cp2k")
        self.assertTrue(cp2k["execution_backend_registered"])

        self.assertEqual(unknown["execution_mode"], "blocked")
        self.assertEqual(unknown["execution_backend"], "orca")
        self.assertFalse(unknown["execution_backend_registered"])
        self.assertIsNone(agent_a_execution_mode("orca"))
        self.assertIsNone(agent_a_execution_mode(None))

    def test_runtime_verified_version_is_independent_of_profile_fields(self):
        missing = _request("cp2k", verified=True)
        self.assertIsNone(missing["runtime_verified_version"])
        self.assertNotEqual(missing["runtime_verified_version"], "PROFILE-MUST-NOT-BE-USED")

        supplied = _request("cp2k", verified=True, runtime_version="2025.2")
        self.assertEqual(supplied["runtime_verified_version"], "2025.2")
        self.assertEqual(supplied["software_version"], "2025.2")

    def test_real_cp2k_unverified_missing_and_mismatched_versions_are_blocked(self):
        unverified = plan_method(_request("cp2k", verified=False, runtime_version="2025.2"))
        self.assertEqual(unverified["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertTrue(unverified["runtime_version_matches"])
        self.assertFalse(unverified["runtime_version_verified"])
        self.assertTrue(any("verified against the installed executable" in item
                            for item in unverified["blockers"]))

        missing = plan_method(_request("cp2k", verified=True))
        self.assertEqual(missing["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertFalse(missing["runtime_version_matches"])
        self.assertTrue(any("runtime_verified_version must exactly match" in item
                            for item in missing["blockers"]))

        mismatched = plan_method(_request("cp2k", verified=True, runtime_version="2025.1"))
        self.assertEqual(mismatched["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertFalse(mismatched["runtime_version_matches"])
        self.assertTrue(any("runtime_verified_version must exactly match" in item
                            for item in mismatched["blockers"]))

    def test_real_cp2k_requires_exact_independent_runtime_version_match(self):
        result = plan_method(_request("cp2k", verified=True, runtime_version="2025.2"))
        self.assertEqual(result["status"], "METHOD_FIELDS_RESOLVED")
        self.assertTrue(result["ready_for_core_compilation"])
        self.assertTrue(result["runtime_version_verified"])
        self.assertTrue(result["runtime_version_matches"])
        self.assertEqual(result["runtime_verified_version"], "2025.2")

    def test_cp2k_projection_uses_real_mode_and_keeps_the_real_version_gate(self):
        # Projection/gate only. No WorkflowAdapter, remote client or HPC job is created.
        projection = to_cp2k_calculation_plan_method({
            "engine": "cp2k",
            "status": "METHOD_FIELDS_RESOLVED",
            "ready_for_core_compilation": True,
            "blockers": [],
            "fields": {},
            "execution_mode": agent_a_execution_mode("cp2k"),
            "runtime_version_verified": False,
            "runtime_version_matches": False,
            "runtime_verified_version": None,
            "software_version": "2025.2",
        })
        self.assertEqual(projection["execution_mode"], "real")
        self.assertEqual(projection["status"], "BLOCKED")
        self.assertTrue(any("Real projection requires runtime_version_verified=True" in item
                            for item in projection["blockers"]))
        self.assertTrue(any("runtime_verified_version to match software_version exactly" in item
                            for item in projection["blockers"]))


if __name__ == "__main__":
    unittest.main()
