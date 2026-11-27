from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path

from pipeline_contracts.workflow import WorkflowStore
from pipeline_contracts.project_lifecycle import ProjectLifecycle, PROJECT_STAGES
from projects.corr_dft_v4_1.model_plugin.pipeline import generate_validate_review, approve_candidate


class TestWriter:
    def write(self, path, symbols, positions):
        path.write_text("test-only model bytes", encoding="utf-8")


class FakeDataAnalysis:
    def __init__(self):
        self.files = {}
    def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
        path = Path(file_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact_id = "artifact-" + str(len(self.files) + 1)
        self.files[artifact_id] = path
        return {"artifact_id":artifact_id,"sha256":digest}
    def resolve_artifact_path(self, project_root, artifact_id):
        return str(self.files[artifact_id])


class ModelPipelineTests(unittest.TestCase):
    def test_generation_validation_review_and_approval_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = WorkflowStore(root / "workflow.sqlite")
            try:
                lifecycle = ProjectLifecycle(store)
                run_id = lifecycle.create("v41-test", {})
                for stage in PROJECT_STAGES[:2]:
                    lifecycle.transition(run_id, stage, "COMPLETED")
                spec = {
                    "schema_version":"1.0.0","project_id":"v41-test","model_id":"test-model",
                    "atoms":[
                        {"atom_id":"Cu1","element":"Cu","position":[0,0,0]},
                        {"atom_id":"O1","element":"O","position":[2,0,0]},
                    ],
                    "bonds":[{"atom1":"Cu1","atom2":"O1","kind":"coordination"}],
                    "fragments":{"ligand":{"atom_ids":["O1"]}},
                    "expected":{"atom_count":2,"composition":{"Cu":1,"O":1},
                                "charge":0,"multiplicity":1,"candidate_count":1},
                    "build_constraints":{"random_seed":17,"candidate_transforms":[{
                        "candidate_id":"candidate-1","fragment_id":"ligand",
                        "origin":[0,0,0],"axis":[0,0,1],"angle_degrees":0,
                        "translation":[0,0,0]}],"donor_atoms":["O1"]},
                    "evidence":[{"evidence_id":"source-1"}],
                }
                def validator(path, topology, expected, *, pseudopotential_valence):
                    return {"status":"PASS","structure_sha256":hashlib.sha256(
                        Path(path).read_bytes()).hexdigest(),"atom_count":2,
                        "composition":{"Cu":1,"O":1},"formula":"CuO","charge":0,
                        "pseudopotential_electron_count":17,"multiplicity":1}
                def renderer(item, path):
                    path.write_bytes(b"test-only preview")
                result = generate_validate_review(
                    [spec], root / "models", lifecycle=lifecycle, project_run_id=run_id,
                    data_analysis_api=FakeDataAnalysis(),
                    format_ids={"structure":"extxyz","topology":"json","metadata":"json",
                                "validation_report":"json"},
                    parent_artifact_ids=[], pseudopotential_valence_by_model={
                        "test-model":{"Cu":11,"O":6}},
                    structure_writer=TestWriter(), validator=validator,
                    preview_renderer=renderer,
                )
                self.assertEqual(result["status"], "AWAITING_APPROVAL")
                record = approve_candidate(
                    result, "candidate-1", approver="owner",
                    approval_record_path=root / "approval.json", lifecycle=lifecycle,
                    project_run_id=run_id, approved=True,
                )
                self.assertEqual(record["approval_status"], "APPROVED")
                self.assertEqual(lifecycle.approval(run_id, "candidate-1")["artifact_id"],
                                 record["artifact_id"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
