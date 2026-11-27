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


def claim(field, value, evidence_id, label=None, source_text=None, source=None, context=None):
    paragraph = int(evidence_id[-1]) if evidence_id[-1].isdigit() else 1
    location = source or {"part": "word/document.xml", "paragraph": paragraph}
    return {
        "field": field,
        "label": label or field,
        "value": value,
        "status": "requires_confirmation",
        "evidence_id": evidence_id,
        "evidence_ids": [evidence_id],
        "source": location,
        "source_text": source_text or f"{label or field}: {value}",
        "context": dict(context or {}),
    }


def evidence(evidence_id, text, paragraph):
    return {
        "evidence_id": evidence_id,
        "text": text,
        "source": {"part": "word/document.xml", "paragraph": paragraph},
        "block_kind": "paragraph",
    }


def table_location(table, row, column):
    return {
        "part": "word/document.xml",
        "table": table,
        "row": row,
        "column": column,
    }


def table_row_claim(field, label, value, evidence_ids, cells, *, table=1, row=1, context=None):
    locations = [table_location(table, row, column) for column in range(1, len(cells) + 1)]
    return {
        "field": field,
        "label": label,
        "value": value,
        "unit": None,
        "status": "requires_confirmation",
        "evidence_id": evidence_ids[0],
        "evidence_ids": list(evidence_ids),
        "source": locations[0],
        "source_text": " | ".join(cells),
        "sources": [
            {
                "evidence_id": evidence_id,
                "source": location,
                "source_text": cell_text,
                "raw_value": value,
            }
            for evidence_id, location, cell_text in zip(evidence_ids, locations, cells)
        ],
        "context": dict(context or {}),
    }


def table_evidence(evidence_ids, cells, *, table=1, row=1):
    return [
        {
            "evidence_id": evidence_id,
            "text": cell_text,
            "source": table_location(table, row, column),
            "block_kind": "table_cell",
            "style": None,
            "list_info": None,
        }
        for column, (evidence_id, cell_text) in enumerate(zip(evidence_ids, cells), start=1)
    ]


class ProjectProfileEvidenceReconciliationTests(unittest.TestCase):
    def result_for(self, report, path):
        return next(item for item in report["results"] if item["profile_field"] == path)

    def test_duplicate_same_field_value_is_supported_not_conflict(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff", "500.0", "ev-1"), claim("cutoff", 500, "ev-2")],
            [evidence("ev-1", "Cutoff: 500.0", 1), evidence("ev-2", "cutoff: 500", 2)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ["ev-1", "ev-2"])
        self.assertEqual([item["text"] for item in result["evidence"]],
                         ["Cutoff: 500.0", "cutoff: 500"])

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

    def test_explicit_aliases_can_disambiguate_duplicate_system_leaf_names(self):
        profile = {"systems": {"Cu": {"charge": 0}, "SnCu": {"charge": 0}}}
        cu = claim("cu_charge", 0, "ev-1", context={"system_id": "Cu"})
        sncu = claim("sncu_charge", 0, "ev-2", context={"system_id": "SnCu"})
        manifest = make_manifest(
            [cu, sncu],
            [evidence("ev-1", "Cu charge: 0", 1), evidence("ev-2", "SnCu charge: 0", 2)],
        )
        report = reconcile_project_profile(profile, manifest, aliases={
            "systems.Cu.charge": "cu_charge",
            "systems.SnCu.charge": "sncu_charge",
        })
        cu_result = self.result_for(report, "systems.Cu.charge")
        sncu_result = self.result_for(report, "systems.SnCu.charge")
        self.assertEqual(cu_result["status"], SOURCE_SUPPORTED)
        self.assertEqual(sncu_result["status"], SOURCE_SUPPORTED)
        self.assertEqual(cu_result["evidence_ids"], ["ev-1"])
        self.assertEqual(sncu_result["evidence_ids"], ["ev-2"])

    def test_different_units_are_not_converted_or_treated_as_equal(self):
        profile = {"method": {"cutoff": "500 eV"}}
        manifest = make_manifest(
            [claim("cutoff", "500 Ry", "ev-1")],
            [evidence("ev-1", "Cutoff: 500 Ry", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.cutoff")
        self.assertEqual(result["status"], SOURCE_MISMATCH)

    def test_evidence_id_text_and_source_location_are_preserved_without_mutation(self):
        profile = {"method": {"xc": "PBE"}}
        original_evidence = evidence("ev-7", "Exchange-correlation functional: PBE", 7)
        manifest = make_manifest(
            [claim("xc", "PBE", "ev-7", "Exchange-correlation functional",
                   source_text="Exchange-correlation functional: PBE",
                   source={"part": "word/document.xml", "paragraph": 7})],
            [original_evidence],
        )
        before = copy.deepcopy(manifest)
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.xc")
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ["ev-7"])
        self.assertEqual(result["evidence"][0]["text"], "Exchange-correlation functional: PBE")
        self.assertEqual(result["evidence"][0]["source"]["paragraph"], 7)
        self.assertEqual(manifest, before)

    def test_unscoped_claim_cannot_be_assigned_to_multiple_system_profile_fields(self):
        profile = {"systems": {"Cu": {"charge": 0}, "SnCu": {"charge": 0}}}
        manifest = make_manifest(
            [claim("charge", 0, "ev-1")],
            [evidence("ev-1", "Charge: 0", 1)],
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

    def test_key_equals_value_numeric_format_is_normalised_but_unit_is_not_inferred(self):
        profile = {"method": {"cutoff": 500}}
        manifest = make_manifest(
            [claim("cutoff", "Cutoff = 5.00e2 Ry", "ev-1")],
            [evidence("ev-1", "Cutoff = 5.00e2 Ry", 1)],
        )
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

    def test_multi_cell_table_claim_returns_every_referenced_original_evidence_id(self):
        ids = ["cell-1", "cell-2", "cell-3"]
        cells = ["Multiplicities", "2", "4"]
        row_claim = table_row_claim("multiplicities", "Multiplicities", "2 | 4", ids, cells)
        manifest = make_manifest([row_claim], table_evidence(ids, cells))
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicities": "2 | 4"}}, manifest),
            "method.multiplicities",
        )
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ids)
        self.assertEqual([item["evidence_id"] for item in result["evidence"]], ids)

    def test_table_label_and_each_value_cell_keep_own_text_and_location(self):
        ids = ["cell-label", "cell-value"]
        cells = ["Multiplicity", "2"]
        row_claim = table_row_claim("multiplicity", "Multiplicity", "2", ids, cells)
        manifest = make_manifest([row_claim], table_evidence(ids, cells))
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicity": 2}}, manifest),
            "method.multiplicity",
        )
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(
            [(item["text"], item["source"]["column"], item["contribution"])
             for item in result["evidence"]],
            [("Multiplicity", 1, "field_label"), ("2", 2, "field_value")],
        )
        self.assertTrue(all(
            item["text"] == item["evidence_text"] for item in result["evidence"]
        ))
        self.assertTrue(all(
            item["claim_source_text"] == "Multiplicity | 2" for item in result["evidence"]
        ))

    def test_label_cell_alone_cannot_support_a_value_when_second_cell_is_missing(self):
        ids = ["cell-label", "cell-value"]
        cells = ["Multiplicity", "2"]
        row_claim = table_row_claim("multiplicity", "Multiplicity", "2", ids, cells)
        # The second original evidence record is missing, despite being cited by the claim.
        manifest = make_manifest([row_claim], [table_evidence(ids, cells)[0]])
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicity": 2}}, manifest),
            "method.multiplicity",
        )
        self.assertEqual(result["status"], NEEDS_REVIEW)
        self.assertEqual(result["missing_evidence_ids"], ["cell-value"])
        self.assertEqual([item["text"] for item in result["evidence"]], ["Multiplicity"])

    def test_nonexistent_source_reference_fails_closed_and_is_reported(self):
        ids = ["cell-label", "cell-missing"]
        cells = ["Multiplicity", "2"]
        row_claim = table_row_claim("multiplicity", "Multiplicity", "2", ids, cells)
        # Sources references cell-missing but Manifest evidence does not contain it.
        manifest = make_manifest([row_claim], [table_evidence(ids, cells)[0]])
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicity": 2}}, manifest),
            "method.multiplicity",
        )
        self.assertEqual(result["status"], NEEDS_REVIEW)
        self.assertIn("cell-missing", result["evidence_ids"])
        self.assertEqual(result["missing_evidence_ids"], ["cell-missing"])
        self.assertFalse(any(
            item["evidence_id"] == "cell-missing" for item in result["evidence"]
        ))

    def test_sources_text_or_location_mismatch_fails_closed(self):
        ids = ["cell-label", "cell-value"]
        cells = ["Multiplicity", "2"]
        row_claim = table_row_claim("multiplicity", "Multiplicity", "2", ids, cells)
        row_claim["sources"][1]["source_text"] = "3"
        manifest = make_manifest([row_claim], table_evidence(ids, cells))
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicity": 2}}, manifest),
            "method.multiplicity",
        )
        self.assertEqual(result["status"], NEEDS_REVIEW)
        self.assertTrue(result["provenance_issues"])

    def test_duplicate_same_value_row_claims_preserve_all_cell_evidence(self):
        ids1, cells1 = ["r1-label", "r1-value"], ["Multiplicity", "2"]
        ids2, cells2 = ["r2-label", "r2-value"], ["Multiplicity", "2"]
        claims = [
            table_row_claim("multiplicity", "Multiplicity", "2", ids1, cells1, row=1),
            table_row_claim("multiplicity", "Multiplicity", "2", ids2, cells2, row=2),
        ]
        records = table_evidence(ids1, cells1, row=1) + table_evidence(ids2, cells2, row=2)
        result = self.result_for(
            reconcile_project_profile({"method": {"multiplicity": 2}}, make_manifest(claims, records)),
            "method.multiplicity",
        )
        self.assertEqual(result["status"], SOURCE_SUPPORTED)
        self.assertEqual(result["evidence_ids"], ids1 + ids2)
        self.assertEqual(len(result["evidence"]), 4)

    def test_same_field_in_different_systems_and_work_packages_does_not_cross_match(self):
        profile = {
            "systems": {
                "Cu-20": {"atom_count": 83},
                "SnCu-20": {"atom_count": 84},
            },
            "tasks": {
                "WP1": {"candidate_count": 2},
                "WP2": {"candidate_count": 1},
            },
        }
        claims = [
            claim("atom_count", 83, "ev-cu", context={"system_id": "Cu-20"}),
            claim("atom_count", 84, "ev-sncu", context={"system_id": "SnCu-20"}),
            claim("candidate_count", 2, "ev-wp1", context={"work_package": "WP1"}),
            claim("candidate_count", 1, "ev-wp2", context={"work_package": "WP2"}),
        ]
        records = [
            evidence("ev-cu", "Atom count: 83", 1),
            evidence("ev-sncu", "Atom count: 84", 2),
            evidence("ev-wp1", "Candidate count: 2", 3),
            evidence("ev-wp2", "Candidate count: 1", 4),
        ]
        report = reconcile_project_profile(profile, make_manifest(claims, records))
        cu = self.result_for(report, "systems.Cu-20.atom_count")
        sncu = self.result_for(report, "systems.SnCu-20.atom_count")
        wp1 = self.result_for(report, "tasks.WP1.candidate_count")
        wp2 = self.result_for(report, "tasks.WP2.candidate_count")
        self.assertEqual(cu["status"], SOURCE_SUPPORTED)
        self.assertEqual(sncu["status"], SOURCE_SUPPORTED)
        self.assertEqual(wp1["status"], SOURCE_SUPPORTED)
        self.assertEqual(wp2["status"], SOURCE_SUPPORTED)
        self.assertEqual(cu["evidence_ids"], ["ev-cu"])
        self.assertEqual(sncu["evidence_ids"], ["ev-sncu"])
        self.assertEqual(wp1["evidence_ids"], ["ev-wp1"])
        self.assertEqual(wp2["evidence_ids"], ["ev-wp2"])

    def test_missing_or_nonunique_system_wp_context_is_needs_review(self):
        profile = {
            "systems": {"Cu-20": {"atom_count": 83}},
            "tasks": {"WP1": {"candidate_count": 2}},
        }
        claims = [
            claim("atom_count", 83, "ev-1"),  # system_id missing
            claim("candidate_count", 2, "ev-2"),  # work_package missing
        ]
        manifest = make_manifest(
            claims, [evidence("ev-1", "Atom count: 83", 1), evidence("ev-2", "Candidate count: 2", 2)]
        )
        report = reconcile_project_profile(profile, manifest)
        self.assertEqual(self.result_for(report, "systems.Cu-20.atom_count")["status"], NEEDS_REVIEW)
        self.assertEqual(self.result_for(report, "tasks.WP1.candidate_count")["status"], NEEDS_REVIEW)

    def test_scoped_claim_cannot_support_global_field_without_unique_scope(self):
        profile = {"method": {"xc": "PBE"}}
        manifest = make_manifest(
            [claim("xc", "PBE", "ev-1", context={"system_id": "Cu-20"})],
            [evidence("ev-1", "XC: PBE", 1)],
        )
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.xc")
        self.assertEqual(result["status"], NEEDS_REVIEW)

    def test_unset_profile_field_is_visible_and_needs_review(self):
        report = reconcile_project_profile(
            {"tasks": {"WP1": {"orientation_scope": None}}}, make_manifest()
        )
        result = self.result_for(report, "tasks.WP1.orientation_scope")
        self.assertEqual(result["status"], NEEDS_REVIEW)

    def test_claim_without_complete_provenance_cannot_be_supported(self):
        profile = {"method": {"xc": "PBE"}}
        manifest = make_manifest([{"field": "xc", "label": "xc", "value": "PBE"}])
        result = self.result_for(reconcile_project_profile(profile, manifest), "method.xc")
        self.assertEqual(result["status"], NEEDS_REVIEW)


if __name__ == "__main__":
    unittest.main()
