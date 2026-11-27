from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from projects.corr_dft_v4_1.model_plugin import ModelSpec, build_candidates, create_approval_record, verify_approval_record
from projects.corr_dft_v4_1.model_plugin.artifacts import register_candidate_structure, register_candidate_package
from projects.corr_dft_v4_1.model_plugin.review import build_review_package


class SimpleWriter:
    def write(self, path, symbols, positions):
        # The test writer is explicitly test-only; production requires ASE.
        path.write_text("test-only structure placeholder", encoding="utf-8")


class ModelPluginTests(unittest.TestCase):
    def _spec(self):
        return ModelSpec.from_mapping({
            "schema_version": "1.0.0", "project_id": "test", "model_id": "test-model",
            "atoms": [
                {"atom_id": "Cu1", "element": "Cu", "position": [0,0,0]},
                {"atom_id": "O1", "element": "O", "position": [2,0,0]},
            ],
            "bonds": [{"atom1":"Cu1","atom2":"O1","kind":"coordination"}],
            "fragments": {"ligand": {"atom_ids": ["O1"]}},
            "expected": {"atom_count": 2, "composition": {"Cu":1,"O":1}, "charge":0,"multiplicity":1,"candidate_count":1},
            "build_constraints": {
                "candidate_transforms": [{
                    "candidate_id":"candidate-001","fragment_id":"ligand",
                    "origin":[0,0,0],"axis":[0,0,1],"angle_degrees":0,"translation":[0,0,0]
                }],
                "donor_atoms": ["O1"], "random_seed": 17
            },
            "evidence": [{"evidence_id":"source-1"}]
        })

    def test_candidate_requires_explicit_graph_and_transform(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = build_candidates(self._spec(), tmp, writer=SimpleWriter())
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0].structure_path.exists())
            self.assertEqual(len(candidates[0].sha256), 64)

    def test_candidate_count_mismatch_fails_closed(self):
        spec = self._spec()
        raw = {
            "schema_version":"1.0.0","project_id":"test","model_id":"test-model",
            "atoms":[dict(x) for x in spec.atoms],"bonds":[dict(x) for x in spec.bonds],
            "fragments":dict(spec.fragments),
            "expected":dict(spec.expected, candidate_count=2),
            "build_constraints":dict(spec.build_constraints),
            "evidence":[dict(x) for x in spec.evidence],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_candidates(ModelSpec.from_mapping(raw), tmp, writer=SimpleWriter())

    def test_candidate_artifact_uses_data_analysis_register_and_resolve(self):
        import hashlib
        class FakeDataAnalysis:
            def __init__(self, path):
                self.path = path
                self.calls = []
            def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
                digest = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
                self.calls.append((source_artifact_ids, format_id, dict(provenance)))
                return {"artifact_id":"da-artifact-1","sha256":digest}
            def resolve_artifact_path(self, project_root, artifact_id):
                self.asserted_id = artifact_id
                return str(self.path)
        with tempfile.TemporaryDirectory() as tmp:
            structure = Path(tmp) / "model.extxyz"
            structure.write_text("model bytes", encoding="utf-8")
            api = FakeDataAnalysis(structure)
            result = register_candidate_structure(
                structure, project_root=tmp, data_analysis_api=api, format_id="extxyz",
                parent_artifact_ids=["source-1"], provenance={"candidate_id":"candidate-1"},
            )
            self.assertEqual(result["artifact_id"], "da-artifact-1")
            self.assertTrue(result["verified"])
            self.assertEqual(api.calls[0][0], ["source-1"])

    def test_review_package_does_not_claim_ready_without_3d_preview(self):
        import json
        candidate = {"candidate_id":"candidate-1","validation_report":{
            "status":"PASS","structure_sha256":"a"*64,"atom_count":2,
            "composition":{"Cu":1,"O":1},"formula":"CuO","charge":0,
            "pseudopotential_electron_count":17,"multiplicity":2}}
        with tempfile.TemporaryDirectory() as tmp:
            package_path = build_review_package([candidate], tmp)
            package = json.loads(package_path.read_text(encoding="utf-8"))
            self.assertEqual(package["review_status"], "BLOCKED_PREVIEW_UNAVAILABLE")
            def renderer(item, path):
                path.write_bytes(b"test-only preview")
            package_path = build_review_package([candidate], tmp + "/rendered", preview_renderer=renderer)
            package = json.loads(package_path.read_text(encoding="utf-8"))
            self.assertEqual(package["review_status"], "AWAITING_USER_REVIEW")

    def test_full_candidate_package_registers_all_required_artifacts(self):
        import hashlib
        class FakeDataAnalysis:
            def __init__(self):
                self.files = {}
                self.calls = []
            def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
                path = Path(file_path)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                artifact_id = "da-" + str(len(self.files) + 1)
                self.files[artifact_id] = path
                self.calls.append((format_id, provenance["artifact_role"]))
                return {"artifact_id":artifact_id,"sha256":digest}
            def resolve_artifact_path(self, project_root, artifact_id):
                return str(self.files[artifact_id])
        with tempfile.TemporaryDirectory() as tmp:
            candidate = build_candidates(self._spec(), tmp, writer=SimpleWriter())[0]
            report = {"status":"PASS","structure_sha256":candidate.sha256}
            api = FakeDataAnalysis()
            result = register_candidate_package(
                candidate, report, project_root=tmp, data_analysis_api=api,
                format_ids={"structure":"extxyz","topology":"json","metadata":"json",
                            "validation_report":"json"}, parent_artifact_ids=[],
            )
            self.assertEqual(set(result["artifacts"]), {
                "structure","topology","metadata","validation_report"
            })
            self.assertEqual(len(api.calls), 4)
            self.assertTrue(all(item["verified"] for item in result["artifacts"].values()))

    def test_missing_3d_position_fails_closed(self):
        raw = {
            "schema_version":"1.0.0","project_id":"x","model_id":"x",
            "atoms":[{"atom_id":"Cu1","element":"Cu"}],"bonds":[],
            "fragments":{},"expected":{},"build_constraints":{},"evidence":[]
        }
        with self.assertRaises(ValueError):
            ModelSpec.from_mapping(raw)

    def test_approval_is_hash_pinned_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            structure = Path(tmp) / "model.xyz"
            structure.write_text("immutable bytes", encoding="utf-8")
            report = {"status":"PASS","structure_sha256":__import__("hashlib").sha256(
                structure.read_bytes()).hexdigest()}
            record_path = Path(tmp) / "approval.json"
            record = create_approval_record(
                record_path, approver="owner", candidate_id="candidate-001",
                artifact_ref={"artifact_id":"artifact-1","sha256":report["structure_sha256"],"source_system":"Data_analysis","verified":True}, structure_path=structure,
                validation_report=report, approved=True,
            )
            self.assertTrue(verify_approval_record(record, structure))
            structure.write_text("changed bytes", encoding="utf-8")
            self.assertFalse(verify_approval_record(record, structure))
            with self.assertRaises(FileExistsError):
                create_approval_record(
                    record_path, approver="owner", candidate_id="candidate-001",
                    artifact_ref={"artifact_id":"artifact-1","sha256":report["structure_sha256"],"source_system":"Data_analysis","verified":True}, structure_path=structure,
                    validation_report=report, approved=True,
                )


if __name__ == "__main__":
    unittest.main()
