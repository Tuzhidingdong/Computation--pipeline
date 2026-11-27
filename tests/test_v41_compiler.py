from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from projects.corr_dft_v4_1.plan_compiler import compile_v41_docx


class V41CompilerTests(unittest.TestCase):
    def test_v41_compiler_injects_frozen_profile_and_known_blockers(self):
        xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Frozen plan</w:t></w:r></w:p>
        <w:p><w:r><w:t>Cutoff: 500 Ry</w:t></w:r></w:p>
        </w:body></w:document>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            result = compile_v41_docx(path, plan_version="v4.1")
        manifest = result.manifest
        self.assertEqual(manifest["systems"][0]["system_id"], "Cu-20")
        self.assertEqual(manifest["systems"][0]["complete_atom_count"], 83)
        self.assertEqual(manifest["systems"][1]["explicit_valence_electrons"], 426)
        self.assertEqual({x["code"] for x in result.diagnostics}, {
            "WP1_ORIENTATION_SCOPE_UNRESOLVED", "WP1_FRAGMENT_SPIN_COUNT_MISMATCH"
        })
        self.assertEqual(manifest["compilation_status"], "BLOCKED")
        self.assertTrue(manifest["evidence"])


if __name__ == "__main__":
    unittest.main()
