from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipeline_contracts.calculation_plan import CalculationPlan, compile_initial_tasks
from pipeline_contracts.models import ArtifactRef, HpcPreflight, TaskStatus
from pipeline_contracts.real_workflow import RealCP2KWorkflowAdapter, build_real_workflow_adapter


class FakeDataAnalysisAPI:
    def __init__(self, paths, events):
        self.paths = paths
        self.events = events
        self.intake_index = 0

    def register_inputs(self, project_root, input_path, *, source_class, received_from=None):
        self.events.append(("register_inputs", source_class, Path(input_path).name))
        self.intake_index += 1
        artifact_id = "ART-STRUCT" if self.intake_index == 1 else f"ART-OUTPUT-{self.intake_index}"
        self.paths[artifact_id] = Path(input_path).resolve()
        return {"artifact_ids": [artifact_id], "failures": []}

    def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
        path = Path(file_path).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.events.append(("register_derived_artifact", tuple(source_artifact_ids), format_id))
        self.paths["ART-CP2K-INPUT"] = path
        return {"artifact_id": "ART-CP2K-INPUT", "sha256": digest}


class FakeDAAdapter:
    execution_mode = "real"

    def __init__(self, project_root, paths, events):
        self.project_root = Path(project_root)
        self.paths = paths
        self.events = events
        self.analysis_request = None

    def resolve_artifact_path(self, artifact):
        self.events.append(("resolve_artifact_path", artifact.artifact_id))
        return self.paths[artifact.artifact_id]

    def analyze(self, request):
        self.analysis_request = request
        self.events.append(("analysis_run", request.upstream_job_reference, tuple(x.artifact_id for x in request.input_artifacts)))
        return SimpleNamespace(
            status=TaskStatus.SUCCEEDED,
            analysis_run_id="ANALYSIS-REAL-001",
            output_artifacts=(ArtifactRef("ART-DERIVED-001", sha256="d" * 64),),
            evidence_package={"evidence_package_id": "EVIDENCE-REAL-001"},
            qc_status="not_assessed",
            warnings=(),
            error=None,
        )


class FakeCSTAdapter:
    def __init__(self, events):
        self.events = events

    def _load_components(self):
        class Builder:
            def build_finite_system(self, **kwargs):
                return "CP2K INPUT"
        return Builder, SimpleNamespace(
            validate_cp2k_input=lambda *args, **kwargs: None,
            validate_cp2k_output=lambda *args, **kwargs: None,
        ), None

    def execute(self, request):
        self.events.append(("cst", request.operation))
        if request.operation == "cp2k.build_finite_system":
            return SimpleNamespace(
                status=TaskStatus.SUCCEEDED,
                structured_result={"input_text": "&GLOBAL\n&END GLOBAL\n&MOTION\n&END MOTION\n"},
                error=None,
            )
        if request.operation == "cp2k.validate_input":
            return SimpleNamespace(
                status=TaskStatus.SUCCEEDED,
                structured_result={"status": "passed"},
                error=None,
            )
        raise AssertionError(f"unexpected CST operation: {request.operation}")


class FakeHPC:
    def preflight(self):
        return HpcPreflight("ucas", True, ("stage_inputs", "submit", "status", "retrieve", "sha256"))

    def _new_remote_workdir(self, task_id):
        return "/remote/project/pipeline-runs/opaque-id"


class FakeCell:
    array = [[18.0, 0.0, 0.0], [0.0, 18.0, 0.0], [0.0, 0.0, 18.0]]

    def lengths(self):
        return [18.0, 18.0, 18.0]

    def angles(self):
        return [90.0, 90.0, 90.0]


class FakeAtoms:
    cell = FakeCell()

    def get_chemical_symbols(self):
        return ["H", "H"]

    def get_positions(self):
        return [[0.0, 0.0, 0.0], [0.7, 0.0, 0.0]]


def _install_fake_ase():
    package = types.ModuleType("ase")
    io_module = types.ModuleType("ase.io")
    io_module.read = lambda path: FakeAtoms()
    package.io = io_module
    return patch.dict(sys.modules, {"ase": package, "ase.io": io_module})


def make_runtime(root, project_root, skill_root):
    ssh = skill_root / "ssh.exe"
    scp = skill_root / "scp.exe"
    record = skill_root / ".agents" / "skills" / "hpc-remote-workflow" / "scripts" / "hpc_job_record.py"
    template = skill_root / ".agents" / "skills" / "hpc-remote-workflow" / "templates" / "slurm" / "cp2k.slurm"
    for path in (ssh, scp, record, template):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
    basis = root / "BASIS_MOLOPT"
    potential = root / "GTH_POTENTIALS"
    basis.write_text("basis fixture", encoding="utf-8")
    potential.write_text("potential fixture", encoding="utf-8")
    return {
        "active_project_root": str(project_root),
        "python_executable": sys.executable,
        "data_analysis": {"project_root": str(project_root), "source_root": ""},
        "chem_scitoolkit": {"source_root": ""},
        "hpc_backends": {
            "ucas": {
                "enabled": True, "alias": "hpc", "ssh_executable": str(ssh),
                "scp_executable": str(scp), "skill_root": str(skill_root),
                "job_record_script": str(record), "slurm_template": str(template),
                "remote_root": "/remote/project", "remote_cp2k_data_dir": "",
                "account": "research",
            }
        },
        "resource_profiles": {
            "ucas-cpu": {"nodes": 1, "ntasks": 4, "cpus_per_task": 1, "mem": "8G",
                         "time": "01:00:00", "partition": "node", "account": "research",
                         "module": "cp2k/2025.2-openmpi"}
        },
        "input_files": {"basis": str(basis), "potential": str(potential)},
    }


class RealWorkflowArtifactLifecycleTests(unittest.TestCase):
    def test_structure_intake_then_derived_cp2k_input_registration_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            da_project = root / "da-project"
            active = root / "active-project"
            skill_root = root / "skills"
            da_project.mkdir()
            active.mkdir()
            structure = root / "input.xyz"
            structure.write_text("2\nfixture\nH 0 0 0\nH 0.7 0 0\n", encoding="utf-8")
            runtime = make_runtime(root, active, skill_root)
            plan = CalculationPlan.load(
                Path(__file__).parents[1] / "examples" / "cp2k_geo_opt_energy_plan.json"
            )
            plan_raw = plan.as_dict()
            plan_raw["project_root"] = str(da_project)
            plan_raw["structure"]["path"] = str(structure)
            plan = CalculationPlan.from_mapping(plan_raw)

            events = []
            paths = {}
            api = FakeDataAnalysisAPI(paths, events)
            da = FakeDAAdapter(da_project, paths, events)
            cst = FakeCSTAdapter(events)
            adapter = RealCP2KWorkflowAdapter(
                plan, da_project, runtime,
                cst_adapter=cst, data_analysis_adapter=da,
                hpc_backend=FakeHPC(), data_analysis_api=api,
            )
            with _install_fake_ase():
                prepared = adapter._prepare_task(compile_initial_tasks(plan)[0], None)

            event_names = [x[0] for x in events]
            self.assertLess(event_names.index("register_inputs"), event_names.index("resolve_artifact_path"))
            self.assertLess(event_names.index("cst"), event_names.index("register_derived_artifact"))
            self.assertLess(event_names.index("register_derived_artifact"), event_names.index("resolve_artifact_path", 2))
            self.assertEqual(events[0][0], "register_inputs")
            derived_event = next(x for x in events if x[0] == "register_derived_artifact")
            self.assertEqual(derived_event[1], ("ART-STRUCT",))
            self.assertEqual(prepared["structure_artifact_id"], "ART-STRUCT")
            self.assertEqual(prepared["cp2k_input_artifact_id"], "ART-CP2K-INPUT")
            self.assertEqual(prepared["cp2k_input_sha256"],
                             hashlib.sha256(Path(paths["ART-CP2K-INPUT"]).read_bytes()).hexdigest())
            self.assertTrue(any(item["name"] == "job.slurm" for item in prepared["local_files"]))
            self.assertIn("&TRAJECTORY", Path(prepared["local_files"][-1]["path"]).read_text(encoding="utf-8"))

    def test_retrieved_cp2k_output_registered_and_resolved_before_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            da_project = root / "da-project"
            da_project.mkdir()
            events = []
            output = root / "cp2k.out"
            output.write_text("PROGRAM ENDED AT\n", encoding="utf-8")
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            paths = {"ART-OUTPUT-2": output}
            api = FakeDataAnalysisAPI(paths, events)
            da = FakeDAAdapter(da_project, paths, events)
            plan = CalculationPlan.load(Path(__file__).parents[1] / "examples" / "cp2k_geo_opt_energy_plan.json")
            adapter = RealCP2KWorkflowAdapter.__new__(RealCP2KWorkflowAdapter)
            adapter.plan = plan
            adapter.da_project_root = da_project
            adapter.register_inputs = api.register_inputs
            adapter.da_api = api
            adapter.da = da
            adapter._prepared = {
                "energy-task": {"structure_artifact_id": "ART-STRUCT", "structure_sha256": "a" * 64}
            }
            ref = ArtifactRef(
                "stage-output", sha256=digest, uri=output.resolve().as_uri(), source_system="HPC:ucas"
            )
            registered = adapter._register_retrieved("cp2k_output", ref, "654321")
            self.assertEqual(registered.artifact_id, "ART-OUTPUT-2")
            event_names = [x[0] for x in events]
            self.assertLess(event_names.index("register_inputs"), event_names.index("resolve_artifact_path"))

            result = adapter.analyze(
                {"task_id": "energy-task", "tool_version": "2025.2", "_upstream_job_reference": "654321"},
                ({"artifact_id": registered.artifact_id, "sha256": registered.sha256, "kind": "cp2k_output"},),
            )
            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.analysis_run_id, "ANALYSIS-REAL-001")
            self.assertEqual(result.evidence_package_id, "EVIDENCE-REAL-001")
            self.assertEqual(da.analysis_request.upstream_job_reference, "654321")
            self.assertEqual(da.analysis_request.input_artifacts[0].artifact_id, "ART-OUTPUT-2")


if __name__ == "__main__":
    unittest.main()
