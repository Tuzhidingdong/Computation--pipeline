import unittest

from pipeline_contracts.integration import run_mock_integration
from pipeline_contracts.models import TaskStatus


class MockIntegrationTests(unittest.TestCase):
    def test_pipeline_cst_to_data_analysis_artifact_and_provenance_handoff(self):
        result = run_mock_integration()
        cst_artifact = result.cst.output_artifacts[0]
        self.assertEqual(result.cst.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.analysis.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.analysis.provenance.input_artifacts[0].artifact_id, cst_artifact.artifact_id)
        self.assertIn(cst_artifact.artifact_id, result.analysis.evidence_refs[0].source_artifact_ids)
        self.assertEqual(result.analysis.provenance.task_id, "mock-analysis-001")
        self.assertFalse(result.cst.structured_result["scientific_values_generated"])
        self.assertEqual(result.analysis.qc_status, "not_evaluated")


if __name__ == "__main__":
    unittest.main()
