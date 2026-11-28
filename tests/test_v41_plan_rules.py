from __future__ import annotations
import unittest
from projects.corr_dft_v4_1.plan_rules import audit_v41_plan, apply_v41_audit, confirm_v41_resolutions


class V41PlanRulesTests(unittest.TestCase):
    def test_known_orientation_and_spin_count_ambiguities_block_execution(self):
        result = audit_v41_plan({})
        self.assertEqual({item["code"] for item in result}, {
            "WP1_ORIENTATION_SCOPE_UNRESOLVED", "WP1_FRAGMENT_SPIN_COUNT_MISMATCH"
        })
        self.assertTrue(all(item["blocks_execution"] for item in result))

    def test_orientation_resolution_alone_does_not_silently_resolve_spin_count(self):
        result = audit_v41_plan({"confirmed_resolutions": {
            "wp1_orientation_scope": "per_catalyst",
            "wp1_fragment_spin_count_resolution": "retain_all_six",
        }})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "WP1_FRAGMENT_SPIN_COUNT_MISMATCH")

    def test_owner_can_explicitly_retain_all_six_candidates(self):
        result = confirm_v41_resolutions(
            {"unresolved_definitions":[]}, orientation_scope="per_catalyst",
            fragment_spin_resolution="retain_all_six",
            confirmed_by="owner", rationale="Retain every explicitly listed spin state and correct the summary count.",
        )
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["compilation_status"], "READY_FOR_APPROVAL")
        self.assertEqual(result["confirmed_resolutions"]["wp1_orientation_scope"], "per_catalyst")
        self.assertEqual(len(result["confirmed_resolutions"]["wp1_selected_fragment_spin_candidates"]), 6)
        self.assertEqual(result["project_decision_records"][0]["confirmed_by"], "owner")

    def test_owner_may_select_four_only_by_naming_all_four_candidates(self):
        selected = ["Cu13:M2", "Cu13:M4", "Cu20_support:M1", "SnCu20_support:M2"]
        result = confirm_v41_resolutions(
            {"unresolved_definitions":[]}, orientation_scope="across_both_systems",
            fragment_spin_resolution="select_four_explicitly",
            selected_fragment_spin_candidates=selected,
            confirmed_by="owner", rationale="The owner explicitly selected the four listed isolated-fragment calculations.",
        )
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["confirmed_resolutions"]["wp1_selected_fragment_spin_candidates"], selected)

    def test_select_four_requires_exact_unique_candidate_ids(self):
        with self.assertRaises(ValueError):
            confirm_v41_resolutions(
                {}, orientation_scope="per_catalyst",
                fragment_spin_resolution="select_four_explicitly",
                selected_fragment_spin_candidates=["Cu13:M2", "Cu13:M2", "Cu13:M4", "Cu20_support:M1"],
                confirmed_by="owner", rationale="invalid duplicate selection",
            )

    def test_audit_marks_manifest_blocked_without_discarding_existing_diagnostics(self):
        original = {"diagnostics":[{"code":"SOURCE_CONFLICT","blocks_execution":True}],
                    "compilation_status":"BLOCKED"}
        result = apply_v41_audit(original)
        self.assertEqual(result["diagnostics"][0]["code"], "SOURCE_CONFLICT")
        self.assertEqual(len(result["diagnostics"]), 3)
        self.assertEqual(result["compilation_status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
