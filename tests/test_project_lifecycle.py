from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pipeline_contracts.calculation_plan import CalculationPlan
from pipeline_contracts.workflow import WorkflowStore, WorkflowController, MockCP2KWorkflowAdapter
from pipeline_contracts.project_lifecycle import ProjectLifecycle, PROJECT_STAGES
from projects.corr_dft_v4_1.model_plugin.approval import create_approval_record


class ProjectLifecycleTests(unittest.TestCase):
    def test_approval_freezes_model_then_creates_existing_calculation_dag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = WorkflowStore(root / "workflow.sqlite")
            try:
                lifecycle = ProjectLifecycle(store)
                project_run = lifecycle.create("v41-test", {"schema_version":"1.0.0"})
                for stage in PROJECT_STAGES[:6]:
                    lifecycle.transition(project_run, stage, "COMPLETED")
                lifecycle.transition(project_run, "MODEL_APPROVAL", "AWAITING_APPROVAL")

                structure = root / "approved.extxyz"
                structure.write_text("test structure bytes", encoding="utf-8")
                digest = hashlib.sha256(structure.read_bytes()).hexdigest()
                validation = {"status":"PASS", "structure_sha256":digest}
                record = create_approval_record(
                    root / "approval.json", approver="owner", candidate_id="candidate-1",
                    artifact_ref={"artifact_id":"artifact-1","sha256":digest,"source_system":"Data_analysis","verified":True,"uri":"file:///tmp/artifact"}, structure_path=structure,
                    validation_report=validation, approved=True,
                )
                lifecycle.freeze_approval(project_run, record)

                raw = json.loads((Path(__file__).parents[1] / "examples" /
                                  "cp2k_geo_opt_energy_plan.json").read_text(encoding="utf-8"))
                raw["structure"].pop("path", None)
                raw["structure"]["artifact_id"] = "artifact-1"
                raw["structure"]["sha256"] = digest
                plan = CalculationPlan.from_mapping(raw)
                controller = WorkflowController(store, MockCP2KWorkflowAdapter())
                workflow_run = lifecycle.create_calculation_run(
                    project_run, "candidate-1", structure, plan, controller
                )
                self.assertTrue(workflow_run.startswith("wf-"))
                self.assertEqual(store.run_info(workflow_run)["plan_id"], plan.plan_id)
                self.assertEqual(lifecycle.db.execute(
                    "SELECT status FROM project_lifecycle_runs WHERE project_run_id=?",
                    (project_run,)
                ).fetchone()["status"], "RUNNING")
            finally:
                store.close()

    def test_project_stage_cannot_skip_previous_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "workflow.sqlite")
            try:
                lifecycle = ProjectLifecycle(store)
                run_id = lifecycle.create("test", {})
                with self.assertRaises(RuntimeError):
                    lifecycle.transition(run_id, "MODEL_GENERATE", "RUNNING")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
