"""Regression tests for encoding-safe JSON CLI output."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline_contracts.cli import _emit_json
from pipeline_contracts.plan_compiler.compiler import write_manifest


class CliJsonEncodingTests(unittest.TestCase):
    def _render_with_encoding(self, payload: dict, encoding: str) -> tuple[str, dict]:
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding=encoding, errors="strict")
        try:
            with patch.object(sys, "stdout", stream):
                _emit_json(payload)
                stream.flush()
            raw = buffer.getvalue()
            rendered = raw.decode(encoding, errors="strict")
        finally:
            # TextIOWrapper owns the in-memory buffer; detach so BytesIO remains readable.
            try:
                stream.detach()
            except Exception:
                pass
        self.assertTrue(all(ord(char) < 128 for char in rendered))
        return rendered, json.loads(rendered)

    def test_superscript_two_and_other_unicode_round_trip_on_gbk_and_ascii(self):
        payload = {
            "method": "PBE-D3(BJ)",
            "basis": "TZV2P",
            "source_excerpt": "Boundary density: 1×10⁻⁶ e/Bohr³; squared term ²",
            "label": "温度 300 K",
        }
        for encoding in ("gbk", "ascii"):
            with self.subTest(encoding=encoding):
                rendered, restored = self._render_with_encoding(payload, encoding)
                self.assertIn(r"\\u00b2", rendered)
                self.assertEqual(restored, payload)

    def test_manifest_utf8_retains_unicode_and_stdout_matches_its_json_semantics(self):
        manifest = {
            "compilation_status": "BLOCKED",
            "claims": [{
                "field": "boundary_density",
                "value": "1×10⁻⁶ e/Bohr³",
                "source_text": "Boundary density target ²",
            }],
            "diagnostics": [{"message": "需要核验原始证据"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            write_manifest(manifest, path)
            encoded_file = path.read_bytes()
            self.assertIn("²".encode("utf-8"), encoded_file)
            self.assertIn("需要核验".encode("utf-8"), encoded_file)
            file_value = json.loads(encoded_file.decode("utf-8"))
            self.assertEqual(file_value, manifest)

            for encoding in ("gbk", "ascii"):
                with self.subTest(encoding=encoding):
                    _, stdout_value = self._render_with_encoding(file_value, encoding)
                    self.assertEqual(stdout_value, file_value)


if __name__ == "__main__":
    unittest.main()
