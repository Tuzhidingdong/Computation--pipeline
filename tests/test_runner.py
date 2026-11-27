import hashlib
import tempfile
import unittest
from pathlib import Path

from pipeline_contracts.mocks import MockCSTAdapter, MockDataAnalysisAdapter
from pipeline_contracts.models import TaskStatus
from pipeline_contracts.runner import PipelineRunner, PipelineTaskManifest


class PipelineRunnerMockTests(unittest.TestCase):
    def _manifest(self, root: Path, **kwargs):
        values = {
            "task_id": "TASK-MVP-POSTPROCESS",
            "project_root": root,
            "input_artifact_ids": ("ART-CP2K-OUTPUT-001",),
            "operation": "dft.artifact.read",
            "parameters": {"reader_id": "python-csv", "max_records": 100},
            "input_artifact_formats": {
                "ART-CP2K-OUTPUT-001": "finite_displacement_force_table",
            },
            "cst_validation": {
                "operation": "cp2k.validate_output",
                "parameters": {"run_type": "ENERGY"},
            },
            "metadata": {"question": "Post-process existing CP2K output"},
        }
        values.update(kwargs)
        return PipelineTaskManifest(**values)

    def test_complete_mock_e2e_cst_to_analysis_run_artifact_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cst = MockCSTAdapter()
            data_analysis = MockDataAnalysisAdapter()
            runner = PipelineRunner(data_analysis_adapter=data_analysis, cst_adapter=cst)

            result = runner.run(self._manifest(root))

            self.assertEqual(result.status, TaskStatus.SUCCEEDED)
            self.assertEqual(result.execution_mode, "mock")
            self.assertEqual(result.state_history, (
                TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.SUCCEEDED,
            ))
            self.assertEqual([stage.name for stage in result.stages], [
                "cst_validation", "data_analysis",
            ])
            self.assertEqual(result.input_artifacts[0].artifact_id, "ART-CP2K-OUTPUT-001")
            self.assertTrue(result.input_artifacts[0].mock)
            self.assertEqual(cst.last_request.task_id, result.task_id)
            self.assertEqual(cst.last_request.input_artifacts[0].artifact_id, "ART-CP2K-OUTPUT-001")
            self.assertEqual(data_analysis.last_request.task_id, result.task_id)
            self.assertEqual(data_analysis.last_request.input_artifacts[0].artifact_id, "ART-CP2K-OUTPUT-001")

            self.assertEqual(result.analysis_run_id, result.analysis_run_record["analysis_run_id"])
            self.assertEqual(result.analysis_run_record["input_artifact_ids"], ["ART-CP2K-OUTPUT-001"])
            self.assertEqual(len(result.output_artifacts), 1)
            output_id = result.output_artifacts[0].artifact_id
            self.assertEqual(result.analysis_run_record["output_artifact_ids"], [output_id])
            self.assertEqual(result.evidence_package["analysis_run_id"], result.analysis_run_id)
            self.assertEqual(result.evidence_package["output_artifact_ids"], [output_id])
            self.assertIn("ART-CP2K-OUTPUT-001", result.evidence_refs[0].source_artifact_ids)
            self.assertEqual(result.qc_status, "not_evaluated")
            self.assertEqual(result.analysis_outcome.qc_status, "not_evaluated")

    def test_id_only_manifest_is_resolved_and_sha_is_pinned_before_reader(self):
        class ResolverBackedMockAnalysis:
            execution_mode = "real"

            def __init__(self, project_root, source_path):
                self.project_root = project_root
                self.source_path = source_path
                self.received_request = None

            def resolve_artifact_path(self, artifact):
                self.asserted_artifact_id = artifact.artifact_id
                return self.source_path

            def analyze(self, request):
                self.received_request = request
                return MockDataAnalysisAdapter().analyze(request)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "cp2k.out"
            source.write_text("synthetic CP2K output", encoding="utf-8")
            adapter = ResolverBackedMockAnalysis(root, source)
            result = PipelineRunner(data_analysis_adapter=adapter).run(
                self._manifest(root, cst_validation=None)
            )

            expected_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(result.status, TaskStatus.SUCCEEDED)
            self.assertEqual(adapter.asserted_artifact_id, "ART-CP2K-OUTPUT-001")
            self.assertEqual(adapter.received_request.input_artifacts[0].sha256, expected_sha)
            self.assertIsNone(adapter.received_request.input_artifacts[0].uri)

    def test_cst_warning_continues_to_data_analysis_and_aggregates_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            cst = MockCSTAdapter(status=TaskStatus.WARNING)
            data_analysis = MockDataAnalysisAdapter()
            result = PipelineRunner(
                data_analysis_adapter=data_analysis, cst_adapter=cst
            ).run(self._manifest(Path(temp)))

            self.assertEqual(result.status, TaskStatus.WARNING)
            self.assertIsNotNone(result.analysis_run_id)
            self.assertTrue(result.output_artifacts)
            self.assertTrue(result.evidence_package)
            self.assertTrue(any(d.code == "MOCK_CST_WARNING" for d in result.diagnostics))
            self.assertEqual(result.qc_status, "not_evaluated")

    def test_unavailable_official_resolver_is_reported_as_unavailable(self):
        class UnavailableResolver:
            execution_mode = "real"

            def resolve_artifact_path(self, artifact):
                raise RuntimeError("Data_analysis DFT API is unavailable in this runtime")

            def analyze(self, request):
                raise AssertionError("Reader must not run after resolver unavailability")

        with tempfile.TemporaryDirectory() as temp:
            result = PipelineRunner(data_analysis_adapter=UnavailableResolver()).run(
                self._manifest(Path(temp), cst_validation=None)
            )
            self.assertEqual(result.status, TaskStatus.UNAVAILABLE)
            self.assertEqual(result.stages[0].status, TaskStatus.UNAVAILABLE)
            self.assertIn("unavailable", result.error.lower())
            self.assertIsNone(result.analysis_outcome)

    def test_cst_failure_stops_before_data_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter()
            cst = MockCSTAdapter(status=TaskStatus.FAILED)
            result = PipelineRunner(
                data_analysis_adapter=data_analysis, cst_adapter=cst
            ).run(self._manifest(Path(temp)))

            self.assertEqual(result.status, TaskStatus.FAILED)
            self.assertIsNone(result.analysis_outcome)
            self.assertIsNone(data_analysis.last_request)
            self.assertFalse(result.output_artifacts)

    def test_reader_failure_stops_pipeline_without_output_or_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter(
                status=TaskStatus.FAILED,
                failure_code="DFT_PARSE_FAILED",
                failure_message="Synthetic reader parse failure",
            )
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(Path(temp), cst_validation=None)
            )

            self.assertEqual(result.status, TaskStatus.FAILED)
            self.assertEqual(result.stages[-1].name, "data_analysis")
            self.assertEqual(result.analysis_run_id, None)
            self.assertFalse(result.output_artifacts)
            self.assertFalse(result.evidence_refs)
            self.assertIsNone(result.evidence_package)
            self.assertEqual(result.analysis_outcome.diagnostics[0].code, "DFT_PARSE_FAILED")

    def test_artifact_hash_error_is_failure_and_never_returns_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter(
                status=TaskStatus.FAILED,
                failure_code="ARTIFACT_HASH_MISMATCH",
                failure_message="Registered Artifact SHA-256 mismatch",
            )
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(
                    Path(temp),
                    cst_validation=None,
                    input_artifact_hashes={"ART-CP2K-OUTPUT-001": "a" * 64},
                )
            )

            self.assertEqual(result.status, TaskStatus.FAILED)
            self.assertIn("SHA-256 mismatch", result.error)
            self.assertFalse(result.output_artifacts)
            self.assertFalse(result.evidence_refs)

    def test_derived_artifact_registration_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter(
                status=TaskStatus.FAILED,
                failure_code="DERIVED_ARTIFACT_REGISTRATION_FAILED",
                failure_message="Synthetic derived Artifact registration failure",
            )
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(Path(temp), cst_validation=None)
            )

            self.assertEqual(result.status, TaskStatus.FAILED)
            self.assertEqual(result.analysis_outcome.status, TaskStatus.FAILED)
            self.assertFalse(result.output_artifacts)
            self.assertFalse(result.evidence_package)

    def test_missing_requested_cst_adapter_is_unavailable_and_stops_required_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter()
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(Path(temp))
            )

            self.assertEqual(result.status, TaskStatus.UNAVAILABLE)
            self.assertEqual(result.stages[0].status, TaskStatus.UNAVAILABLE)
            self.assertIsNone(result.analysis_outcome)
            self.assertIsNone(data_analysis.last_request)

    def test_missing_data_analysis_adapter_is_unavailable_not_implicit_mock(self):
        with tempfile.TemporaryDirectory() as temp:
            result = PipelineRunner(data_analysis_adapter=None).run(
                self._manifest(Path(temp), cst_validation=None)
            )
            self.assertEqual(result.status, TaskStatus.UNAVAILABLE)
            self.assertEqual(result.stages[0].status, TaskStatus.UNAVAILABLE)
            self.assertIsNone(result.analysis_outcome)

    def test_optional_unavailable_cst_can_continue_with_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter()
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(
                    Path(temp),
                    cst_validation={
                        "operation": "cp2p.validate_output",
                        "required": False,
                    },
                )
            )
            self.assertEqual(result.status, TaskStatus.WARNING)
            self.assertEqual(result.stages[0].status, TaskStatus.WARNING)
            self.assertIsNotNone(result.analysis_run_id)
            self.assertTrue(result.output_artifacts)

    def test_nonterminal_data_analysis_state_is_not_promoted_to_success(self):
        with tempfile.TemporaryDirectory() as temp:
            data_analysis = MockDataAnalysisAdapter(status=TaskStatus.PENDING)
            result = PipelineRunner(data_analysis_adapter=data_analysis).run(
                self._manifest(Path(temp), cst_validation=None)
            )
            self.assertEqual(result.status, TaskStatus.UNAVAILABLE)
            self.assertFalse(result.output_artifacts)


if __name__ == "__main__":
    unittest.main()
