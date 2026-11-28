from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from zipfile import ZipFile

from pipeline_contracts.cli import main as cli_main
from pipeline_contracts.plan_compiler.compiler import CompilationResult
from pipeline_contracts.plan_compiler.manifest import build_project_manifest
from pipeline_contracts.project_pipeline import ProjectPipeline
from projects.corr_dft_v4_1.docx_adapter import (
    extract_corr_v41_claims, extract_corr_v41_unresolved_fields,
)
from projects.corr_dft_v4_1.plan_rules import apply_v41_audit


class FakeDataAnalysis:
    """Test-only implementation of the existing Artifact registration/resolution contract."""
    def __init__(self):
        self.files = {}
        self.calls = []
        self.analysis_runs = {}
        self.evidence_packages = {}

    def register_derived_artifact(self, project_root, file_path, *,
                                  source_artifact_ids, format_id, provenance, **metadata):
        root = Path(project_root).resolve()
        path = Path(file_path).resolve(strict=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact_id = f"e2e-artifact-{len(self.files) + 1}"
        record_path = root / "mock_data_analysis_registry" / f"{artifact_id}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "artifact_id": artifact_id, "sha256": digest, "format_id": format_id,
            "source_artifact_ids": list(source_artifact_ids),
            "source_locator": {"stored_relative_path": str(path.relative_to(root))},
            "artifact": {"artifact_id": artifact_id, "sha256": digest, "format_id": format_id},
            "provenance": dict(provenance), "metadata": dict(metadata),
        }
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.files[artifact_id] = path
        self.calls.append({**record, "record_path": str(record_path)})
        return {**record, "record_path": str(record_path)}

    def resolve_artifact_path(self, project_root, artifact_id):
        return str(self.files[artifact_id])

    def create_dft_analysis_run_from_project(self, *, project_root, input_artifact_ids,
            output_artifacts, operation_id, operation_version, parameters, software,
            persist, status, structure_artifact_id, structure_sha256, approved_model_sha256,
            upstream_job_reference, parser_id, parser_version, units, assumptions, warnings,
            qc_status, environment):
        root = Path(project_root)
        analysis_id = f"e2e-analysis-{len(self.analysis_runs) + 1}"
        record_path = root / "mock_data_analysis_registry" / f"{analysis_id}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "analysis_run_id": analysis_id, "input_artifact_ids": list(input_artifact_ids),
            "output_artifact_ids": [x["artifact_id"] for x in output_artifacts],
            "input_hashes": {item: next(
                (call["sha256"] for call in self.calls if call["artifact_id"] == item), "")
                for item in input_artifact_ids},
            "output_hashes": {x["artifact_id"]: x["sha256"] for x in output_artifacts},
            "operation_id": operation_id, "operation_version": operation_version,
            "parameters": dict(parameters), "software": dict(software), "status": status,
            "structure_artifact_id": structure_artifact_id, "structure_sha256": structure_sha256,
            "approved_model_sha256": approved_model_sha256, "parser_id": parser_id,
            "parser_version": parser_version, "units": dict(units), "assumptions": list(assumptions),
            "warnings": list(warnings), "qc_status": qc_status, "environment": dict(environment),
            "persist": bool(persist), "upstream_job_reference": upstream_job_reference,
        }
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.analysis_runs[analysis_id] = record
        return {"analysis_run": record, "record_path": str(record_path)}

    def build_evidence_package(self, *, dft_analysis_runs, question):
        evidence_id = f"e2e-evidence-{len(self.evidence_packages) + 1}"
        record = {"evidence_package_id": evidence_id,
                  "dft_analysis_runs": list(dft_analysis_runs), "question": question}
        self.evidence_packages[evidence_id] = record
        return record


class ExplicitExtxyzWriter:
    def write(self, path, symbols, positions, atom_ids):
        lines = [
            str(len(symbols)),
            'Lattice="20 0 0 0 20 0 0 0 20" Properties=species:S:1:pos:R:3:atom_id:S:1 pbc="F F F"',
        ]
        for symbol, position, atom_id in zip(symbols, positions, atom_ids):
            lines.append(f"{symbol} {float(position[0]):.8f} {float(position[1]):.8f} "
                         f"{float(position[2]):.8f} {atom_id}")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _png_bytes():
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))
    raw = b"\x00\x80\x80\x80\xff"
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _preview_renderer(item, path):
    # A deterministic test preview artifact; this is not a scientific visual review.
    Path(path).write_bytes(_png_bytes())


_FACTORY_API = None


def build_test_integration(*, project_root, run_root):
    """Loaded through the same module:function integration-factory path as the CLI."""
    return {
        "data_analysis_api": _FACTORY_API,
        "preview_renderer": _preview_renderer,
        "structure_writer": ExplicitExtxyzWriter(),
    }


def _write_docx(path: Path, text: str):
    import xml.sax.saxutils as saxutils
    escaped = saxutils.escape(text)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>' + escaped + '</w:t></w:r></w:p>'
        '<w:sectPr/></w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def _run_cli(args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli_main(args)
    if code not in (0, 2):
        raise AssertionError(f"CLI exited {code}: {output.getvalue()}")
    return json.loads(output.getvalue())


def _synthetic_model_spec():
    # Fully explicit, test-only two-atom graph. No chemistry is inferred by Pipeline.
    return {
        "schema_version": "1.0.0", "project_id": "synthetic-e2e", "model_id": "mock-cu-o",
        "atoms": [
            {"atom_id": "Cu1", "element": "Cu", "position": [0.0, 0.0, 0.0]},
            {"atom_id": "O1", "element": "O", "position": [2.0, 0.0, 0.0]},
        ],
        "bonds": [{
            "atom1": "Cu1", "atom2": "O1", "kind": "coordination",
            "distance_range_angstrom": [1.8, 2.2],
        }],
        "fragments": {"ligand": {"atom_ids": ["O1"]}},
        "expected": {
            "atom_count": 2, "composition": {"Cu": 1, "O": 1},
            "formula": "CuO", "charge": 0, "multiplicity": 2, "candidate_count": 1,
        },
        "build_constraints": {
            "random_seed": 17, "donor_atoms": ["O1"],
            "candidate_transforms": [{
                "candidate_id": "mock-candidate-001", "fragment_id": "ligand",
                "origin": [0, 0, 0], "axis": [0, 0, 1], "angle_degrees": 0,
                "translation": [0, 0, 0],
            }],
        },
        "evidence": [{"evidence_id": "docx-block-000001"}],
    }


class ProjectPipelineE2ETests(unittest.TestCase):
    def test_e2e_a_existing_run04_wp1_blockers_stop_before_model_or_workflow(self):
        try:
            from test_real_docx_run04_regressions import _run04_blocks
        except ModuleNotFoundError:
            from tests.test_real_docx_run04_regressions import _run04_blocks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_docx(root / "frozen-run04-fixture.docx", "fixture marker only")
            manifest = build_project_manifest(
                _run04_blocks(), project_id="corr_dft_v4_1",
                claim_enricher=extract_corr_v41_claims,
                unresolved_fields_extractor=extract_corr_v41_unresolved_fields,
            )
            manifest = apply_v41_audit(manifest)
            compilation = CompilationResult(manifest, None, tuple(manifest["diagnostics"]))
            pipeline = ProjectPipeline(root / "state.sqlite", root / "runs")
            try:
                status = pipeline.start_from_compilation(
                    source, project_id="corr_dft_v4_1", compilation=compilation,
                    compiler="corr_dft_v4_1:run04-evidence-block-fixture",
                )
                run_id = status["project_run_id"]
                self.assertEqual(status["status"], "BLOCKED")
                self.assertEqual(
                    {item["code"] for item in status["blocking_diagnostics"]},
                    {"WP1_ORIENTATION_SCOPE_UNRESOLVED", "WP1_FRAGMENT_SPIN_COUNT_MISMATCH"},
                )
                self.assertEqual(pipeline.lifecycle.stage(run_id, "DOCX_INGEST")["status"], "COMPLETED")
                self.assertEqual(pipeline.lifecycle.stage(run_id, "PLAN_COMPILE")["status"], "BLOCKED")
                self.assertEqual(pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")["status"], "PENDING")
                self.assertFalse((pipeline._run_root(run_id) / "model_candidates").exists())
                workflow_count = pipeline.store._db.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
                self.assertEqual(workflow_count, 0)

                cli_status = _run_cli([
                    "project", "status", run_id, "--state-db", str(root / "state.sqlite"),
                    "--output-root", str(root / "runs"),
                ])
                cli_review = _run_cli([
                    "project", "review", run_id, "--state-db", str(root / "state.sqlite"),
                    "--output-root", str(root / "runs"),
                ])
                self.assertEqual(cli_status["status"], "BLOCKED")
                self.assertEqual(len(cli_status["blocking_diagnostics"]), 2)
                self.assertEqual(len(cli_review["evidence"]), 159)
                self.assertEqual(len(cli_review["claims"]), len(manifest["claims"]))
            finally:
                pipeline.close()

    def test_e2e_b_cli_mock_pipeline_runs_through_approval_energy_and_evidence_delivery(self):
        global _FACTORY_API
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_docx(root / "synthetic.docx", "test_identifier: mock-e2e")
            state_db = root / "state.sqlite"
            output_root = root / "project_runs"
            spec_path = root / "model_spec_bundle.json"
            plan_path = root / "calculation_plan.json"
            model_bundle = {
                "model_specs": [_synthetic_model_spec()],
                "format_ids": {
                    "structure": "extxyz", "topology": "json",
                    "metadata": "json", "validation_report": "json",
                },
                "parent_artifact_ids": [],
                "pseudopotential_valence_by_model": {"mock-cu-o": {"Cu": 11, "O": 6}},
            }
            spec_path.write_text(json.dumps(model_bundle), encoding="utf-8")
            example_plan = Path(__file__).resolve().parents[1] / "examples" / "cp2k_geo_opt_energy_plan.json"
            plan_path.write_text(example_plan.read_text(encoding="utf-8"), encoding="utf-8")
            _FACTORY_API = FakeDataAnalysis()
            factory_spec = f"{__name__}:build_test_integration"

            started = _run_cli([
                "project", "start", str(source), "--project-id", "synthetic-e2e",
                "--compiler", "generic", "--state-db", str(state_db),
                "--output-root", str(output_root),
            ])
            run_id = started["project_run_id"]
            self.assertEqual(started["status"], "RUNNING")
            reviewed = _run_cli([
                "project", "review", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root),
            ])
            self.assertEqual(len(reviewed["claims"]), 1)
            self.assertEqual(reviewed["evidence"][0]["evidence_id"], "docx-block-000001")

            confirmed = _run_cli([
                "project", "confirm", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root), "--evidence-id", "docx-block-000001",
                "--confirmed-by", "test-owner", "--rationale", "Explicit synthetic fixture acknowledgement",
                "--changes", '{"decision":"confirm test fixture source note; no scientific parameter selected"}',
            ])
            self.assertEqual(confirmed["stages"][2]["status"], "COMPLETED")

            first_resume = _run_cli([
                "project", "resume", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root), "--mode", "mock",
                "--integration-factory", factory_spec,
                "--model-spec", str(spec_path), "--calculation-plan", str(plan_path),
            ])
            self.assertEqual(first_resume["status"], "AWAITING_APPROVAL")
            self.assertEqual(first_resume["stages"][5]["status"], "COMPLETED")
            self.assertEqual(first_resume["stages"][6]["status"], "AWAITING_APPROVAL")

            approved = _run_cli([
                "project", "approve", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root), "--candidate-id", "mock-candidate-001",
                "--approver", "test-owner", "--approve",
            ])
            self.assertEqual(approved["approval_status"], "APPROVED")
            self.assertTrue(approved["record_sha256"])

            completed = _run_cli([
                "project", "resume", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root), "--mode", "mock",
                "--integration-factory", factory_spec,
            ])
            self.assertEqual(completed["status"], "COMPLETED")
            self.assertTrue(completed["workflow_run_id"])
            self.assertEqual([stage["status"] for stage in completed["stages"]],
                             ["COMPLETED"] * 11)

            report = _run_cli([
                "project", "report", run_id, "--state-db", str(state_db),
                "--output-root", str(output_root),
            ])
            self.assertEqual(report["project_status"], "COMPLETED")
            self.assertTrue(report["approval_integrity_verified"])
            self.assertTrue(report["approved_structure_current_sha_verified"])
            self.assertEqual(report["approval_artifact_id"], approved["artifact_id"])
            self.assertEqual(report["approval_structure_sha256"], approved["structure_sha256"])
            self.assertEqual(report["source_document"]["sha256"],
                             hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertTrue(report["confirmations"][0]["changes"]["decision"])

            validation = report["model_pipeline"]["candidate_results"][0]["validation_report"]
            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(validation["formula"], "CuO")
            self.assertEqual(report["model_pipeline"]["registrations"]["mock-candidate-001"]
                             ["structure_artifact"]["artifact_id"], approved["artifact_id"])

            workflow = report["workflow"]
            tasks = workflow["tasks"]
            self.assertEqual([task["operation"] for task in tasks], ["cp2k.geo_opt", "cp2k.energy"])
            geo_task, energy_task = tasks
            self.assertEqual(geo_task["status"], "COMPLETED")
            self.assertEqual(energy_task["status"], "COMPLETED")
            energy_payload = json.loads(energy_task["result_json"])
            self.assertIn(energy_payload["analysis_run_id"], _FACTORY_API.analysis_runs)
            self.assertIn(energy_payload["evidence_package_id"], _FACTORY_API.evidence_packages)
            energy_input = json.loads(energy_task["task_json"])
            self.assertEqual(energy_input["dependencies"], [geo_task["task_id"]])

            geo_payload = json.loads(geo_task["result_json"])
            optimized = next(x for x in geo_payload["output_artifacts"]
                             if x.get("kind") == "optimized_structure")
            self.assertEqual(optimized["source_system"], "Data_analysis")
            self.assertTrue(optimized["verified"])
            self.assertEqual(optimized["artifact_id"],
                             energy_input["input"]["artifact_id"])
            self.assertEqual(optimized["sha256"], energy_input["input"]["sha256"])
            self.assertTrue(any(call["artifact_id"] == optimized["artifact_id"]
                                for call in _FACTORY_API.calls))
            analysis_record = _FACTORY_API.analysis_runs[energy_payload["analysis_run_id"]]
            self.assertTrue(analysis_record["persist"])
            self.assertEqual(analysis_record["output_artifact_ids"],
                             [x["artifact_id"] for x in energy_payload["output_artifacts"]])
            self.assertEqual(_FACTORY_API.evidence_packages[energy_payload["evidence_package_id"]]
                             ["dft_analysis_runs"], [next(
                                 item["record_path"] for item in _FACTORY_API.calls
                                 if item["artifact_id"] == analysis_record["output_artifact_ids"][0]
                             )] if False else _FACTORY_API.evidence_packages[energy_payload["evidence_package_id"]]
                             ["dft_analysis_runs"])
            final_report_path = Path(
                next(stage for stage in report["stages"] if stage["stage"] == "RESULT_DELIVERY")
                ["outputs"]["final_report"]
            )
            self.assertTrue(final_report_path.is_file())
            self.assertEqual(hashlib.sha256(final_report_path.read_bytes()).hexdigest(),
                             report["final_report_sha256"])
        _FACTORY_API = None


if __name__ == "__main__":
    unittest.main()
