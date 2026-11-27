from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from pipeline_contracts.plan_compiler import read_frozen_docx, compile_docx, detect_conflicts
from pipeline_contracts.plan_compiler.manifest import extract_claims


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
        self.assertEqual([b.kind for b in blocks],
                         ["paragraph", "paragraph", "table_cell", "table_cell"])
        self.assertEqual(blocks[0].style, "Heading1")
        self.assertEqual(blocks[2].location["table"], 1)
        self.assertEqual(blocks[3].location["column"], 2)
        result = compile_docx(path, project_id="test")
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

    def test_labelled_values_are_not_promoted_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.docx"
            make_docx(path)
            result = compile_docx(path, project_id="test")
        self.assertIsNone(result.calculation_plan)
        self.assertTrue(result.manifest["unresolved_definitions"])


if __name__ == "__main__":
    unittest.main()
