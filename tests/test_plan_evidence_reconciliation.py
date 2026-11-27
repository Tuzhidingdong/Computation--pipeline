from __future__ import annotations

import copy
import unittest

from pipeline_contracts.plan_compiler.evidence_reconciliation import (
    MENTION_ONLY,
    NEEDS_REVIEW,
    PROFILE_ONLY,
    SOURCE_CONFLICT,
    SOURCE_MISMATCH,
    SOURCE_SUPPORTED,
    reconcile_project_profile,
)


def make_manifest(claims=None, evidence=None):
    return {
        "schema_version": "1.0.0",
        "claims": list(claims or []),
        "evidence": list(evidence or []),
    }


def claim(field, value, evidence_id, label=None, source_text=None, source=None):
    return {
        "field": field,
        "label": label or field,
        "value": value,
        "status": "requires_confirmation",
        "evidence_id": evidence_id,
        "source": source or {"part": "word/document.xml", "paragraph": int(evidence_id[-1])},
        "source_text": source_text or f"{label or field}: {value}",
    }


def evidence(evidence_id, text, paragraph):
    return {
        "evidence_id": evidence_id,
        "text": text,
        "source": {"part": "word/document.xml", "paragraph": paragraph},
        "block_kind": "paragraph",
    }


class ProjectProfileEvidenceReconciliationTests(unittest.TestCase):
    def result_for(self, report, path):
        return next(item for item in report["results"] if item["profile_field"] == path)

    def test_duplicate_same_field_value_is_supported_not_conflict(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff", "500.0", "ev-1"), claim("cutoff", 500, "ev-2")],
            [evidence("ev-1", "Cutoff: 500.0", 1), evidence("ev-2", "Cutoff: 500", 2)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ["ev-1", "ev-2"])

    def test_two_distinct_values_for_same_field_are_conflict(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff", "500 Ry", "ev-1"), claim("cutoff", "600 Ry", "ev-2")],
            [evidence("ev-1", "Cutoff: 500 Ry", 1), evidence("ev-2", "Cutoff: 600 Ry", 2)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_CONFLICT)
        self.assertEqual(result["evidence_ids"], ["ev-1", "ev-2"])

    def test_profile_value_without_corresponding_evidence_is_profile_only(self):
        report = reconcile_project_profile(
            {"systems": {"Cu-20": {"atom_count": 83}}}, make_manifest()
        )
        result = self.result_for(report, "systems.Cu-20.atom_count")
        self.assertEqual(result["status"], PROFILE_ONLY)
        self.assertEqual(result["evidence"], [])

    def test_isolated_number_is_mention_only_not_parameter_support(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            evidence=[evidence("ev-1", "The appendix page number is 500.", 1)]
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], MENTION_ONLY)
        self.assertEqual(result["evidence_ids"], ["ev-1"])

    def test_explicit_alias_maps_a_profile_path_to_manifest_label(self):
        profile = {"method": {"cutoff_ry": 500}}
        manifest = make_manifest(
            [claim("plane_wave_cutoff", "500 Ry", "ev-1", "Plane-wave cutoff")],
            [evidence("ev-1", "Plane-wave cutoff: 500 Ry", 1)],
        )
        report = reconcile_project_profile(
            profile, manifest, aliases={"method.cutoff_ry": ["plane_wave_cutoff", "Plane-wave cutoff"]}
        )
        result = self.result_for(report, "method.cutoff_ry")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)

    def test_explicit_aliases_can_disambiguate_duplicate_leaf_field_names(self):
        profile = {"systems": {"Cu": {"charge": 0}, "SnCu": {"charge": 0}}}
        manifest = make_manifest(
            [claim("cu_charge", 0, "ev-1"), claim("sncu_charge", 0, "ev-2")],
            [evidence("ev-1", "Cu charge: 0", 1), evidence("ev-2", "SnCu charge: 0", 2)],
        )
        report = reconcile_project_profile(profile, manifest, aliases={
            "systems.Cu.charge": "cu_charge",
            "systems.SnCu.charge": "sncu_charge",
        })
        self.assertEqual(self.result_for(report, "systems.Cu.charge")["status"], SOURCE_SUPPORTED)
        self.assertEqual(self.result_for(report, "systems.SnCu.charge")["status"], SOURCE_SUPPORTED)

    def test_different_units_are_not_converted_or_treated_as_equal(self):
        profile = {"method": {"cutoff": "500 eV"}}
        manifest = make_manifest(
            [claim("cutoff", "500 Ry", "ev-1")],
            [evidence("ev-1", "Cutoff: 500 Ry", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_MISMATCH)

    def test_evidence_id_text_and_source_location_are_preserved(self):
        profile = {"method": {"xc": "PBE"}}
        original_evidence = evidence("ev-7", "Exchange-correlation functional: PBE", 7)
        manifest = make_manifest(
            [claim("xc", "PBE", "ev-7", "Exchange-correlation functional",
                   source_text="Exchange-correlation functional: PBE",
                   source={"part": "word/document.xml", "paragraph": 7})],
            [original_evidence],
        )
        before = copy.deepcopy(manifest["evidence"])
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.xc")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ["ev-7"])
        self.assertEqual(result["evidence"][0]["text"], "Exchange-correlation functional: PBE")
        self.assertEqual(result["evidence"][0]["source"]["paragraph"], 7)
        self.assertEqual(manifest["evidence"], before)

    def test_claim_that_maps_to_two_profile_fields_needs_review(self):
        profile = {"systems": {"Cu": {"charge": 0}, "SnCu": {"charge": 0}}}
        manifest = make_manifest(
            [claim("charge", 0, "ev-1")], [evidence("ev-1", "Charge: 0", 1)]
        )
        report = reconcile_project_profile(profile, manifest)
        self.assertEqual(self.result_for(report, "systems.Cu.charge")["status"], NEEDS_REVIEW)
        self.assertEqual(self.result_for(report, "systems.SnCu.charge")["status"], NEEDS_REVIEW)

    def test_similar_but_not_exact_field_name_is_not_supported(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff_energy", 500, "ev-1")],
            [evidence("ev-1", "Cutoff energy: 500", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], MENTION_ONLY)

    def test_key_equals_value_and_whitespace_case_numeric_format_are_normalised(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff", "Cutoff = 5.00e2 Ry", "ev-1")],
            [evidence("ev-1", "Cutoff = 5.00e2 Ry", 1)],
        )
        # Unit is deliberately absent from the Profile value, so no unit inference occurs.
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_MISMATCH)

    def test_explicit_manifest_unit_field_is_compared_without_unit_inference(self):
        profile = {"method": {"cutoff": {"value": 500, "unit": "Ry"}}}
        manifest = make_manifest(
            [{**claim("cutoff", 500, "ev-1"), "unit": "Ry"}],
            [evidence("ev-1", "Cutoff: 500 Ry", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)

    def test_declared_same_unit_quantity_normalises_number_and_unit_alias(self):
        profile = {"method": {"cutoff": "500 eV/Å"}}
        manifest = make_manifest(
            [claim("cutoff", "500.0 eV/Angstrom", "ev-1")],
            [evidence("ev-1", "Cutoff: 500.0 eV/Angstrom", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)

    def test_table_split_label_and_value_claim_is_reconciled_with_row_excerpt(self):
        profile = {"method": {"multiplicity": 2}}
        manifest = make_manifest(
            [{
                "field": "multiplicity", "label": "Multiplicity", "value": "2",
                "evidence_id": "cell-1",
                "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 1},
                "source_text": "Multiplicity | 2",
            }],
            [
                {"evidence_id": "cell-1", "text": "Multiplicity",
                 "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 1}},
                {"evidence_id": "cell-2", "text": "2",
                 "source": {"part": "word/document.xml", "table": 1, "row": 1, "column": 2}},
            ],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.multiplicity")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence"][0]["text"], "Multiplicity | 2")
        self.assertEqual(result["evidence"][0]["source"]["column"], 1)

    def test_unset_profile_field_is_visible_and_needs_review(self):
        report = reconcile_project_profile({"tasks": {"WP1": {"orientation_scope": None}}}, make_manifest())
        result = self.result_for(report, "tasks.WP1.orientation_scope")
        self.assertEqual(result["status"], NEEDS_REVIEW)

    def test_claim_without_complete_provenance_cannot_be_supported(self):
        profile = {"method": {"xc": "PBE"}}
        manifest = make_manifest([{"field": "xc", "label": "xc", "value": "PBE"}])
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.xc")
        self.assertEqual(result["status"], NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()
