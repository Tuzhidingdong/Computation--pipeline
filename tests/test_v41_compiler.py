from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from projects.corr_dft_v4_1.plan_compiler import compile_v41_docx


def write_docx(path: Path, body_xml: str):
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + body_xml + '</w:body></w:document>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


class V41CompilerTests(unittest.TestCase):
    def test_v41_compiler_keeps_profile_out_of_docx_structured_fields_and_preserves_blockers(self):
        body = """
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Frozen plan</w:t></w:r></w:p>
        <w:p><w:r><w:t>Cutoff: 500 Ry</w:t></w:r></w:p>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            result = compile_v41_docx(path, plan_version="v4.1")
        manifest = result.manifest
        self.assertEqual(manifest["systems"], [])
        self.assertEqual(manifest["models"], [])
        self.assertEqual(manifest["method"]["cutoff"]["values"], ["500 Ry"])
        self.assertEqual(manifest["tasks"], [])
        self.assertEqual(manifest["profile_overlay"]["values"]["systems"]["Cu-20"]["complete_atom_count"], 83)
        self.assertEqual(manifest["profile_overlay"]["values"]["systems"]["SnCu-20"]["explicit_valence_electrons"], 426)
        blockers = [item for item in result.diagnostics if item["code"].startswith("WP1_")]
        self.assertEqual({item["code"] for item in blockers}, {
            "WP1_ORIENTATION_SCOPE_UNRESOLVED", "WP1_FRAGMENT_SPIN_COUNT_MISMATCH"
        })
        self.assertTrue(all(item["blocks_execution"] is True for item in blockers))
        self.assertEqual(manifest["compilation_status"], "BLOCKED")

    def test_fifteen_docking_orientations_are_profile_only_without_docx_evidence(self):
        body = '<w:p><w:r><w:t>Frozen plan overview</w:t></w:r></w:p>'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            manifest = compile_v41_docx(path).manifest

        target = next(item for item in manifest["profile_reconciliation"]
                      if item["field"] == "tasks.WP1.support_cluster_docking_orientation_count")
        provenance = manifest["profile_field_provenance"][target["field"]]
        self.assertEqual(target["profile_value"], 15)
        self.assertEqual(target["docx_status"], "absent")
        self.assertEqual(target["status"], "profile_only")
        self.assertEqual(target["docx_evidence_ids"], [])
        self.assertEqual(provenance["status"], "profile")
        self.assertEqual(provenance["evidence_ids"], [])
        self.assertEqual(manifest["field_provenance"]["tasks"]["status"], "absent")

    def test_unstructured_docx_method_mention_is_unresolved_not_profile_filled(self):
        body = (
            '<w:p><w:r><w:t>The CP2K cutoff value must be confirmed before use.</w:t></w:r></w:p>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            manifest = compile_v41_docx(path).manifest

        self.assertEqual(manifest["method"], {})
        self.assertEqual(manifest["field_provenance"]["method"]["status"], "unresolved")
        target = next(item for item in manifest["profile_reconciliation"]
                      if item["field"] == "method.cutoff_ry")
        self.assertEqual(target["docx_status"], "unresolved")
        self.assertEqual(target["status"], "needs_review")
        self.assertEqual(target["docx_evidence_ids"], ["docx-block-000001"])


    def test_unstructured_orientation_text_is_not_promoted_to_profile_fact(self):
        body = (
            '<w:p><w:r><w:t>WP1 considers 15 docking orientations, '
            'but the scope is not stated here.</w:t></w:r></w:p>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            manifest = compile_v41_docx(path).manifest

        target = next(item for item in manifest["profile_reconciliation"]
                      if item["field"] == "tasks.WP1.support_cluster_docking_orientation_count")
        self.assertEqual(target["docx_status"], "unresolved")
        self.assertEqual(target["status"], "needs_review")
        self.assertEqual(target["docx_evidence_ids"], ["docx-block-000001"])
        self.assertTrue(any(
            item["field"] == "tasks" and item["work_package"] == "WP1"
            and item["evidence_ids"] == ["docx-block-000001"]
            for item in manifest["unresolved_structured_fields"]
        ))

    def test_docx_profile_value_mismatch_is_reported_without_profile_override(self):
        body = """
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Cu-20</w:t></w:r></w:p>
        <w:p><w:r><w:t>Formula: Cu15C28H20O19</w:t></w:r></w:p>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            manifest = compile_v41_docx(path).manifest

        model = next(item for item in manifest["models"] if item["model_id"] == "Cu-20")
        self.assertEqual(model["properties"]["formula"][0]["value"], "Cu15C28H20O19")
        target = next(item for item in manifest["profile_reconciliation"]
                      if item["field"] == "systems.Cu-20.complete_formula")
        self.assertEqual(target["docx_status"], "docx_evidence")
        self.assertEqual(target["status"], "conflict")
        self.assertEqual(target["docx_evidence_ids"], ["docx-block-000002"])
        self.assertEqual(manifest["profile_overlay"]["values"]["systems"]["Cu-20"]["complete_formula"],
                         "Cu15C28H20O20")

    def test_matching_docx_system_formula_is_evidence_linked_and_reconciled(self):
        body = """
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Cu-20</w:t></w:r></w:p>
        <w:p><w:r><w:t>Formula: Cu15C28H20O20</w:t></w:r></w:p>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            write_docx(path, body)
            manifest = compile_v41_docx(path).manifest

        model = next(item for item in manifest["models"] if item["model_id"] == "Cu-20")
        self.assertEqual(model["properties"]["formula"][0]["value"], "Cu15C28H20O20")
        target = next(item for item in manifest["profile_reconciliation"]
                      if item["field"] == "systems.Cu-20.complete_formula")
        self.assertEqual(target["docx_status"], "docx_evidence")
        self.assertEqual(target["status"], "consistent")
        self.assertEqual(target["docx_evidence_ids"], ["docx-block-000002"])
        self.assertEqual(manifest["field_provenance"]["models.Cu-20.formula"]["status"],
                         "docx_evidence")


if __name__ == "__main__":
    unittest.main()
