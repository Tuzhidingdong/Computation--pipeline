from __future__ import annotations

import unittest

from pipeline_contracts.scientific_planning.execution_modes import agent_a_execution_mode, planning_mode_fields
from pipeline_contracts.scientific_planning.object_adapters import method_plan_object
from pipeline_contracts.scientific_planning.engines import plan_method, to_cp2k_calculation_plan_method
from pipeline_contracts.scientific_planning.planning_orchestrator import _engine_request
from pipeline_contracts.scientific_planning.plugin_registry import engine_planning


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
        self.assertEqual(planning_mode_fields("cp2k"), {
            "execution_mode": "real",
            "planning_scope": "REAL_PREFLIGHT_CANDIDATE",
            "mock_only": False,
        })
        self.assertEqual(planning_mode_fields("orca"), {})

    def test_unknown_backend_does_not_emit_invalid_mode_enum_fields(self):
        request = _request("orca", verified=True, runtime_version="2025.2")
        blocked_method = method_plan_object(
            method_raw={
                "engine": "cp2k", "execution_mode": "blocked",
                "status": "BLOCKED_UNREGISTERED_EXECUTION_BACKEND",
                "fields": {}, "software_version": None,
                "runtime_version_verified": False,
                "runtime_verified_version": None,
                "runtime_version_matches": False,
            },
            route={
                "integration_status": "UNSUPPORTED_BACKEND",
                "can_enter_real_preflight": False,
                "capability_ids": [],
            },
            engine_request=request,
            method_source_refs=[], all_refs=[], structure_mapping=None,
            artifact_ref=None, overall_status="BLOCKED",
            method_gaps=[], selection_records=[],
        )
        self.assertNotIn("execution_mode", blocked_method)
        self.assertNotIn("planning_scope", blocked_method)
        self.assertFalse(blocked_method.get("mock_only", False))
        self.assertFalse(blocked_method["real_execution_preflight_allowed"])

    def test_profile_true_without_independent_observation_is_blocked_and_not_preflight_ready(self):
        request = _request("cp2k", verified=True)
        self.assertIsNone(request["runtime_verified_version"])
        self.assertFalse(request["runtime_version_verified"])

        method = plan_method(request)
        route = engine_planning(request)["capability_route"]
        self.assertEqual(method["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertFalse(method["runtime_version_verified"])
        self.assertFalse(route["runtime_version_verified"])
        self.assertFalse(route["can_enter_real_preflight"])

    def test_profile_false_with_independent_exact_observation_passes_version_gate(self):
        request = _request("cp2k", verified=False, runtime_version="2025.2")
        self.assertEqual(request["runtime_verified_version"], "2025.2")
        self.assertTrue(request["runtime_version_verified"])

        method = plan_method(request)
        route = engine_planning(request)["capability_route"]
        self.assertEqual(method["status"], "METHOD_FIELDS_RESOLVED")
        self.assertTrue(method["runtime_version_verified"])
        self.assertTrue(method["runtime_version_matches"])
        self.assertTrue(route["runtime_version_verified"])
        self.assertTrue(route["runtime_version_matches"])
        self.assertTrue(route["can_enter_real_preflight"])

    def test_runtime_version_missing_and_mismatched_are_blocked(self):
        missing = plan_method(_request("cp2k", verified=False))
        self.assertEqual(missing["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertFalse(missing["runtime_version_verified"])
        self.assertFalse(missing["runtime_version_matches"])

        mismatched = plan_method(_request("cp2k", verified=False, runtime_version="2025.1"))
        self.assertEqual(mismatched["status"], "BLOCKED_RUNTIME_VERSION_UNVERIFIED")
        self.assertTrue(mismatched["runtime_version_verified"])
        self.assertFalse(mismatched["runtime_version_matches"])
        self.assertTrue(any("runtime_verified_version must exactly match" in item
                            for item in mismatched["blockers"]))

    def test_mock_planning_uses_source_backed_software_version_without_runtime_observation(self):
        request = _request("mock", verified=True)
        self.assertFalse(request["runtime_version_verified"])
        self.assertIsNone(request["runtime_verified_version"])
        result = plan_method(request)
        route = engine_planning(request)["capability_route"]
        self.assertEqual(result["status"], "METHOD_FIELDS_RESOLVED")
        self.assertEqual(result["software_version"], "2025.2")
        self.assertFalse(result["runtime_version_verified"])
        self.assertFalse(route["can_enter_real_preflight"])

    def test_real_cp2k_requires_exact_independent_runtime_version_match(self):
        result = plan_method(_request("cp2k", verified=False, runtime_version="2025.2"))
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
