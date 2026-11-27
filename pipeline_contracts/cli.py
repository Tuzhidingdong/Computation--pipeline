"""CLI: plan, validate, preflight, run, status, resume and report."""
from __future__ import annotations
import argparse, json
from pathlib import Path

from .calculation_plan import CalculationPlan, compile_initial_tasks
from .real_workflow import build_real_workflow_adapter
from .workflow import WorkflowController, WorkflowStore, MockCP2KWorkflowAdapter


def _state_path(plan):
    return Path(plan.project_root).expanduser().resolve() / ".pipeline" / "workflow.sqlite"


def _runtime_path(plan, supplied):
    return Path(supplied).expanduser().resolve() if supplied else (
        Path(plan.project_root).expanduser().resolve() / ".pipeline" / "runtime.local.json"
    )


def main(argv=None):
    parser=argparse.ArgumentParser(prog="computation-pipeline")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("plan","validate","preflight","run"):
        p=sub.add_parser(name); p.add_argument("plan_file")
        if name in {"preflight","run"}:
            p.add_argument("--runtime-config")
        if name=="run":
            p.add_argument("--mock",action="store_true")
            p.add_argument("--state-db")
    for name in ("status","resume","report"):
        p=sub.add_parser(name); p.add_argument("run_id"); p.add_argument("--state-db",required=True)
        if name=="resume":
            p.add_argument("--mock",action="store_true")
            p.add_argument("--runtime-config")
        if name=="report": p.add_argument("--output")
    args=parser.parse_args(argv)

    if args.command in {"plan","validate","preflight","run"}:
        plan=CalculationPlan.load(args.plan_file)
        issues=plan.validate()
        if args.command=="validate":
            print(json.dumps({"valid":not issues,"issues":issues,"plan_sha256":plan.sha256},indent=2))
            return 0 if not issues else 2
        if issues:
            print(json.dumps({"valid":False,"issues":issues},indent=2))
            return 2
        if args.command=="plan":
            print(json.dumps({"plan_sha256":plan.sha256,"initial_tasks":compile_initial_tasks(plan),
                              "dynamic_rule":"cp2k.energy is created only after GEO_OPT QC passes"},indent=2))
            return 0
        runtime_path=_runtime_path(plan,args.runtime_config)
        if args.command=="preflight":
            adapter=build_real_workflow_adapter(plan,plan.project_root,runtime_path)
            task=compile_initial_tasks(plan)[0]
            result=adapter.preflight(task)
            payload={"execution_mode":"real","ready":bool(result.get("ready")),
                     "backend":plan.execution.get("backend"),"runtime_config":str(runtime_path),
                     "preflight":dict(result)}
            print(json.dumps(payload,indent=2,ensure_ascii=False))
            return 0 if result.get("ready") else 1
        state_path=Path(args.state_db).expanduser().resolve() if args.state_db else _state_path(plan)
        store=WorkflowStore(state_path)
        adapter=MockCP2KWorkflowAdapter() if args.mock else build_real_workflow_adapter(plan,plan.project_root,runtime_path)
        ctl=WorkflowController(store,adapter); run_id=ctl.create(plan)
        status=ctl.run(run_id,plan)
        mode="mock" if args.mock else getattr(adapter,"execution_mode","real")
        detail=getattr(adapter,"reason",None)
        payload={"workflow_run_id":run_id,"status":status,"state_db":str(store.path),
                 "execution_mode":mode,"runtime_config":None if args.mock else str(runtime_path)}
        if detail: payload["unavailable_reason"]=detail
        print(json.dumps(payload,indent=2,ensure_ascii=False))
        store.close()
        return 0 if status=="COMPLETED" else 1

    store=WorkflowStore(args.state_db)
    info=store.run_info(args.run_id)
    plan=CalculationPlan.from_mapping(json.loads(info["plan_json"]))
    if args.command=="status":
        result={"workflow_run_id":args.run_id,"status":info["status"],
                "execution_mode":info["execution_mode"],"tasks":store.tasks(args.run_id)}
    else:
        runtime_path=_runtime_path(plan,getattr(args,"runtime_config",None))
        adapter=MockCP2KWorkflowAdapter() if getattr(args,"mock",False) else build_real_workflow_adapter(plan,plan.project_root,runtime_path)
        ctl=WorkflowController(store,adapter)
        if args.command=="resume":
            status=ctl.resume(args.run_id,plan)
            result={"workflow_run_id":args.run_id,"status":status,
                    "execution_mode":getattr(adapter,"execution_mode","real")}
            reason=getattr(adapter,"reason",None)
            if reason: result["unavailable_reason"]=reason
        else:
            result=ctl.report(args.run_id)
            if args.output:
                Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False))
    store.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
