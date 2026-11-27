from __future__ import annotations
import json, tempfile, unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from pipeline_contracts.calculation_plan import CalculationPlan, compile_initial_tasks
from pipeline_contracts.workflow import ExecutionResult, MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore
from pipeline_contracts.cli import main as cli_main

def example_plan():
    return CalculationPlan.load(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")

class WorkflowTests(unittest.TestCase):
    def setup_run(self,*,converged=True,interrupt=False):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        store=WorkflowStore(Path(temp.name)/"state.sqlite"); self.addCleanup(store.close)
        adapter=MockCP2KWorkflowAdapter(geo_opt_converged=converged,interrupt_once=interrupt)
        plan=example_plan(); ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
        return ctl,store,adapter,plan,rid
    def test_plan_compiles_only_initial_geo_opt(self):
        tasks=compile_initial_tasks(example_plan())
        self.assertEqual(len(tasks),1); self.assertEqual(tasks[0]["operation"],"cp2k.geo_opt")
    def test_missing_scientific_parameter_is_not_guessed(self):
        raw=example_plan().as_dict(); raw["method"].pop("xc")
        self.assertTrue(any("xc" in x for x in CalculationPlan.from_mapping(raw).validate()))
    def test_geo_opt_success_dynamically_adds_energy_then_analysis(self):
        ctl,store,adapter,plan,rid=self.setup_run()
        self.assertEqual(ctl.run(rid,plan),"COMPLETED")
        tasks=store.tasks(rid); self.assertEqual([x["operation"] for x in tasks],["cp2k.geo_opt","cp2k.energy"])
        energy=json.loads(tasks[1]["task_json"]); self.assertEqual(energy["dependencies"],[tasks[0]["task_id"]])
        result=json.loads(tasks[1]["result_json"])
        self.assertTrue(result["analysis_run_id"]); self.assertTrue(result["evidence_package_id"])
        events=[x["event"] for x in store.events(rid)]
        self.assertIn("QUEUED",events); self.assertIn("RUNNING",events)
    def test_geo_opt_nonconvergence_does_not_create_energy(self):
        ctl,store,adapter,plan,rid=self.setup_run(converged=False)
        self.assertEqual(ctl.run(rid,plan),"FAILED")
        self.assertEqual(len(store.tasks(rid)),1)
        self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_PERMANENT")
    def test_network_loss_persists_job_and_resume_does_not_resubmit_geo_opt(self):
        ctl,store,adapter,plan,rid=self.setup_run(interrupt=True)
        self.assertEqual(ctl.run(rid,plan),"INTERRUPTED_RECOVERY")
        first=store.tasks(rid)[0]; self.assertEqual(first["status"],"INTERRUPTED_RECOVERY")
        saved_job=first["job_id"]; self.assertTrue(saved_job)
        self.assertEqual(ctl.resume(rid,plan),"COMPLETED")
        self.assertEqual(adapter.submissions[first["task_id"]],saved_job)
        self.assertEqual(len(adapter.submissions),2)
    def test_missing_real_adapter_is_not_silently_mocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp)/"s.sqlite"); self.addCleanup(store.close)
            ctl=WorkflowController(store,None); plan=example_plan(); rid=ctl.create(plan)
            self.assertEqual(ctl.run(rid,plan),"UNAVAILABLE")
            self.assertEqual(store.run_info(rid)["execution_mode"],"real")
    def test_scheduler_completed_with_nonzero_application_exit_is_failure(self):
        class BadApplication(MockCP2KWorkflowAdapter):
            def execute(self, task, existing_job_id=None):
                result=super().execute(task,existing_job_id)
                from dataclasses import replace
                return replace(result,application_exit_code=17)
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp)/"s.sqlite"); self.addCleanup(store.close)
            plan=example_plan(); ctl=WorkflowController(store,BadApplication()); rid=ctl.create(plan)
            self.assertEqual(ctl.run(rid,plan),"FAILED")
            self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_PERMANENT")

    def test_cli_plan_validate_run_status_resume_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_file=str(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            state_db=str(Path(tmp)/"cli.sqlite")
            for command in (["plan",plan_file],["validate",plan_file]):
                with redirect_stdout(StringIO()): self.assertEqual(cli_main(command),0)
            output=StringIO()
            with redirect_stdout(output): self.assertEqual(cli_main(["run",plan_file,"--mock","--state-db",state_db]),0)
            run_id=json.loads(output.getvalue())["workflow_run_id"]
            for command in (["status",run_id,"--state-db",state_db],["resume",run_id,"--state-db",state_db,"--mock"],["report",run_id,"--state-db",state_db]):
                with redirect_stdout(StringIO()): self.assertEqual(cli_main(command),0)

    def test_run_lock_prevents_two_controllers_from_running_same_workflow(self):
        ctl,store,adapter,plan,rid=self.setup_run()
        lock=store.acquire_run_lock(rid)
        self.assertTrue(lock)
        try:
            self.assertEqual(ctl.run(rid,plan),"LOCKED")
            self.assertEqual(adapter.submissions,{})
        finally:
            store.release_run_lock(rid,lock)
        self.assertEqual(ctl.run(rid,plan),"COMPLETED")

    def test_failed_permanent_task_is_not_retried_by_ordinary_resume(self):
        class FailOnce:
            execution_mode="real"
            def __init__(self): self.calls=0
            def preflight(self,task): return {"ready":True}
            def execute(self,task,existing_job_id=None,**kwargs):
                self.calls+=1
                return ExecutionResult("FAILED_PERMANENT",job_id="777",scheduler_state="FAILED",
                                       application_exit_code=1,diagnostics=("app failed",),execution_mode="real")
            def analyze(self,task,artifacts): raise AssertionError("analysis not reached")
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp)/"s.sqlite"); self.addCleanup(store.close)
            plan=example_plan(); adapter=FailOnce(); ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
            self.assertEqual(ctl.run(rid,plan),"FAILED")
            self.assertEqual(ctl.resume(rid,plan),"FAILED")
            self.assertEqual(adapter.calls,1)

    def test_infrastructure_failure_is_distinct_and_not_retried_by_resume(self):
        class InfraFail:
            execution_mode="real"
            def __init__(self): self.calls=0
            def preflight(self,task): return {"ready":True}
            def execute(self,task,existing_job_id=None,**kwargs):
                self.calls+=1
                return ExecutionResult(
                    "FAILED_INFRASTRUCTURE", job_id="NODE-FAIL-1",
                    scheduler_state="NODE_FAIL",
                    diagnostics=("compute node failed",), execution_mode="real",
                )
            def analyze(self,task,artifacts): raise AssertionError("analysis not reached")
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp)/"s.sqlite"); self.addCleanup(store.close)
            plan=example_plan(); adapter=InfraFail(); ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
            self.assertEqual(ctl.run(rid,plan),"FAILED_INFRASTRUCTURE")
            self.assertEqual(ctl.resume(rid,plan),"FAILED_INFRASTRUCTURE")
            self.assertEqual(adapter.calls,1)
            self.assertEqual(store.tasks(rid)[0]["status"],"FAILED_INFRASTRUCTURE")

    def test_submission_intent_and_job_id_are_durable_before_polling(self):
        class RunningAdapter:
            execution_mode="real"
            def __init__(self): self.existing=[]; self.submits=0
            def preflight(self,task): return {"ready":True}
            def execute(self,task,existing_job_id=None,*,runtime_state=None,on_submission_intent=None,on_job_submitted=None):
                self.existing.append(existing_job_id)
                if existing_job_id is None:
                    self.submits+=1
                    details={"remote_workdir":"/opaque/runs/abc123","submission_time":"2026-11-27T00:00:00Z",
                             "input_hashes":{"cp2k.inp":"a"*64}}
                    on_submission_intent(details)
                    on_job_submitted("98765",details)
                return ExecutionResult("RUNNING",job_id=existing_job_id or "98765",
                    scheduler_state="RUNNING",state_trace=("SUBMITTED","QUEUED","RUNNING"),
                    execution_mode="real",runtime={"remote_workdir":"/opaque/runs/abc123"})
            def analyze(self,task,artifacts): raise AssertionError("analysis not reached")
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp)/"s.sqlite"); self.addCleanup(store.close)
            plan=example_plan(); adapter=RunningAdapter(); ctl=WorkflowController(store,adapter); rid=ctl.create(plan)
            self.assertEqual(ctl.run(rid,plan),"RUNNING")
            first=store.tasks(rid)[0]; runtime=json.loads(first["result_json"])
            self.assertEqual(first["job_id"],"98765")
            self.assertTrue(runtime["submission_intent"])
            self.assertEqual(runtime["remote_workdir"],"/opaque/runs/abc123")
            self.assertEqual(ctl.resume(rid,plan),"RUNNING")
            self.assertEqual(adapter.submits,1)
            self.assertEqual(adapter.existing, [None,"98765"])

    def test_cli_preflight_reports_missing_real_runtime_without_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_file=str(Path(__file__).parents[1]/"examples"/"cp2k_geo_opt_energy_plan.json")
            config=str(Path(tmp)/"missing-runtime.json")
            output=StringIO()
            with redirect_stdout(output):
                code=cli_main(["preflight",plan_file,"--runtime-config",config])
            self.assertEqual(code,1)
            payload=json.loads(output.getvalue())
            self.assertFalse(payload["ready"])
            self.assertIn("not found", payload["preflight"]["reason"].lower())

    def test_input_change_changes_deterministic_task_identity(self):
        plan=example_plan(); first=compile_initial_tasks(plan)[0]
        raw=plan.as_dict(); raw["structure"]["path"]="different.xyz"
        second=compile_initial_tasks(CalculationPlan.from_mapping(raw))[0]
        self.assertNotEqual(first["task_id"],second["task_id"])

if __name__=="__main__": unittest.main()
