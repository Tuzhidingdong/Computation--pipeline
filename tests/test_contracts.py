import unittest

from pipeline_contracts.adapters import CSTAdapter, DataAnalysisAdapter, HpcAdapter
from pipeline_contracts.mocks import MockCSTAdapter, MockDataAnalysisAdapter, MockHpcAdapter
from pipeline_contracts.models import (
    AnalysisRequest, ArtifactRef, CSTTaskRequest, ContractError,
    HpcState, HpcTaskManifest, TaskStatus,
)


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.source = ArtifactRef("ART-INPUT-1", uri="mock://fixtures/input", mock=True)

    def test_cst_request_is_passed_without_losing_task_or_artifact_ids(self):
        adapter = MockCSTAdapter()
        request = CSTTaskRequest("TASK-1", "mock.prepare", {"run_type": "ENERGY"}, (self.source,), {"cutoff": 1}, "mock-job-1")
        outcome = adapter.execute(request)
        self.assertIs(adapter.last_request, request)
        self.assertEqual(outcome.task_id, "TASK-1")
        self.assertEqual(outcome.provenance.input_artifacts[0].artifact_id, "ART-INPUT-1")
        self.assertEqual(outcome.provenance.upstream_job_reference, "mock-job-1")
        self.assertTrue(outcome.output_artifacts[0].artifact_id.startswith("mock-cst-"))
        self.assertEqual(outcome.scientific_validation, "not_evaluated")
        self.assertFalse(outcome.structured_result["scientific_values_generated"])

    def test_data_analysis_preserves_input_refs_analysis_run_and_evidence(self):
        adapter = MockDataAnalysisAdapter()
        artifact = ArtifactRef("ART-CST-OUTPUT", sha256="a" * 64, mock=True, uri="mock://cst/out")
        request = AnalysisRequest("AN-1", "mock.normalize", (artifact,), {"action": "register"}, {"window": 2}, {"formula": "synthetic"}, "mock-job-analysis")
        outcome = adapter.analyze(request)
        self.assertIs(adapter.last_request, request)
        self.assertEqual(outcome.analysis_run_id, "mock-analysis-run-AN-1")
        self.assertEqual(outcome.provenance.input_artifacts[0].artifact_id, "ART-CST-OUTPUT")
        self.assertEqual(outcome.evidence_refs[0].source_artifact_ids, ("ART-CST-OUTPUT",))
        self.assertEqual(outcome.evidence_refs[0].source_hashes["ART-CST-OUTPUT"], "a" * 64)
        self.assertEqual(outcome.qc_status, "not_evaluated")
        self.assertFalse(outcome.qc["scientific_validation"])
        self.assertEqual(outcome.provenance.upstream_job_reference, "mock-job-analysis")

    def test_warning_and_failure_states_are_visible(self):
        warning = MockCSTAdapter(TaskStatus.WARNING).execute(
            CSTTaskRequest("TASK-WARN", "mock.op", {"x": 1}, (self.source,))
        )
        failed = MockDataAnalysisAdapter(TaskStatus.FAILED).analyze(
            AnalysisRequest("AN-FAIL", "mock.op", (self.source,), {"x": 1})
        )
        self.assertEqual(warning.status, TaskStatus.WARNING)
        self.assertTrue(any(item.severity.value == "warning" for item in warning.diagnostics))
        self.assertEqual(failed.status, TaskStatus.FAILED)
        self.assertIn("Synthetic", failed.error)

    def test_incomplete_and_invalid_inputs_are_rejected(self):
        with self.assertRaises(ContractError):
            CSTTaskRequest("TASK-EMPTY", "mock.op")
        with self.assertRaises(ContractError):
            AnalysisRequest("AN-EMPTY", "mock.op", (), {"action": "parse"})
        with self.assertRaises(ContractError):
            ArtifactRef("ART-BAD-HASH", sha256="not-a-hash")
        with self.assertRaises(ContractError):
            MockCSTAdapter("not-a-status")

    def test_mock_adapters_implement_pipeline_protocols(self):
        self.assertTrue(callable(getattr(MockCSTAdapter(), "execute", None)))
        self.assertTrue(callable(getattr(MockDataAnalysisAdapter(), "analyze", None)))
        expected_hpc = ("preflight", "stage_inputs", "submit", "get_status", "get_record", "retrieve_selected_outputs", "verify_hashes")
        self.assertTrue(all(callable(getattr(MockHpcAdapter(), name, None)) for name in expected_hpc))
        self.assertTrue(callable(getattr(CSTAdapter, "execute", None)))
        self.assertTrue(callable(getattr(DataAnalysisAdapter, "analyze", None)))
        self.assertTrue(all(callable(getattr(HpcAdapter, name, None)) for name in expected_hpc))

    def _hpc_manifest(self):
        expected = ArtifactRef("ART-HPC-OUTPUT", uri="mock://hpc/output", mock=True)
        return HpcTaskManifest("HPC-TASK-1", (self.source,), {"resource_profile": "synthetic"}, (expected,))

    def test_scheduler_completion_is_not_reported_as_success(self):
        adapter = MockHpcAdapter()
        manifest = self._hpc_manifest()
        self.assertTrue(adapter.preflight().ready)
        adapter.stage_inputs(manifest)
        job = adapter.submit(manifest)
        self.assertEqual(adapter.get_status(job).state, HpcState.SUBMITTED)
        self.assertEqual(adapter.get_status(job).state, HpcState.QUEUED)
        self.assertEqual(adapter.get_status(job).state, HpcState.RUNNING)
        awaiting = adapter.get_status(job)
        self.assertEqual(awaiting.scheduler_state, "COMPLETED")
        self.assertEqual(awaiting.state, HpcState.AWAITING_VALIDATION)
        self.assertNotEqual(awaiting.state, HpcState.SUCCEEDED)
        record = adapter.get_record(job)
        outputs = adapter.retrieve_selected_outputs(job, ["ART-HPC-OUTPUT"])
        self.assertEqual(record.application_state, "succeeded")
        checked = adapter.verify_hashes(outputs)
        self.assertTrue(checked.verified)
        final = adapter.get_status(job)
        self.assertEqual(final.state, HpcState.SUCCEEDED)
        self.assertEqual(checked.verification_mode, "mock_scenario_no_bytes_hashed")

    def test_hpc_hash_failure_blocks_success(self):
        adapter = MockHpcAdapter(hashes_valid=False)
        manifest = self._hpc_manifest()
        adapter.stage_inputs(manifest)
        job = adapter.submit(manifest)
        for _ in range(4):
            adapter.get_status(job)
        adapter.get_record(job)
        outputs = adapter.retrieve_selected_outputs(job, ["ART-HPC-OUTPUT"])
        checked = adapter.verify_hashes(outputs)
        self.assertFalse(checked.verified)
        self.assertEqual(adapter.get_status(job).state, HpcState.FAILED)

    def test_hpc_application_failure_is_not_hidden_by_scheduler_completion(self):
        adapter = MockHpcAdapter(application_state="failed")
        manifest = self._hpc_manifest()
        adapter.stage_inputs(manifest)
        job = adapter.submit(manifest)
        for _ in range(4):
            adapter.get_status(job)
        record = adapter.get_record(job)
        self.assertEqual(record.scheduler_state, "COMPLETED")
        self.assertEqual(record.application_state, "failed")
        self.assertEqual(adapter.get_status(job).state, HpcState.FAILED)

    def test_hpc_rejects_missing_stage_and_unknown_output(self):
        adapter = MockHpcAdapter()
        manifest = self._hpc_manifest()
        with self.assertRaises(ContractError):
            adapter.submit(manifest)
        adapter.stage_inputs(manifest)
        job = adapter.submit(manifest)
        for _ in range(4):
            adapter.get_status(job)
        with self.assertRaises(ContractError):
            adapter.retrieve_selected_outputs(job, ["ART-NOT-DECLARED"])


if __name__ == "__main__":
    unittest.main()
