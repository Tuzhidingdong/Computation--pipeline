from __future__ import annotations
import tempfile
import hashlib
import unittest
from pathlib import Path
from zipfile import ZipFile

from pipeline_contracts.plan_compiler import read_frozen_docx, compile_docx, detect_conflicts
from pipeline_contracts.plan_compiler.docx_reader import ExtractedBlock
from pipeline_contracts.plan_compiler.manifest import build_project_manifest
from pipeline_contracts.plan_compiler.manifest import extract_claims
from pipeline_contracts.plan_compiler import confirm_manifest_claims
from pipeline_contracts.cli import main as cli_main


def make_docx(path: Path):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Plan</w:t></w:r></w:p>
        <w:p><w:r><w:t>Cutoff: 500 Ry</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Multiplicity</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body></w:document>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


class PlanCompilerTests(unittest.TestCase):
    def test_docx_extracts_heading_paragraph_and_table_cells_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            make_docx(path)
            blocks = read_frozen_docx(path)
            result = compile_docx(path, project_id="test")
            source_size = path.stat().st_size
            source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual([b.kind for b in blocks],
                         ["paragraph", "paragraph", "table_cell", "table_cell"])
        self.assertEqual(blocks[0].style, "Heading1")
        self.assertEqual(blocks[2].location["table"], 1)
        self.assertEqual(blocks[3].location["column"], 2)
        self.assertEqual(result.manifest["sections"][0]["heading"], "Plan")
        self.assertEqual(result.manifest["source_document"]["file_name"], "plan.docx")
        self.assertEqual(result.manifest["source_document"]["size_bytes"], source_size)
        self.assertEqual(result.manifest["source_document"]["sha256"], source_sha256)
        table_claim = next(x for x in result.manifest["claims"] if x.get("field") == "multiplicity")
        self.assertEqual(table_claim["value"], "2")

    def test_conflicting_labelled_values_block_without_discarding_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
            <w:p><w:r><w:t>Cutoff: 500 Ry</w:t></w:r></w:p>
            <w:p><w:r><w:t>Cutoff: 600 Ry</w:t></w:r></w:p>
            </w:body></w:document>"""
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            result = compile_docx(path, project_id="test")
        self.assertEqual(result.manifest["compilation_status"], "BLOCKED")
        self.assertEqual(len(result.manifest["evidence"]), 2)
        self.assertEqual(result.diagnostics[0]["code"], "PLAN_FIELD_CONFLICT")

    def test_owner_confirmation_is_auditable_and_removes_only_selected_unresolved_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            make_docx(path)
            manifest = compile_docx(path, project_id="test").manifest
            evidence_id = next(x["evidence_id"] for x in manifest["claims"]
                               if x.get("field") == "cutoff")
            confirmed = confirm_manifest_claims(
                manifest, evidence_ids=[evidence_id], confirmer="owner",
                rationale="Confirmed against the frozen approved method table",
            )
        claim = next(x for x in confirmed["claims"] if x.get("field") == "cutoff")
        self.assertEqual(claim["status"], "user_confirmed")
        self.assertEqual(len(confirmed["confirmations"]), 1)
        self.assertFalse(any(x["evidence_id"] == evidence_id
                             for x in confirmed["unresolved_definitions"]))

    def test_v41_cli_writes_blocked_manifest_instead_of_selecting_ambiguous_values(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "frozen.docx"
            make_docx(docx)
            output = Path(tmp) / "manifest.json"
            code = cli_main(["compile-v41-docx", str(docx), "--plan-version", "v4.1",
                             "--output", str(output)])
            self.assertEqual(code, 2)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["compilation_status"], "BLOCKED")

    def test_v41_resolution_cli_records_owner_decisions(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "frozen.docx"
            make_docx(docx)
            manifest_path = Path(tmp) / "manifest.json"
            cli_main(["compile-v41-docx", str(docx), "--output", str(manifest_path)])
            resolved_path = Path(tmp) / "resolved.json"
            code = cli_main([
                "resolve-v41-planning", str(manifest_path),
                "--orientation-scope", "per_catalyst",
                "--fragment-spin-resolution", "retain_all_six",
                "--confirmed-by", "owner", "--rationale", "Owner confirmed the detailed count.",
                "--output", str(resolved_path),
            ])
            resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertFalse(any(x["code"].startswith("WP1_") for x in resolved["diagnostics"]))
        self.assertEqual(resolved["confirmed_resolutions"]["wp1_orientation_scope"], "per_catalyst")
        self.assertEqual(resolved["confirmed_resolutions"]["wp1_fragment_spin_count_resolution"], "retain_all_six")
        self.assertEqual(len(resolved["confirmed_resolutions"]["wp1_selected_fragment_spin_candidates"]), 6)


    def test_repeated_charge_zero_keeps_both_evidence_without_false_conflict(self):
        blocks = [
            ExtractedBlock("paragraph", "CHARGE = 0",
                           {"part": "word/document.xml", "paragraph": 79}),
            ExtractedBlock("paragraph", "CHARGE = 0",
                           {"part": "word/document.xml", "paragraph": 80}),
        ]
        claims, evidence, diagnostics = extract_claims(blocks)
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(evidence), 2)
        self.assertEqual([claim["value"] for claim in claims], ["0", "0"])
        self.assertEqual([claim["evidence_id"] for claim in claims],
                         ["docx-block-000001", "docx-block-000002"])

    def test_value_normalisation_handles_case_spacing_and_operator_formatting_only(self):
        claims = [
            {"field": "Functional", "value": "PBE - D3 ( BJ )",
             "evidence_id": "docx-block-000001", "source": {"paragraph": 1},
             "source_text": "Functional: PBE - D3 ( BJ )"},
            {"field": "functional", "value": "pbe-d3(bj)",
             "evidence_id": "docx-block-000002", "source": {"paragraph": 2},
             "source_text": "functional: pbe-d3(bj)"},
        ]
        self.assertEqual(detect_conflicts(claims), [])

    def test_true_charge_conflict_reports_both_raw_values_and_sources(self):
        claims = [
            {"field": "CHARGE", "value": "0", "evidence_id": "docx-block-000079",
             "source": {"paragraph": 79}, "source_text": "CHARGE = 0"},
            {"field": "charge", "value": "1", "evidence_id": "docx-block-000080",
             "source": {"paragraph": 80}, "source_text": "CHARGE = 1"},
        ]
        diagnostics = [item.as_dict() for item in detect_conflicts(claims)]
        self.assertEqual(len(diagnostics), 1)
        diagnostic = diagnostics[0]
        self.assertEqual(diagnostic["code"], "PLAN_FIELD_CONFLICT")
        self.assertEqual(diagnostic["evidence_ids"],
                         ["docx-block-000079", "docx-block-000080"])
        self.assertEqual(
            [group["raw_values"][0] for group in diagnostic["conflicting_values"]],
            ["0", "1"],
        )
        self.assertEqual(
            [group["evidence"][0]["source"]["paragraph"]
             for group in diagnostic["conflicting_values"]],
            [79, 80],
        )

    def test_different_fields_with_same_value_do_not_conflict_and_units_are_preserved(self):
        different_fields = [
            {"field": "CHARGE", "value": "0", "evidence_id": "docx-block-000001"},
            {"field": "MULTIPLICITY", "value": "0", "evidence_id": "docx-block-000002"},
        ]
        self.assertEqual(detect_conflicts(different_fields), [])
        unit_values = [
            {"field": "cutoff", "value": "500 Ry", "evidence_id": "docx-block-000003"},
            {"field": "cutoff", "value": "500 Ha", "evidence_id": "docx-block-000004"},
        ]
        self.assertEqual(len(detect_conflicts(unit_values)), 1)

    def test_ase_vibrations_and_copyready_text_claims_are_kept_in_separate_fields(self):
        blocks = [
            ExtractedBlock("paragraph", "ase_vibrations__cp2k true",
                           {"part": "word/document.xml", "paragraph": 1}),
            ExtractedBlock("paragraph", "ase_vibrations__cp2k TRUE",
                           {"part": "word/document.xml", "paragraph": 2}),
            ExtractedBlock("paragraph", "copyready_english_text enabled",
                           {"part": "word/document.xml", "paragraph": 3}),
            ExtractedBlock("paragraph", "copyready_english_text ENABLED",
                           {"part": "word/document.xml", "paragraph": 4}),
        ]
        claims, _, diagnostics = extract_claims(blocks)
        self.assertEqual(diagnostics, [])
        by_field = {}
        for claim in claims:
            by_field.setdefault(claim["field"], []).append(claim["value"])
        self.assertEqual(by_field["ase_vibrations_cp2k"], ["true", "TRUE"])
        self.assertEqual(by_field["copyready_english_text"], ["enabled", "ENABLED"])

    def test_docx_structures_system_model_method_task_dependency_and_resources_with_evidence(self):
        blocks = [
            ExtractedBlock("paragraph", "Cu-20",
                           {"part": "word/document.xml", "paragraph": 1}, style="Heading1"),
            ExtractedBlock("paragraph", "Formula: Cu15C28H20O20",
                           {"part": "word/document.xml", "paragraph": 2}),
            ExtractedBlock("paragraph", "Atom Count: 83",
                           {"part": "word/document.xml", "paragraph": 3}),
            ExtractedBlock("paragraph", "CHARGE: 0",
                           {"part": "word/document.xml", "paragraph": 4}),
            ExtractedBlock("paragraph", "ADDED_MOS 80",
                           {"part": "word/document.xml", "paragraph": 5}),
            ExtractedBlock("paragraph", "WP1: Docking candidate generation",
                           {"part": "word/document.xml", "paragraph": 6}),
            ExtractedBlock("paragraph", "Generate the explicitly specified docking candidates.",
                           {"part": "word/document.xml", "paragraph": 7}),
            ExtractedBlock("paragraph", "WP2: Local Hessian calculations",
                           {"part": "word/document.xml", "paragraph": 8}),
            ExtractedBlock("paragraph", "WP2 depends on WP1",
                           {"part": "word/document.xml", "paragraph": 9}),
            ExtractedBlock("paragraph", "Nodes: 2",
                           {"part": "word/document.xml", "paragraph": 10}),
            ExtractedBlock("paragraph", "Input files: seed.xyz",
                           {"part": "word/document.xml", "paragraph": 11}),
            ExtractedBlock("paragraph", "Output files: candidates.extxyz",
                           {"part": "word/document.xml", "paragraph": 12}),
        ]
        manifest = build_project_manifest(blocks, project_id="test")
        self.assertEqual(manifest["systems"][0]["system_id"], "Cu-20")
        model = next(item for item in manifest["models"] if item["model_id"] == "Cu-20")
        self.assertEqual(model["properties"]["formula"][0]["value"], "Cu15C28H20O20")
        self.assertEqual(manifest["method"]["added_mos"]["values"], ["80"])
        self.assertEqual(manifest["field_provenance"]["method.added_mos"]["status"],
                         "docx_evidence")
        self.assertEqual(manifest["field_provenance"]["method.added_mos"]["evidence_ids"],
                         ["docx-block-000005"])
        self.assertEqual([item["work_package"] for item in manifest["tasks"]], ["WP1", "WP2"])
        self.assertTrue(any(
            item.get("dependent") == "WP2" and item.get("prerequisite") == "WP1"
            for item in manifest["dependencies"]
        ))
        self.assertEqual(manifest["resources"]["nodes"][0]["value"], "2")
        self.assertEqual(manifest["input_outputs"]["inputs"][0]["value"], "seed.xyz")
        self.assertEqual(manifest["input_outputs"]["outputs"][0]["value"], "candidates.extxyz")

    def test_relevant_but_unstructured_method_text_is_marked_unresolved(self):
        blocks = [ExtractedBlock(
            "paragraph", "The CP2K cutoff value must be confirmed before use.",
            {"part": "word/document.xml", "paragraph": 1},
        )]
        manifest = build_project_manifest(blocks, project_id="test")
        self.assertEqual(manifest["method"], {})
        self.assertEqual(manifest["field_provenance"]["method"]["status"], "unresolved")
        unresolved = manifest["field_provenance"]["method"]["evidence_ids"]
        self.assertEqual(unresolved, ["docx-block-000001"])

    def test_unmentioned_resource_category_is_explicitly_absent(self):
        blocks = [ExtractedBlock(
            "paragraph", "General project overview.",
            {"part": "word/document.xml", "paragraph": 1},
        )]
        manifest = build_project_manifest(blocks, project_id="test")
        self.assertEqual(manifest["field_provenance"]["resources"]["status"], "absent")
        self.assertEqual(manifest["field_provenance"]["resources"]["evidence_ids"], [])


    def test_table_row_claim_contains_all_cell_evidence(self):
        blocks = [
            ExtractedBlock("table_cell", "CHARGE", {"table": 1, "row": 1, "column": 1}),
            ExtractedBlock("table_cell", "0", {"table": 1, "row": 1, "column": 2}),
            ExtractedBlock("table_cell", "CHARGE", {"table": 1, "row": 2, "column": 1}),
            ExtractedBlock("table_cell", "1", {"table": 1, "row": 2, "column": 2}),
        ]
        claims, evidence, diagnostics = extract_claims(blocks)
        self.assertEqual(len(evidence), 4)
        self.assertEqual([claim["evidence_ids"] for claim in claims], [
            ["docx-block-000001", "docx-block-000002"],
            ["docx-block-000003", "docx-block-000004"],
        ])
        self.assertEqual(diagnostics[0]["evidence_ids"], [
            "docx-block-000001", "docx-block-000002",
            "docx-block-000003", "docx-block-000004",
        ])

    def test_unit_spacing_is_formatting_but_unit_changes_remain_conflicts(self):
        self.assertEqual(detect_conflicts([
            {"field": "cutoff", "value": "500Ry", "evidence_id": "e1"},
            {"field": "CUTOFF", "value": "500 Ry", "evidence_id": "e2"},
        ]), [])
        self.assertEqual(len(detect_conflicts([
            {"field": "cutoff", "value": "500 Ry", "evidence_id": "e3"},
            {"field": "cutoff", "value": "500 Ha", "evidence_id": "e4"},
        ])), 1)

    def test_same_field_in_separate_work_packages_is_not_cross_compared(self):
        self.assertEqual(detect_conflicts([
            {"field": "charge", "value": "0", "evidence_id": "e1",
             "context": {"work_package": "WP1"}},
            {"field": "charge", "value": "1", "evidence_id": "e2",
             "context": {"work_package": "WP2"}},
        ]), [])

    def test_labelled_values_are_not_promoted_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            make_docx(path)
            result = compile_docx(path, project_id="test")
        self.assertIsNone(result.calculation_plan)
        self.assertTrue(result.manifest["unresolved_definitions"])


if __name__ == "__main__":
    unittest.main()
