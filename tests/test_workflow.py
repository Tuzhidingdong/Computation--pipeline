from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from pipeline_contracts.calculation_plan import CalculationPlan, compile_initial_tasks
from pipeline_contracts.workflow import MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore

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
    def test_input_change_changes_deterministic_task_identity(self):
        plan=example_plan(); first=compile_initial_tasks(plan)[0]
        raw=plan.as_dict(); raw["structure"]["path"]="different.xyz"
        second=compile_initial_tasks(CalculationPlan.from_mapping(raw))[0]
        self.assertNotEqual(first["task_id"],second["task_id"])

if __name__=="__main__": unittest.main()
