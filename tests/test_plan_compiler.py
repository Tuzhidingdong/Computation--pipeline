from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from pipeline_contracts.plan_compiler import read_frozen_docx, compile_docx, detect_conflicts
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
        self.assertEqual([b.kind for b in blocks],
                         ["paragraph", "paragraph", "table_cell", "table_cell"])
        self.assertEqual(blocks[0].style, "Heading1")
        self.assertEqual(blocks[2].location["table"], 1)
        self.assertEqual(blocks[3].location["column"], 2)
        self.assertEqual(result.manifest["sections"][0]["heading"], "Plan")
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
                "--fragment-spin-resolution", "preserve_detailed_six_correct_summary",
                "--confirmed-by", "owner", "--rationale", "Owner confirmed the detailed count.",
                "--output", str(resolved_path),
            ])
            resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertFalse(any(x["code"].startswith("WP1_") for x in resolved["diagnostics"]))
        self.assertEqual(resolved["confirmed_resolutions"]["wp1_orientation_scope"], "per_catalyst")

    def test_labelled_values_are_not_promoted_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            make_docx(path)
            result = compile_docx(path, project_id="test")
        self.assertIsNone(result.calculation_plan)
        self.assertTrue(result.manifest["unresolved_definitions"])


if __name__ == "__main__":
    unittest.main()
