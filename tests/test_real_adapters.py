import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pipeline_contracts.models import (
    AnalysisRequest,
    ArtifactRef,
    CSTTaskRequest,
    TaskStatus,
)
from pipeline_contracts.real_adapters import RealCSTAdapter, RealDataAnalysisAdapter


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeDataAnalysisAPI:
    """Small API double with the exact function-level boundary of Agent A's DA branch."""

    def __init__(self, project_root: Path, expected_artifact_id: str, expected_hash: str):
        self.project_root = project_root
        self.expected_artifact_id = expected_artifact_id
        self.expected_hash = expected_hash
        self.calls = []
        self.run_path = project_root / "registry" / "analysis_runs" / "RUN-DFT-TEST.json"
        self.run_path.parent.mkdir(parents=True, exist_ok=True)

    def list_dft_readers(self, format_id=None):
        self.calls.append(("list_dft_readers", format_id))
        return [{
            "format_id": format_id or "finite_displacement_force_table",
            "reader_id": "python-csv",
            "registered_status": "available_with_python",
            "available": True,
            "availability_reason": "Python standard library",
        }]

    def read_dft_file(self, path, *, format_id=None, reader_id=None, **kwargs):
        self.calls.append(("read_dft_file", Path(path).resolve(), format_id, reader_id, kwargs))
        payload = Path(path).read_text(encoding="utf-8")
        return {
            "schema_version": "1.0.0",
            "status": self.reader_status,
            "format_id": format_id,
            "reader_id": reader_id or "python-csv",
            "reader_version": "Python standard library",
            "source_path": str(Path(path).resolve()),
            "source_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "data": {"row_count": 1, "result_kind": "synthetic-fixture"},
            "warnings": [],
            "error": "synthetic unavailable reader" if self.reader_status != "parsed" else None,
        }

    reader_status = "parsed"

    def list_dft_operations(self):
        self.calls.append(("list_dft_operations",))
        return [
            {"operation_id": "dft.artifact.read", "status": "implemented", "operation_version": "1.0.0"},
            {"operation_id": "dft.normalized_result.package", "status": "implemented", "operation_version": "1.0.0"},
        ]

    def get_dft_operation(self, operation_id):
        self.calls.append(("get_dft_operation", operation_id))
        return next((item for item in self.list_dft_operations() if item["operation_id"] == operation_id), None)

    def create_dft_analysis_run_from_project(self, **kwargs):
        self.calls.append(("create_dft_analysis_run_from_project", kwargs))
        self.assert_registered_input(kwargs["input_artifact_ids"])
        run_status = kwargs["status"]
        record = {
            "schema_version": "1.0.0",
            "analysis_run_id": "RUN-DFT-TEST",
            "operation_id": kwargs["operation_id"],
            "operation_version": kwargs["operation_version"],
            "input_artifact_ids": list(kwargs["input_artifact_ids"]),
            "output_artifact_ids": [],
            "input_hashes": {self.expected_artifact_id: self.expected_hash},
            "output_hashes": {},
            "parameters": dict(kwargs["parameters"]),
            "software": dict(kwargs["software"]),
            "status": run_status,
            "warnings": list(kwargs.get("warnings", [])),
            "assumptions": [],
            "dft_provenance": {"qc_status": kwargs["qc_status"], "units": {}},
        }
        self.run_path.write_text(json.dumps(record), encoding="utf-8")
        return {"analysis_run": record, "record_path": str(self.run_path)}

    def assert_registered_input(self, artifact_ids):
        if artifact_ids != [self.expected_artifact_id]:
            raise ValueError("adapter changed the owning Artifact ID")

    def run_dft_operation(self, operation_id, **kwargs):
        self.calls.append(("run_dft_operation", operation_id, kwargs))
        if operation_id != "dft.normalized_result.package":
            return {"status": "unsupported_operation", "error": operation_id}
        return {
            "status": "completed",
            "operation_id": operation_id,
            "operation_version": "1.0.0",
            "result": {
                "result_type": "normalized_dft_result",
                "analysis_run_id": kwargs["analysis_run"]["analysis_run_id"],
                "normalized_result": dict(kwargs["normalized_result"]),
            },
        }

    def build_evidence_package(self, *, dft_analysis_runs, question=None):
        self.calls.append(("build_evidence_package", tuple(map(str, dft_analysis_runs)), question))
        record = json.loads(Path(dft_analysis_runs[0]).read_text(encoding="utf-8"))
        return {
            "schema_version": "1.0.0",
            "evidence_package_id": "EV-TEST-DFT",
            "dft_report_count": 1,
            "dft_reports": [{
                "analysis_run_id": record["analysis_run_id"],
                "input_artifact_ids": record["input_artifact_ids"],
                "input_hashes": record["input_hashes"],
                "qc_status": record["dft_provenance"]["qc_status"],
            }],
        }


class DataAnalysisRealAdapterTests(unittest.TestCase):
    def _fixture(self, root: Path):
        source = root / "forces.tsv"
        source.write_text(
            "displacement_id,atom_index,force_x,force_y,force_z,force_unit\n"
            "synthetic-1,0,0.0,0.1,0.2,eV/angstrom\n",
            encoding="utf-8",
        )
        return source

    def test_real_adapter_calls_da_read_operation_provenance_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._fixture(root)
            project = root / "da-project"
            project.mkdir()
            artifact_id = "ART-SYNTHETIC-INPUT"
            digest = _sha(source)
            api = FakeDataAnalysisAPI(project, artifact_id, digest)
            adapter = RealDataAnalysisAdapter(project, api=api)

            outcome = adapter.analyze(AnalysisRequest(
                task_id="TASK-DA-REAL-1",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef(
                    artifact_id=artifact_id,
                    sha256=digest,
                    format_id="finite_displacement_force_table",
                    uri=str(source),
                    source_system="Data_analysis",
                ),),
                analysis_task={"operation_id": "dft.artifact.read", "question": "Synthetic interface test"},
                parameters={"reader_id": "python-csv", "max_records": 10},
                structure_metadata={"units": {"force": "eV/angstrom"}},
                upstream_job_reference="job-ref-synthetic",
            ))

            self.assertEqual(outcome.status, TaskStatus.WARNING)
            self.assertEqual(outcome.analysis_run_id, "RUN-DFT-TEST")
            self.assertEqual(outcome.analysis_run_record["input_artifact_ids"], [artifact_id])
            self.assertEqual(outcome.provenance.input_artifacts[0].artifact_id, artifact_id)
            self.assertEqual(outcome.provenance.upstream_job_reference, "job-ref-synthetic")
            self.assertEqual(outcome.evidence_package["evidence_package_id"], "EV-TEST-DFT")
            self.assertEqual(outcome.evidence_refs[0].source_hashes[artifact_id], digest)
            self.assertEqual(outcome.qc_status, "not_assessed")
            self.assertFalse(outcome.output_artifacts)
            self.assertTrue(any(call[0] == "list_dft_readers" for call in api.calls))
            self.assertTrue(any(call[0] == "list_dft_operations" for call in api.calls))
            self.assertTrue(any(call[0] == "get_dft_operation" for call in api.calls))
            self.assertTrue(any(call[0] == "read_dft_file" for call in api.calls))
            self.assertTrue(any(call[0] == "create_dft_analysis_run_from_project" for call in api.calls))
            self.assertTrue(any(call[0] == "run_dft_operation" for call in api.calls))
            self.assertTrue(any(call[0] == "build_evidence_package" for call in api.calls))

    def test_reader_unavailable_is_returned_as_failure_and_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._fixture(root)
            project = root / "da-project"
            project.mkdir()
            artifact_id = "ART-SYNTHETIC-UNAVAILABLE"
            digest = _sha(source)
            api = FakeDataAnalysisAPI(project, artifact_id, digest)
            api.reader_status = "reader_unavailable"
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(AnalysisRequest(
                task_id="TASK-DA-REAL-2",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef(
                    artifact_id=artifact_id, sha256=digest,
                    format_id="finite_displacement_force_table", uri=str(source)
                ),),
                analysis_task={"operation_id": "dft.artifact.read"},
            ))
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.analysis_run_record["status"], "failed")
            self.assertEqual(outcome.qc_status, "blocked")
            self.assertIn("synthetic unavailable reader", outcome.error)
            self.assertIsNotNone(outcome.evidence_package)

    def test_real_adapter_rejects_missing_artifact_hash_before_reading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._fixture(root)
            project = root / "da-project"
            project.mkdir()
            api = FakeDataAnalysisAPI(project, "ART-NO-SHA", "0" * 64)
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(AnalysisRequest(
                task_id="TASK-DA-NO-SHA",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef("ART-NO-SHA", uri=str(source)),),
                analysis_task={"operation_id": "dft.artifact.read"},
            ))
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.qc["reason_code"], "ARTIFACT_RESOLUTION_FAILED")
            self.assertFalse(any(call[0] == "read_dft_file" for call in api.calls))

    def test_real_adapter_exposes_unsupported_format_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._fixture(root)
            project = root / "da-project"
            project.mkdir()
            artifact_id = "ART-SYNTHETIC-UNSUPPORTED"
            digest = _sha(source)
            api = FakeDataAnalysisAPI(project, artifact_id, digest)
            api.reader_status = "unsupported_format"
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(AnalysisRequest(
                task_id="TASK-DA-UNSUPPORTED",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef(
                    artifact_id=artifact_id, sha256=digest,
                    format_id="unknown_dft_format", uri=str(source)
                ),),
                analysis_task={"operation_id": "dft.artifact.read"},
            ))
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.diagnostics[0].code, "DFT_FORMAT_UNSUPPORTED")

    def test_real_adapter_does_not_resolve_paths_from_a_private_duplicate_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "da-project"
            project.mkdir()
            api = FakeDataAnalysisAPI(project, "ART-NO-URI", "0" * 64)
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(AnalysisRequest(
                task_id="TASK-DA-NO-URI",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef("ART-NO-URI", sha256="0" * 64),),
                analysis_task={"operation_id": "dft.artifact.read"},
            ))
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.qc["reason_code"], "ARTIFACT_RESOLUTION_FAILED")
            self.assertIsNone(outcome.analysis_run_id)


class CSTRealAdapterTests(unittest.TestCase):
    class FakeBuilder:
        def __init__(self, **options):
            self.options = options

        def build_finite_system(self, **arguments):
            self.arguments = arguments
            return "&GLOBAL\\n  RUN_TYPE ENERGY\\n&END GLOBAL\\n"

    def test_real_cst_adapter_calls_the_finite_system_builder(self):
        adapter = RealCSTAdapter(
            builder_cls=self.FakeBuilder,
            workflows=SimpleNamespace(),
            style=SimpleNamespace(),
            chem_scitoolkit_version="synthetic-test-double",
        )
        outcome = adapter.execute(CSTTaskRequest(
            task_id="TASK-CST-BUILDER",
            operation="cp2k.build_finite_system",
            task_config={
                "builder_options": {"project_name": "synthetic"},
                "arguments": {
                    "atoms": [("H", 0.0, 0.0, 0.0)],
                    "cell": {"a": 10, "b": 10, "c": 10},
                    "kind_definitions": {"H": {"element": "H", "basis_set": "BASIS", "potential": "GTH"}},
                },
            },
        ))
        self.assertEqual(outcome.status, TaskStatus.SUCCEEDED)
        self.assertIn("RUN_TYPE ENERGY", outcome.structured_result["input_text"])
        self.assertEqual(outcome.structured_result["result_kind"], "cp2k_input_text")
        self.assertFalse(outcome.structured_result["artifact_registered"])
        self.assertFalse(outcome.output_artifacts)

    def test_cst_output_validator_failure_is_not_reported_as_success(self):
        workflows = SimpleNamespace(
            validate_cp2k_output=lambda **kwargs: {
                "run_type": kwargs["run_type"],
                "status": "failed_or_incomplete",
                "program_normal_termination": False,
                "scf_converged": True,
            }
        )
        adapter = RealCSTAdapter(
            builder_cls=self.FakeBuilder,
            workflows=workflows,
            style=SimpleNamespace(),
            chem_scitoolkit_version="synthetic-test-double",
        )
        outcome = adapter.execute(CSTTaskRequest(
            task_id="TASK-CST-OUTPUT",
            operation="cp2k.validate_output",
            task_config={"arguments": {"log_path": "synthetic.log", "run_type": "GEO_OPT"}},
        ))
        self.assertEqual(outcome.status, TaskStatus.WARNING)
        self.assertEqual(outcome.structured_result["status"], "failed_or_incomplete")
        self.assertEqual(outcome.scientific_validation, "not_evaluated")


class OptionalLiveUpstreamIntegrationTests(unittest.TestCase):
    """Opt-in tests against actual Agent A source branches, never required in public CI."""

    @unittest.skipUnless(
        __import__("os").environ.get("DATA_ANALYSIS_SOURCE_ROOT"),
        "set DATA_ANALYSIS_SOURCE_ROOT to an owner-approved Data_analysis checkout/source tree",
    )
    def test_live_data_analysis_synthetic_force_table_path(self):
        import os
        import sys
        sys.path.insert(0, str(Path(os.environ["DATA_ANALYSIS_SOURCE_ROOT"]) / "src"))
        from data_analysis.register import register_inputs

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "synthetic_forces.tsv"
            source.write_text(
                "displacement_id,atom_index,force_x,force_y,force_z,force_unit\n"
                "fixture-1,0,0.1,0.2,0.3,eV/angstrom\n",
                encoding="utf-8",
            )
            project = root / "da-project"
            manifest = register_inputs(project, source, source_class="synthetic_test")
            artifact_id = manifest["artifact_ids"][0]
            artifact = ArtifactRef(
                artifact_id=artifact_id,
                sha256=_sha(source),
                format_id="finite_displacement_force_table",
                uri=str(source),
                source_system="Data_analysis",
            )
            outcome = RealDataAnalysisAdapter(project).analyze(AnalysisRequest(
                task_id="TASK-LIVE-DA-SYNTHETIC",
                operation="dft.artifact.read",
                input_artifacts=(artifact,),
                analysis_task={"operation_id": "dft.artifact.read"},
                parameters={"reader_id": "python-csv"},
            ))
            self.assertEqual(outcome.status, TaskStatus.WARNING)
            self.assertTrue(outcome.analysis_run_id)
            self.assertTrue(outcome.evidence_package)
            self.assertEqual(outcome.analysis_run_record["input_artifact_ids"], [artifact_id])

    @unittest.skipUnless(
        __import__("os").environ.get("CHEM_SCI_TOOLKIT_SOURCE_ROOT"),
        "set CHEM_SCI_TOOLKIT_SOURCE_ROOT to an owner-approved chem-scitoolkit checkout/source tree",
    )
    def test_live_cst_finite_builder_without_running_cp2k(self):
        import os
        import sys
        sys.path.insert(0, str(Path(os.environ["CHEM_SCI_TOOLKIT_SOURCE_ROOT"])))
        adapter = RealCSTAdapter()
        outcome = adapter.execute(CSTTaskRequest(
            task_id="TASK-LIVE-CST-BUILDER",
            operation="cp2k.build_finite_system",
            task_config={
                "builder_options": {"project_name": "synthetic-interface-test", "run_type": "ENERGY"},
                "arguments": {
                    "atoms": [("H", 0.0, 0.0, 0.0), ("H", 0.7, 0.0, 0.0)],
                    "cell": {"a": 12, "b": 12, "c": 12},
                    "kind_definitions": {
                        "H": {
                            "element": "H", "basis_set": "DZVP-MOLOPT-SR-GTH",
                            "potential": "GTH-PBE", "valence_electrons": 1,
                        }
                    },
                    "multiplicity": 1,
                },
            },
        ))
        self.assertEqual(outcome.status, TaskStatus.SUCCEEDED, outcome.error)
        self.assertIn("PERIODIC NONE", outcome.structured_result["input_text"])
        self.assertIn("&POISSON", outcome.structured_result["input_text"])


if __name__ == "__main__":
    unittest.main()
