"""CLI: plan, validate, run, status, resume and report."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .calculation_plan import CalculationPlan, compile_initial_tasks
from .workflow import WorkflowController, WorkflowStore, MockCP2KWorkflowAdapter

def _state_path(plan): return Path(plan.project_root) / ".pipeline" / "workflow.sqlite"

def main(argv=None):
    parser=argparse.ArgumentParser(prog="computation-pipeline")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("plan","validate","run"):
        p=sub.add_parser(name); p.add_argument("plan_file"); p.add_argument("--mock",action="store_true")
        if name=="run": p.add_argument("--state-db")
    for name in ("status","resume","report"):
        p=sub.add_parser(name); p.add_argument("run_id"); p.add_argument("--state-db",required=True)
        if name=="resume": p.add_argument("--mock",action="store_true")
        if name=="report": p.add_argument("--output")
    args=parser.parse_args(argv)
    if args.command in {"plan","validate","run"}:
        plan=CalculationPlan.load(args.plan_file); issues=plan.validate()
        if args.command=="validate":
            print(json.dumps({"valid":not issues,"issues":issues,"plan_sha256":plan.sha256},indent=2)); return 0 if not issues else 2
        if issues:
            print(json.dumps({"valid":False,"issues":issues},indent=2)); return 2
        if args.command=="plan":
            print(json.dumps({"plan_sha256":plan.sha256,"initial_tasks":compile_initial_tasks(plan),
                              "dynamic_rule":"cp2k.energy is created only after GEO_OPT QC passes"},indent=2)); return 0
        store=WorkflowStore(args.state_db or _state_path(plan))
        adapter=MockCP2KWorkflowAdapter() if args.mock else None
        ctl=WorkflowController(store,adapter); run_id=ctl.create(plan)
        status=ctl.run(run_id,plan)
        print(json.dumps({"workflow_run_id":run_id,"status":status,"state_db":str(store.path),
                          "execution_mode":"mock" if args.mock else "real-unavailable"},indent=2))
        store.close(); return 0 if status=="COMPLETED" else 1
    store=WorkflowStore(args.state_db); info=store.run_info(args.run_id)
    plan=CalculationPlan.from_mapping(json.loads(info["plan_json"]))
    adapter=MockCP2KWorkflowAdapter() if getattr(args,"mock",False) else None
    ctl=WorkflowController(store,adapter)
    if args.command=="status": result={"workflow_run_id":args.run_id,"status":info["status"],"tasks":store.tasks(args.run_id)}
    elif args.command=="resume":
        status=ctl.resume(args.run_id,plan); result={"workflow_run_id":args.run_id,"status":status}
    else:
        result=ctl.report(args.run_id)
        if args.output: Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False)); store.close(); return 0

if __name__=="__main__": raise SystemExit(main())
