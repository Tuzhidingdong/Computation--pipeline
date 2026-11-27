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
    """API double for the new resolver, derived registration, provenance and evidence boundary."""

    def __init__(self, project_root: Path, expected_artifact_id: str, expected_hash: str, source_path: Path):
        self.project_root = project_root
        self.expected_artifact_id = expected_artifact_id
        self.expected_hash = expected_hash
        self.source_path = source_path
        self.calls = []
        self.fail_resolve = False
        self.fail_derived_registration = False
        self.unserializable_result = False
        self.reader_status = "parsed"
        self.run_path = project_root / "registry" / "analysis_runs" / "RUN-DFT-TEST.json"
        self.run_path.parent.mkdir(parents=True, exist_ok=True)
        self.derived_record_path = project_root / "registry" / "artifacts" / "ART-DERIVED-TEST.json"

    def resolve_artifact_path(self, project_root, artifact_id):
        self.calls.append(("resolve_artifact_path", str(project_root), artifact_id))
        if self.fail_resolve:
            raise FileNotFoundError(f"registered Artifact record not found: {artifact_id}")
        if artifact_id != self.expected_artifact_id:
            raise FileNotFoundError(f"registered Artifact record not found: {artifact_id}")
        root = Path(project_root).resolve()
        resolved = self.source_path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Artifact path escapes Data_analysis project") from exc
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"symlink path component is not allowed: {current}")
        if _sha(resolved) != self.expected_hash:
            raise ValueError(f"registered Artifact SHA-256 mismatch: {artifact_id}")
        return resolved

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
        source_bytes = Path(path).read_bytes()
        data = {"row_count": 1, "result_kind": "synthetic-fixture"}
        if self.unserializable_result:
            data["non_json_value"] = object()
        return {
            "schema_version": "1.0.0",
            "status": self.reader_status,
            "format_id": format_id,
            "reader_id": reader_id or "python-csv",
            "reader_version": "Python standard library",
            "source_path": str(Path(path).resolve()),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "data": data,
            "warnings": [],
            "error": "synthetic unavailable reader" if self.reader_status != "parsed" else None,
        }

    def list_dft_operations(self):
        self.calls.append(("list_dft_operations",))
        return [
            {"operation_id": "dft.artifact.read", "status": "implemented", "operation_version": "1.0.0"},
            {"operation_id": "dft.normalized_result.package", "status": "implemented", "operation_version": "1.0.0"},
        ]

    def get_dft_operation(self, operation_id):
        self.calls.append(("get_dft_operation", operation_id))
        return next((item for item in self.list_dft_operations() if item["operation_id"] == operation_id), None)

    def register_derived_artifact(self, project_root, file_path, **kwargs):
        self.calls.append(("register_derived_artifact", str(file_path), kwargs))
        if self.fail_derived_registration:
            raise RuntimeError("synthetic derived Artifact registration failure")
        path = Path(file_path)
        if not path.is_file() or path.parent != self.project_root / "data" / "derived":
            raise ValueError("derived result must already exist under project data/derived")
        digest = _sha(path)
        artifact_record = {
            "artifact_id": "ART-DERIVED-TEST",
            "sha256": digest,
            "format_id": kwargs["format_id"],
            "relative_path": path.relative_to(self.project_root).as_posix(),
            "parent_artifact_ids": list(kwargs["source_artifact_ids"]),
            "quality_status": kwargs.get("quality_status", "not_assessed"),
        }
        self.derived_record_path.parent.mkdir(parents=True, exist_ok=True)
        self.derived_record_path.write_text(json.dumps(artifact_record), encoding="utf-8")
        return {
            "artifact_id": artifact_record["artifact_id"],
            "sha256": digest,
            "format_id": kwargs["format_id"],
            "source_locator": {
                "stored_relative_path": artifact_record["relative_path"],
                "original_name": path.name,
            },
            "relative_path": artifact_record["relative_path"],
            "stored_relative_path": artifact_record["relative_path"],
            "artifact": artifact_record,
            "record_path": str(self.derived_record_path),
        }

    def create_dft_analysis_run_from_project(self, **kwargs):
        self.calls.append(("create_dft_analysis_run_from_project", kwargs))
        if kwargs["input_artifact_ids"] != [self.expected_artifact_id]:
            raise ValueError("adapter changed the owning input Artifact ID")
        output_ids = [item["artifact_id"] for item in kwargs["output_artifacts"]]
        output_hashes = {item["artifact_id"]: item["sha256"] for item in kwargs["output_artifacts"]}
        record = {
            "schema_version": "1.0.0",
            "analysis_run_id": "RUN-DFT-TEST",
            "operation_id": kwargs["operation_id"],
            "operation_version": kwargs["operation_version"],
            "input_artifact_ids": list(kwargs["input_artifact_ids"]),
            "output_artifact_ids": output_ids,
            "input_hashes": {self.expected_artifact_id: self.expected_hash},
            "output_hashes": output_hashes,
            "parameters": dict(kwargs["parameters"]),
            "software": dict(kwargs["software"]),
            "status": kwargs["status"],
            "warnings": list(kwargs.get("warnings", [])),
            "assumptions": [],
            "dft_provenance": {
                "qc_status": kwargs["qc_status"],
                "units": {},
                "input_artifacts": [{"artifact_id": self.expected_artifact_id, "sha256": self.expected_hash}],
                "output_artifacts": list(kwargs["output_artifacts"]),
            },
        }
        self.run_path.write_text(json.dumps(record), encoding="utf-8")
        return {"analysis_run": record, "record_path": str(self.run_path)}

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
                "output_artifact_ids": kwargs["analysis_run"]["output_artifact_ids"],
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
                "output_artifact_ids": record["output_artifact_ids"],
                "input_hashes": record["input_hashes"],
                "output_hashes": record["output_hashes"],
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

    def _setup(self, root: Path, artifact_id="ART-SYNTHETIC-INPUT"):
        project = root / "da-project"
        project.mkdir()
        received = project / "data" / "received"
        received.mkdir(parents=True)
        source = self._fixture(received)
        digest = _sha(source)
        api = FakeDataAnalysisAPI(project, artifact_id, digest, source)
        request = AnalysisRequest(
            task_id="TASK-DA-REAL-1",
            operation="dft.artifact.read",
            input_artifacts=(ArtifactRef(
                artifact_id=artifact_id,
                sha256=digest,
                format_id="finite_displacement_force_table",
                source_system="Data_analysis",
            ),),
            analysis_task={"operation_id": "dft.artifact.read", "question": "Synthetic interface test"},
            parameters={"reader_id": "python-csv", "max_records": 10},
            structure_metadata={"units": {"force": "eV/angstrom"}},
            upstream_job_reference="job-ref-synthetic",
        )
        return source, project, api, request

    def test_resolver_registration_analysis_run_and_evidence_form_complete_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.SUCCEEDED, outcome.error)
            self.assertEqual(outcome.analysis_run_id, "RUN-DFT-TEST")
            self.assertEqual(outcome.qc_status, "not_assessed")
            self.assertEqual(outcome.qc["scientific_qc"], "not_assessed")
            self.assertEqual(len(outcome.output_artifacts), 1)
            derived_ref = outcome.output_artifacts[0]
            self.assertEqual(derived_ref.artifact_id, "ART-DERIVED-TEST")
            self.assertEqual(derived_ref.sha256, outcome.analysis_run_record["output_hashes"]["ART-DERIVED-TEST"])
            self.assertEqual(outcome.analysis_run_record["output_artifact_ids"], ["ART-DERIVED-TEST"])
            self.assertEqual(outcome.provenance.output_artifacts[0].artifact_id, "ART-DERIVED-TEST")

            derived_file = Path(outcome.result["derived_file_path"])
            self.assertTrue(derived_file.is_file())
            self.assertEqual(derived_file.parent, project / "data" / "derived")
            persisted = json.loads(derived_file.read_text(encoding="utf-8"))
            self.assertEqual(persisted["source_artifact_ids"], ["ART-SYNTHETIC-INPUT"])
            self.assertEqual(persisted["reader_results"][0]["status"], "parsed")
            self.assertEqual(_sha(derived_file), derived_ref.sha256)

            evidence = outcome.evidence_package
            self.assertEqual(evidence["dft_reports"][0]["analysis_run_id"], outcome.analysis_run_id)
            self.assertEqual(evidence["dft_reports"][0]["output_artifact_ids"], ["ART-DERIVED-TEST"])
            self.assertEqual(outcome.evidence_refs[0].source_artifact_ids, (
                "ART-SYNTHETIC-INPUT", "ART-DERIVED-TEST"
            ))
            self.assertEqual(
                outcome.evidence_refs[0].source_hashes["ART-DERIVED-TEST"],
                derived_ref.sha256,
            )

            call_names = [call[0] for call in api.calls]
            self.assertLess(call_names.index("resolve_artifact_path"), call_names.index("read_dft_file"))
            self.assertLess(call_names.index("read_dft_file"), call_names.index("register_derived_artifact"))
            self.assertLess(call_names.index("register_derived_artifact"), call_names.index("create_dft_analysis_run_from_project"))
            self.assertLess(call_names.index("create_dft_analysis_run_from_project"), call_names.index("run_dft_operation"))
            self.assertLess(call_names.index("run_dft_operation"), call_names.index("build_evidence_package"))

    def test_public_resolver_accepts_artifact_id_without_caller_sha_or_uri(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, _ = self._setup(root)
            adapter = RealDataAnalysisAdapter(project, api=api)

            resolved = adapter.resolve_artifact_path(ArtifactRef(
                artifact_id="ART-SYNTHETIC-INPUT",
                format_id="finite_displacement_force_table",
                source_system="Data_analysis",
            ))

            self.assertEqual(resolved, source.resolve())
            self.assertTrue(any(call[0] == "resolve_artifact_path" for call in api.calls))

    def test_validated_only_reader_result_is_registered_as_partial_parse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.reader_status = "validated"
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.SUCCEEDED, outcome.error)
            self.assertEqual(outcome.output_artifacts[0].artifact_id, "ART-DERIVED-TEST")
            registration = next(call for call in api.calls if call[0] == "register_derived_artifact")
            self.assertEqual(registration[2]["parse_status"], "partial")
            self.assertEqual(registration[2]["quality_status"], "not_assessed")
            self.assertEqual(outcome.qc_status, "not_assessed")

    def test_official_resolver_rejects_registered_input_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.expected_hash = "f" * 64
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.diagnostics[0].code, "DA_ARTIFACT_PROVENANCE_REJECTED")
            self.assertIn("SHA-256 mismatch", outcome.error)
            self.assertFalse(any(call[0] == "read_dft_file" for call in api.calls))
            self.assertFalse(any(call[0] == "register_derived_artifact" for call in api.calls))

    def test_reader_reported_hash_mismatch_is_failed_and_never_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            wrong_hash = "e" * 64
            request = AnalysisRequest(
                task_id="TASK-DA-HASH-MISMATCH",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef(
                    artifact_id="ART-SYNTHETIC-INPUT",
                    sha256=wrong_hash,
                    format_id="finite_displacement_force_table",
                ),),
                analysis_task={"operation_id": "dft.artifact.read"},
            )
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.diagnostics[0].code, "DA_ARTIFACT_PROVENANCE_REJECTED")
            self.assertIn("does not match ArtifactRef", outcome.error)
            self.assertIsNone(outcome.analysis_run_id)
            self.assertFalse(outcome.output_artifacts)
            self.assertFalse(any(call[0] == "register_derived_artifact" for call in api.calls))

    def test_missing_sha_is_rejected_before_resolver_or_reader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            request = AnalysisRequest(
                task_id="TASK-DA-NO-SHA",
                operation="dft.artifact.read",
                input_artifacts=(ArtifactRef("ART-SYNTHETIC-INPUT"),),
                analysis_task={"operation_id": "dft.artifact.read"},
            )
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.qc["reason_code"], "ARTIFACT_RESOLUTION_FAILED")
            self.assertFalse(any(call[0] == "resolve_artifact_path" for call in api.calls))
            self.assertFalse(any(call[0] == "read_dft_file" for call in api.calls))

    def test_missing_registered_artifact_is_a_specific_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root, "ART-NOT-REGISTERED")
            api.fail_resolve = True
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.diagnostics[0].code, "DA_ARTIFACT_NOT_REGISTERED_OR_SOURCE_MISSING")
            self.assertIn("registered Artifact record not found", outcome.error)
            self.assertFalse(any(call[0] == "read_dft_file" for call in api.calls))

    def test_reader_unavailable_is_returned_as_failed_analysis_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.reader_status = "reader_unavailable"
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.analysis_run_record["status"], "failed")
            self.assertFalse(outcome.analysis_run_record["output_artifact_ids"])
            self.assertEqual(outcome.qc_status, "blocked")
            self.assertIn("synthetic unavailable reader", outcome.error)
            self.assertIsNotNone(outcome.evidence_package)
            self.assertFalse(outcome.output_artifacts)

    def test_unsupported_format_is_preserved_as_failed_reader_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.reader_status = "unsupported_format"
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)
            self.assertEqual(outcome.status, TaskStatus.FAILED)
            self.assertEqual(outcome.diagnostics[0].code, "DFT_FORMAT_UNSUPPORTED")
            self.assertEqual(outcome.analysis_run_record["status"], "failed")

    def test_json_serialization_failure_keeps_in_memory_result_without_fake_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.unserializable_result = True
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.WARNING)
            self.assertIsNone(outcome.error)
            self.assertEqual(outcome.qc_status, "not_assessed")
            self.assertIn("not JSON serializable", outcome.qc["persistence_error"])
            self.assertIsNone(outcome.result["derived_file_path"])
            self.assertFalse(outcome.output_artifacts)
            self.assertEqual(outcome.analysis_run_record["status"], "failed")
            self.assertFalse(outcome.analysis_run_record["output_artifact_ids"])
            self.assertTrue(outcome.result["reader_results"][0]["data"]["non_json_value"])
            self.assertFalse(any(call[0] == "register_derived_artifact" for call in api.calls))

    def test_registration_failure_keeps_written_file_but_no_fake_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, project, api, request = self._setup(root)
            api.fail_derived_registration = True
            outcome = RealDataAnalysisAdapter(project, api=api).analyze(request)

            self.assertEqual(outcome.status, TaskStatus.WARNING)
            self.assertIsNone(outcome.error)
            self.assertEqual(outcome.qc_status, "not_assessed")
            self.assertIn("synthetic derived Artifact registration failure", outcome.qc["persistence_error"])
            persisted_file = Path(outcome.result["derived_file_path"])
            self.assertTrue(persisted_file.is_file())
            self.assertEqual(persisted_file.parent, project / "data" / "derived")
            self.assertFalse(outcome.output_artifacts)
            self.assertFalse(outcome.analysis_run_record["output_artifact_ids"])
            self.assertEqual(outcome.analysis_run_record["status"], "failed")


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
            self.assertEqual(outcome.status, TaskStatus.SUCCEEDED, outcome.error)
            self.assertTrue(outcome.analysis_run_id)
            self.assertTrue(outcome.evidence_package)
            self.assertEqual(outcome.analysis_run_record["input_artifact_ids"], [artifact_id])
            self.assertEqual(len(outcome.output_artifacts), 1)
            self.assertEqual(outcome.analysis_run_record["output_artifact_ids"], [outcome.output_artifacts[0].artifact_id])

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
