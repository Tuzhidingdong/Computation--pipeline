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
from pipeline_contracts.models import (
    ArtifactRef, HashVerification, HpcJobRecord, HpcPreflight, HpcStageResult,
    HpcState, HpcStatus, JobReference, TaskStatus,
)
from pipeline_contracts.workflow import WorkflowController, WorkflowStore
from pipeline_contracts.real_workflow import RealCP2KWorkflowAdapter, build_real_workflow_adapter


class FakeDataAnalysisAPI:
    def __init__(self, paths, events):
        self.paths = paths
        self.events = events
        self.intake_index = 0
        self.derived_index = 0

    def register_inputs(self, project_root, input_path, *, source_class, received_from=None):
        self.events.append(("register_inputs", source_class, Path(input_path).name))
        self.intake_index += 1
        artifact_id = "ART-STRUCT" if self.intake_index == 1 else f"ART-OUTPUT-{self.intake_index}"
        self.paths[artifact_id] = Path(input_path).resolve()
        return {"artifact_ids": [artifact_id], "failures": []}

    def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
        path = Path(file_path).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.derived_index += 1
        artifact_id = f"ART-CP2K-INPUT-{self.derived_index}"
        self.events.append(("register_derived_artifact", tuple(source_artifact_ids), format_id))
        self.paths[artifact_id] = path
        return {"artifact_id": artifact_id, "sha256": digest}


class FakeDAAdapter:
    execution_mode = "real"

    def __init__(self, project_root, paths, events):
        self.project_root = Path(project_root)
        self.paths = paths
        self.events = events
        self.analysis_request = None
        self.analysis_requests = []

    def resolve_artifact_path(self, artifact):
        self.events.append(("resolve_artifact_path", artifact.artifact_id))
        return self.paths[artifact.artifact_id]

    def analyze(self, request):
        self.analysis_request = request
        self.analysis_requests.append(request)
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
    def __init__(self, events, *, geo_opt_converged=True):
        self.events = events
        self.geo_opt_converged = geo_opt_converged

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
        if request.operation == "cp2k.validate_output":
            return SimpleNamespace(
                status=TaskStatus.SUCCEEDED,
                structured_result={
                    "status": "passed", "program_normal_termination": True,
                    "scf_converged": True, "geometry_optimization_completed": self.geo_opt_converged,
                    "cp2k_version": "2025.2",
                },
                error=None,
            )
        raise AssertionError(f"unexpected CST operation: {request.operation}")


class FakeHPC:
    def __init__(self, root, *, scheduler_state="COMPLETED", exit_code=0,
                 running_polls=0, missing_roles=(), corrupt_hashes=False):
        self.root = Path(root)
        self.scheduler_state = scheduler_state
        self.exit_code = exit_code
        self.running_polls = running_polls
        self.status_calls = 0
        self.missing_roles = set(missing_roles)
        self.corrupt_hashes = corrupt_hashes
        self.manifests = {}
        self.jobs = {}
        self.submissions = []
        self.updates = []

    def preflight(self):
        return HpcPreflight("ucas", True, ("stage_inputs", "submit", "status", "retrieve", "sha256"))

    def _new_remote_workdir(self, task_id):
        return f"/remote/project/pipeline-runs/opaque-{task_id[-8:]}"

    def attach_task(self, manifest, remote_workdir):
        self.manifests[manifest.task_id] = (manifest, remote_workdir)

    def stage_inputs(self, manifest):
        workdir = str(manifest.payload.get("remote_workdir") or self._new_remote_workdir(manifest.task_id))
        self.attach_task(manifest, workdir)
        return HpcStageResult(manifest.task_id, manifest.input_artifacts, workdir)

    def submit(self, manifest, *, on_submission_intent=None, on_job_submitted=None):
        _, workdir = self.manifests[manifest.task_id]
        job_id = f"FAKE-JOB-{len(self.submissions) + 1}"
        self.submissions.append((manifest.task_id, job_id))
        details = {"remote_workdir": workdir, "input_hashes": {"cp2k.inp": "a" * 64}}
        if on_submission_intent:
            on_submission_intent(details)
        if on_job_submitted:
            on_job_submitted(job_id, details)
        reference = JobReference(job_id, manifest.task_id, "ucas")
        self.jobs[job_id] = (reference, manifest)
        return reference

    def get_status(self, reference):
        self.status_calls += 1
        if self.status_calls <= self.running_polls:
            return HpcStatus(reference, HpcState.RUNNING, "RUNNING")
        mapped = HpcState.AWAITING_VALIDATION if self.scheduler_state == "COMPLETED" else HpcState.FAILED
        return HpcStatus(reference, mapped, self.scheduler_state)

    def get_record(self, reference):
        return HpcJobRecord(reference, self.scheduler_state, "unknown", self.exit_code, "scheduler record")

    def retrieve_selected_outputs(self, reference, output_selection):
        manifest = self.jobs[reference.job_id][1]
        context = self.manifests[reference.task_id][1]
        directory = self.root / "retrieved" / reference.job_id
        directory.mkdir(parents=True, exist_ok=True)
        refs = []
        for role in output_selection:
            if role in self.missing_roles:
                raise FileNotFoundError(f"declared output missing: {role}")
            declared = str(manifest.payload["output_files"][role]).replace("JOB_ID", reference.job_id)
            path = directory / declared
            if role == "cp2k_output":
                path.write_text("CP2K output fixture", encoding="utf-8")
            elif role == "optimized_structure":
                path.write_text("2\\noptimized\\nH 0 0 0\\nH 0.7 0 0\\n", encoding="utf-8")
            else:
                path.write_text("SLURM log fixture", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            refs.append(ArtifactRef(
                artifact_id=f"STAGED-{reference.job_id}-{role}",
                sha256=("0" * 64 if self.corrupt_hashes else digest),
                uri=path.resolve().as_uri(), source_system="HPC:ucas",
            ))
        return tuple(refs)

    def verify_hashes(self, manifest):
        for artifact in manifest:
            path = Path(__import__("urllib.parse", fromlist=["urlparse"]).urlparse(artifact.uri).path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
                return HashVerification(False, (), ("hash mismatch",))
        return HashVerification(True, tuple(item.artifact_id for item in manifest))

    def update_application_record(self, job_id, *, success, marker, result_files=(), stdout_path=None, stderr_path=None):
        self.updates.append((job_id, success, marker, tuple(result_files), stdout_path, stderr_path))


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
    io_module.read = lambda path, index=0: FakeAtoms()
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
    template.write_text(
        "#!/usr/bin/env bash\n"
        "#SBATCH --job-name=cp2k\n#SBATCH --partition=node\n"
        "#SBATCH --account=research\n#SBATCH --nodes=1\n"
        "#SBATCH --ntasks=4\n#SBATCH --cpus-per-task=1\n"
        "#SBATCH --mem=8G\n#SBATCH --time=01:00:00\n"
        "#SBATCH --output=slurm-%j.out\n#SBATCH --error=slurm-%j.err\n"
        "source /etc/profile.d/modules.sh\n"
        "module use /public/env/modules/apps\n"
        "module use /public/env/modules/tools\n"
        "module load cp2k/2025.2-openmpi\n"
        "INPUT=cp2k.inp\nOUTPUT=cp2k.out\n"
        "mpirun -np 4 cp2k.psmp -i $INPUT -o $OUTPUT\n",
        encoding="utf-8",
    )
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
            runtime["active_project_root"] = str(active)
            runtime["data_analysis"]["project_root"] = str(da_project)
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
                hpc_backend=FakeHPC(root), data_analysis_api=api,
            )
            with _install_fake_ase():
                prepared = adapter._prepare_task(compile_initial_tasks(plan)[0], None)

            event_names = [x[0] for x in events]
            self.assertLess(event_names.index("register_inputs"), event_names.index("resolve_artifact_path"))
            self.assertLess(event_names.index("cst"), event_names.index("register_derived_artifact"))
            derived_index = event_names.index("register_derived_artifact")
            input_resolve_index = next(
                i for i, event in enumerate(events)
                if event[0] == "resolve_artifact_path" and event[1] == "ART-CP2K-INPUT-1"
            )
            self.assertLess(derived_index, input_resolve_index)
            self.assertEqual(events[0][0], "register_inputs")
            derived_event = next(x for x in events if x[0] == "register_derived_artifact")
            self.assertEqual(derived_event[1], ("ART-STRUCT",))
            self.assertEqual(prepared["structure_artifact_id"], "ART-STRUCT")
            self.assertEqual(prepared["cp2k_input_artifact_id"], "ART-CP2K-INPUT-1")
            self.assertEqual(prepared["cp2k_input_sha256"],
                             hashlib.sha256(Path(paths["ART-CP2K-INPUT-1"]).read_bytes()).hexdigest())
            self.assertTrue(any(item["name"] == "job.slurm" for item in prepared["local_files"]))
            input_file = next(item for item in prepared["local_files"] if item["name"] == prepared["input_filename"])
            self.assertIn("&TRAJECTORY", Path(input_file["path"]).read_text(encoding="utf-8"))

    def test_fake_real_adapter_completes_geo_opt_energy_with_real_artifact_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            da_project = root / "da-project"
            active = root / "active-project"
            skill_root = root / "skills"
            da_project.mkdir()
            active.mkdir()
            structure = root / "input.xyz"
            structure.write_text("2\\nfixture\\nH 0 0 0\\nH 0.7 0 0\\n", encoding="utf-8")
            runtime = make_runtime(root, active, skill_root)
            runtime["data_analysis"]["project_root"] = str(da_project)
            plan = CalculationPlan.load(Path(__file__).parents[1] / "examples" / "cp2k_geo_opt_energy_plan.json")
            raw = plan.as_dict()
            raw["project_root"] = str(da_project)
            raw["structure"]["path"] = str(structure)
            plan = CalculationPlan.from_mapping(raw)

            events, paths = [], {}
            api = FakeDataAnalysisAPI(paths, events)
            da = FakeDAAdapter(da_project, paths, events)
            cst = FakeCSTAdapter(events)
            hpc = FakeHPC(root)
            adapter = RealCP2KWorkflowAdapter(
                plan, da_project, runtime, cst_adapter=cst, data_analysis_adapter=da,
                hpc_backend=hpc, data_analysis_api=api,
            )
            store = WorkflowStore(root / "workflow.sqlite")
            try:
                controller = WorkflowController(store, adapter)
                run_id = controller.create(plan)
                with _install_fake_ase():
                    final = controller.run(run_id, plan)
                self.assertEqual(final, "COMPLETED", json.dumps(controller.report(run_id)["tasks"], default=str))
                tasks = store.tasks(run_id)
                self.assertEqual([item["operation"] for item in tasks], ["cp2k.geo_opt", "cp2k.energy"])
                self.assertTrue(all(item["status"] == "COMPLETED" for item in tasks))
                self.assertEqual(len(hpc.submissions), 2)
                self.assertEqual(len(da.analysis_requests), 1)
                request = da.analysis_requests[0]
                self.assertEqual(request.upstream_job_reference, "FAKE-JOB-2")
                self.assertEqual(request.input_artifacts[0].artifact_id, "ART-OUTPUT-6")
                self.assertEqual(tasks[1]["status"], "COMPLETED")
                report = controller.report(run_id)
                self.assertEqual(report["execution_mode"], "real")
                self.assertEqual(len([event for event in report["events"] if event["event"] == "DYNAMIC_TASK_ADDED"]), 1)
                self.assertTrue(all(ok for _, ok, *_ in hpc.updates))
            finally:
                store.close()

    def test_real_workflow_resumes_known_job_id_without_second_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); da_project=root/"da"; active=root/"active"; skills=root/"skills"
            da_project.mkdir(); active.mkdir()
            structure=root/"structure.xyz"
            structure.write_text("2\\ninput\\nH 0 0 0\\nH 0.7 0 0\\n",encoding="utf-8")
            runtime=make_runtime(root,active,skills); runtime["data_analysis"]["project_root"]=str(da_project)
            plan=CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            raw=plan.as_dict(); raw["project_root"]=str(da_project); raw["structure"]["path"]=str(structure)
            plan=CalculationPlan.from_mapping(raw)
            events=[]; paths={}; api=FakeDataAnalysisAPI(paths,events); da=FakeDAAdapter(da_project,paths,events)
            hpc=FakeHPC(root,running_polls=1)
            adapter=RealCP2KWorkflowAdapter(plan,da_project,runtime,cst_adapter=FakeCSTAdapter(events),
                data_analysis_adapter=da,hpc_backend=hpc,data_analysis_api=api)
            store=WorkflowStore(root/"workflow.sqlite")
            try:
                ctl=WorkflowController(store,adapter); run_id=ctl.create(plan)
                with _install_fake_ase():
                    self.assertEqual(ctl.run(run_id,plan),"RUNNING")
                    first=store.tasks(run_id)[0]
                    saved_job=first["job_id"]
                    self.assertTrue(saved_job)
                    self.assertEqual(ctl.resume(run_id,plan),"COMPLETED", json.dumps(ctl.report(run_id)["tasks"], default=str))
                self.assertEqual(len(hpc.submissions),2)  # GEO_OPT and ENERGY, one each
                self.assertEqual(hpc.submissions[0][1],saved_job)
                self.assertEqual(hpc.status_calls,3)  # first running; resumed GEO_OPT + ENERGY terminal
                self.assertEqual(store.tasks(run_id)[0]["job_id"],saved_job)
            finally:
                store.close()

    def test_real_scheduler_node_failure_is_not_reported_as_scientific_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); da=root/"da"; active=root/"active"; skills=root/"skills"
            da.mkdir(); active.mkdir()
            structure=root/"input.xyz"; structure.write_text("2\\ninput\\nH 0 0 0\\nH 0.7 0 0\\n",encoding="utf-8")
            runtime=make_runtime(root,active,skills); runtime["data_analysis"]["project_root"]=str(da)
            plan=CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            raw=plan.as_dict(); raw["project_root"]=str(da); raw["structure"]["path"]=str(structure)
            plan=CalculationPlan.from_mapping(raw)
            events=[]; paths={}; api=FakeDataAnalysisAPI(paths,events); hpc=FakeHPC(root,scheduler_state="NODE_FAIL",exit_code=None)
            adapter=RealCP2KWorkflowAdapter(plan,da,runtime,cst_adapter=FakeCSTAdapter(events),
                data_analysis_adapter=FakeDAAdapter(da,paths,events),hpc_backend=hpc,data_analysis_api=api)
            store=WorkflowStore(root/"workflow.sqlite")
            try:
                ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
                with _install_fake_ase():
                    self.assertEqual(ctl.run(rid,plan),"FAILED_INFRASTRUCTURE")
                self.assertEqual(len(hpc.submissions),1)
                self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_INFRASTRUCTURE")
            finally:
                store.close()

    def test_cp2k_nonconverged_geo_opt_does_not_create_energy_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); da=root/"da"; active=root/"active"; skills=root/"skills"
            da.mkdir(); active.mkdir()
            structure=root/"input.xyz"; structure.write_text("2\\ninput\\nH 0 0 0\\nH 0.7 0 0\\n",encoding="utf-8")
            runtime=make_runtime(root,active,skills); runtime["data_analysis"]["project_root"]=str(da)
            plan=CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            raw=plan.as_dict(); raw["project_root"]=str(da); raw["structure"]["path"]=str(structure)
            plan=CalculationPlan.from_mapping(raw)
            events=[]; paths={}; api=FakeDataAnalysisAPI(paths,events); hpc=FakeHPC(root)
            adapter=RealCP2KWorkflowAdapter(plan,da,runtime,cst_adapter=FakeCSTAdapter(events,geo_opt_converged=False),
                data_analysis_adapter=FakeDAAdapter(da,paths,events),hpc_backend=hpc,data_analysis_api=api)
            store=WorkflowStore(root/"workflow.sqlite")
            try:
                ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
                with _install_fake_ase():
                    self.assertEqual(ctl.run(rid,plan),"FAILED")
                self.assertEqual([x["operation"] for x in store.tasks(rid)],["cp2k.geo_opt"])
                self.assertEqual(len(hpc.submissions),1)
            finally:
                store.close()

    def test_missing_retrieved_cp2k_output_is_never_registered_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); da=root/"da"; active=root/"active"; skills=root/"skills"
            da.mkdir(); active.mkdir()
            structure=root/"input.xyz"; structure.write_text("2\\ninput\\nH 0 0 0\\nH 0.7 0 0\\n",encoding="utf-8")
            runtime=make_runtime(root,active,skills); runtime["data_analysis"]["project_root"]=str(da)
            plan=CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            raw=plan.as_dict(); raw["project_root"]=str(da); raw["structure"]["path"]=str(structure)
            plan=CalculationPlan.from_mapping(raw)
            events=[]; paths={}; api=FakeDataAnalysisAPI(paths,events); hpc=FakeHPC(root,missing_roles=("cp2k_output",))
            adapter=RealCP2KWorkflowAdapter(plan,da,runtime,cst_adapter=FakeCSTAdapter(events),
                data_analysis_adapter=FakeDAAdapter(da,paths,events),hpc_backend=hpc,data_analysis_api=api)
            store=WorkflowStore(root/"workflow.sqlite")
            try:
                ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
                with _install_fake_ase():
                    self.assertEqual(ctl.run(rid,plan),"FAILED")
                self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_PERMANENT")
                self.assertFalse(any(x[0]=="register_inputs" and len(x)>2 and x[2]=="cp2k.out" for x in events))
            finally:
                store.close()

    def test_retrieved_output_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); da=root/"da"; active=root/"active"; skills=root/"skills"
            da.mkdir(); active.mkdir()
            structure=root/"input.xyz"; structure.write_text("2\\ninput\\nH 0 0 0\\nH 0.7 0 0\\n",encoding="utf-8")
            runtime=make_runtime(root,active,skills); runtime["data_analysis"]["project_root"]=str(da)
            plan=CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            raw=plan.as_dict(); raw["project_root"]=str(da); raw["structure"]["path"]=str(structure)
            plan=CalculationPlan.from_mapping(raw)
            events=[]; paths={}; api=FakeDataAnalysisAPI(paths,events); hpc=FakeHPC(root,corrupt_hashes=True)
            adapter=RealCP2KWorkflowAdapter(plan,da,runtime,cst_adapter=FakeCSTAdapter(events),
                data_analysis_adapter=FakeDAAdapter(da,paths,events),hpc_backend=hpc,data_analysis_api=api)
            store=WorkflowStore(root/"workflow.sqlite")
            try:
                ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
                with _install_fake_ase():
                    self.assertEqual(ctl.run(rid,plan),"FAILED")
                self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_PERMANENT")
            finally:
                store.close()

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
            api.intake_index = 1
            da = FakeDAAdapter(da_project, paths, events)
            plan = CalculationPlan.load(Path(__file__).parents[1] / "examples" / "cp2k_geo_opt_energy_plan.json")
            adapter = RealCP2KWorkflowAdapter.__new__(RealCP2KWorkflowAdapter)
            adapter.plan = plan
            adapter.da_project_root = da_project
            adapter.backend_id = "ucas"
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
