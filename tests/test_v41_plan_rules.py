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

    def test_explicit_owner_resolutions_clear_only_the_two_known_blockers(self):
        result = audit_v41_plan({"confirmed_resolutions": {
            "wp1_orientation_scope": "per_catalyst",
            "wp1_fragment_spin_count_resolution": "preserve_detailed_six_correct_summary",
        }})
        self.assertEqual(result, [])

    def test_owner_resolution_is_recorded_and_clears_only_known_v41_blockers(self):
        result = confirm_v41_resolutions(
            {"unresolved_definitions":[]}, orientation_scope="per_catalyst",
            fragment_spin_resolution="preserve_detailed_six_correct_summary",
            confirmed_by="owner", rationale="The detailed spin list is authoritative; summary count will be corrected.",
        )
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["compilation_status"], "READY_FOR_APPROVAL")
        self.assertEqual(result["confirmed_resolutions"]["wp1_orientation_scope"], "per_catalyst")
        self.assertEqual(result["project_decision_records"][0]["confirmed_by"], "owner")

    def test_audit_marks_manifest_blocked_without_discarding_existing_diagnostics(self):
        original = {"diagnostics":[{"code":"SOURCE_CONFLICT","blocks_execution":True}],
                    "compilation_status":"BLOCKED"}
        result = apply_v41_audit(original)
        self.assertEqual(result["diagnostics"][0]["code"], "SOURCE_CONFLICT")
        self.assertEqual(len(result["diagnostics"]), 3)
        self.assertEqual(result["compilation_status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
