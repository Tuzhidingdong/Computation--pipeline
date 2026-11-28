"""CLI for CalculationPlan workflows and persistent project-level orchestration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .calculation_plan import CalculationPlan, compile_initial_tasks
from .real_workflow import build_real_workflow_adapter
from .workflow import WorkflowController, WorkflowStore, MockCP2KWorkflowAdapter
from .plan_compiler import compile_docx, confirm_manifest_claims, compile_confirmed_manifest, write_manifest


def _emit_json(payload, *, indent=2):
    """ASCII-safe stdout for legacy Windows console encodings; files remain UTF-8."""
    import sys
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, indent=indent, default=str) + "\n")


def _state_path(plan):
    return Path(plan.project_root).expanduser().resolve() / ".pipeline" / "workflow.sqlite"


def _runtime_path(plan, supplied):
    return Path(supplied).expanduser().resolve() if supplied else (
        Path(plan.project_root).expanduser().resolve() / ".pipeline" / "runtime.local.json"
    )


def _project_cli(args) -> int:
    from .project_pipeline import ProjectPipeline, load_integration_factory

    pipeline = ProjectPipeline(args.state_db, args.output_root)
    try:
        if args.project_action == "start":
            result = pipeline.start_docx(args.docx_file, project_id=args.project_id,
                                         compiler=args.compiler, plan_version=args.plan_version)
        elif args.project_action == "status":
            result = pipeline.status(args.project_run_id)
        elif args.project_action == "review":
            result = pipeline.review(args.project_run_id)
        elif args.project_action == "confirm":
            try:
                changes = json.loads(args.changes)
            except json.JSONDecodeError as exc:
                raise ValueError("--changes must be a JSON object") from exc
            if not isinstance(changes, dict):
                raise ValueError("--changes must decode to a JSON object")
            result = pipeline.confirm_evidence(
                args.project_run_id, evidence_ids=args.evidence_id,
                confirmer=args.confirmed_by, rationale=args.rationale, changes=changes,
            )
        elif args.project_action == "plan":
            integrations = {}
            if args.integration_factory:
                integrations = load_integration_factory(
                    args.integration_factory,
                    project_root=pipeline._run_root(args.project_run_id),
                    run_root=pipeline._run_root(args.project_run_id),
                )
            result = pipeline.plan_scientific(
                args.project_run_id,
                profile_path=args.project_profile,
                data_analysis_api=integrations.get("data_analysis_api"),
                data_analysis_project_root=args.data_analysis_project_root,
                runtime_verified_version=args.runtime_verified_version,
            )
        elif args.project_action == "approve":
            result = pipeline.approve_model(
                args.project_run_id, candidate_id=args.candidate_id,
                approver=args.approver, approved=args.approve,
            )
        elif args.project_action == "resume":
            run_root = pipeline._run_root(args.project_run_id)
            integrations = load_integration_factory(
                args.integration_factory, project_root=run_root, run_root=run_root,
            )
            model_config = json.loads(Path(args.model_spec).read_text(encoding="utf-8")) if args.model_spec else None
            plan_data = json.loads(Path(args.calculation_plan).read_text(encoding="utf-8")) if args.calculation_plan else None
            result = pipeline.resume_mock(
                args.project_run_id,
                data_analysis_api=integrations["data_analysis_api"],
                model_config=model_config, calculation_plan_data=plan_data,
                preview_renderer=integrations.get("preview_renderer"),
                structure_writer=integrations.get("structure_writer"),
                validator=integrations.get("validator"),
            )
        elif args.project_action == "report":
            result = pipeline.report(args.project_run_id)
            if args.output:
                Path(args.output).expanduser().resolve().write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
        else:
            raise ValueError(f"unsupported project action: {args.project_action}")
        _emit_json(result)
        status = result.get("status") or result.get("project_status")
        if status == "BLOCKED" or result.get("planning_status") in {"BLOCKED", "NEEDS_DECISION", "UNSUPPORTED"}:
            return 2
        if status in {"FAILED", "FAILED_INFRASTRUCTURE"}:
            return 1
        return 0
    finally:
        pipeline.close()


def main(argv=None):
    parser=argparse.ArgumentParser(prog="computation-pipeline")
    sub=parser.add_subparsers(dest="command",required=True)

    project=sub.add_parser("project", help="persistent project-level DOCX-to-report orchestration")
    project_sub=project.add_subparsers(dest="project_action",required=True)
    p=project_sub.add_parser("start", help="retain and compile a Frozen DOCX into a Project Run")
    p.add_argument("docx_file"); p.add_argument("--project-id",required=True)
    p.add_argument("--compiler",choices=["generic","corr_dft_v4_1"],default="corr_dft_v4_1")
    p.add_argument("--plan-version"); p.add_argument("--state-db",required=True)
    p.add_argument("--output-root",required=True)
    for name in ("status","review","report"):
        p=project_sub.add_parser(name)
        p.add_argument("project_run_id"); p.add_argument("--state-db",required=True)
        p.add_argument("--output-root",required=True)
        if name=="report": p.add_argument("--output")
    p=project_sub.add_parser("confirm", help="record explicit source-evidence confirmation")
    p.add_argument("project_run_id"); p.add_argument("--state-db",required=True)
    p.add_argument("--output-root",required=True); p.add_argument("--evidence-id",action="append",required=True)
    p.add_argument("--confirmed-by",required=True); p.add_argument("--rationale",required=True)
    p.add_argument("--changes",required=True,help="JSON object describing the confirmation/change")
    p=project_sub.add_parser("plan", help="compile an evidence-first Scientific Planning Bundle for an existing Project Run")
    p.add_argument("project_run_id"); p.add_argument("--state-db",required=True)
    p.add_argument("--output-root",required=True); p.add_argument("--project-profile")
    p.add_argument("--integration-factory",help="optional existing Data_analysis API factory module:function")
    p.add_argument("--data-analysis-project-root")
    p.add_argument(
        "--runtime-verified-version",
        help="independent version observed from the installed runtime; never inferred from Project Profile or source documents",
    )
    p=project_sub.add_parser("approve", help="explicitly approve and freeze a reviewed model candidate")
    p.add_argument("project_run_id"); p.add_argument("--state-db",required=True); p.add_argument("--output-root",required=True)
    p.add_argument("--candidate-id",required=True); p.add_argument("--approver",required=True)
    p.add_argument("--approve",action="store_true",required=True)
    p=project_sub.add_parser("resume", help="continue model and Mock workflow stages from persisted state")
    p.add_argument("project_run_id"); p.add_argument("--state-db",required=True); p.add_argument("--output-root",required=True)
    p.add_argument("--mode",choices=["mock"],required=True)
    p.add_argument("--integration-factory",required=True,help="module:function returning the existing Data_analysis API and preview renderer")
    p.add_argument("--model-spec",help="JSON ModelSpec bundle; required on first resume before candidate generation")
    p.add_argument("--calculation-plan",help="complete CalculationPlan JSON; required before calculation after approval")

    for name in ("compile-docx", "compile-v41-docx"):
        p=sub.add_parser(name); p.add_argument("docx_file")
        p.add_argument("--plan-version"); p.add_argument("--output", required=True)
        if name == "compile-docx": p.add_argument("--project-id", required=True)
    p=sub.add_parser("confirm-manifest")
    p.add_argument("manifest_file"); p.add_argument("--evidence-id", action="append", required=True)
    p.add_argument("--confirmed-by", required=True); p.add_argument("--rationale", required=True)
    p.add_argument("--output", required=True)
    p=sub.add_parser("resolve-v41-planning")
    p.add_argument("manifest_file")
    p.add_argument("--orientation-scope", choices=["per_catalyst","across_both_systems"], required=True)
    p.add_argument("--fragment-spin-resolution", choices=["retain_all_six","select_four_explicitly"], required=True)
    p.add_argument("--fragment-spin-candidate", action="append", default=[])
    p.add_argument("--confirmed-by", required=True); p.add_argument("--rationale", required=True)
    p.add_argument("--output", required=True)
    p=sub.add_parser("compile-calculation-plan")
    p.add_argument("manifest_file"); p.add_argument("calculation_plan_file")
    for name in ("plan","validate","preflight","run"):
        p=sub.add_parser(name); p.add_argument("plan_file")
        if name in {"preflight","run"}: p.add_argument("--runtime-config")
        if name=="run": p.add_argument("--mock",action="store_true"); p.add_argument("--state-db")
    for name in ("status","resume","report"):
        p=sub.add_parser(name); p.add_argument("run_id"); p.add_argument("--state-db",required=True)
        if name=="resume": p.add_argument("--mock",action="store_true"); p.add_argument("--runtime-config")
        if name=="report": p.add_argument("--output")
    args=parser.parse_args(argv)

    if args.command == "project":
        return _project_cli(args)
    if args.command == "compile-docx":
        result = compile_docx(args.docx_file, project_id=args.project_id, plan_version=args.plan_version)
        write_manifest(result, args.output)
        _emit_json({"manifest":str(Path(args.output).resolve()),
                    "compilation_status":result.manifest["compilation_status"],
                    "diagnostics":list(result.diagnostics)})
        return 2 if any(item.get("blocks_execution") for item in result.diagnostics) else 0
    if args.command == "compile-v41-docx":
        from projects.corr_dft_v4_1.plan_compiler import compile_v41_docx
        result = compile_v41_docx(args.docx_file, plan_version=args.plan_version)
        write_manifest(result, args.output)
        _emit_json({"manifest":str(Path(args.output).resolve()),
                    "compilation_status":result.manifest["compilation_status"],
                    "diagnostics":list(result.diagnostics)})
        return 2 if any(item.get("blocks_execution") for item in result.diagnostics) else 0
    if args.command == "confirm-manifest":
        manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
        confirmed = confirm_manifest_claims(manifest, evidence_ids=args.evidence_id,
                                            confirmer=args.confirmed_by, rationale=args.rationale)
        write_manifest(confirmed, args.output)
        _emit_json({"manifest":str(Path(args.output).resolve()),
                    "remaining_unresolved":len(confirmed.get("unresolved_definitions", []))})
        return 0
    if args.command == "resolve-v41-planning":
        from projects.corr_dft_v4_1.plan_rules import confirm_v41_resolutions
        manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
        resolved = confirm_v41_resolutions(
            manifest, orientation_scope=args.orientation_scope,
            fragment_spin_resolution=args.fragment_spin_resolution,
            selected_fragment_spin_candidates=args.fragment_spin_candidate,
            confirmed_by=args.confirmed_by, rationale=args.rationale,
        )
        write_manifest(resolved, args.output)
        _emit_json({"manifest":str(Path(args.output).resolve()),
                    "compilation_status":resolved["compilation_status"],
                    "remaining_blockers":[x["code"] for x in resolved["diagnostics"]]})
        return 2 if resolved["compilation_status"] == "BLOCKED" else 0
    if args.command == "compile-calculation-plan":
        manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
        raw_plan = json.loads(Path(args.calculation_plan_file).read_text(encoding="utf-8"))
        plan = compile_confirmed_manifest(manifest, raw_plan)
        _emit_json({"calculation_plan":plan.as_dict(),"plan_sha256":plan.sha256})
        return 0

    if args.command in {"plan","validate","preflight","run"}:
        plan=CalculationPlan.load(args.plan_file)
        issues=plan.validate()
        if args.command=="validate":
            _emit_json({"valid":not issues,"issues":issues,"plan_sha256":plan.sha256})
            return 0 if not issues else 2
        if issues:
            _emit_json({"valid":False,"issues":issues})
            return 2
        if args.command=="plan":
            _emit_json({"plan_sha256":plan.sha256,"initial_tasks":compile_initial_tasks(plan),
                        "dynamic_rule":"cp2k.energy is created only after GEO_OPT QC passes"})
            return 0
        runtime_path=_runtime_path(plan,args.runtime_config)
        if args.command=="preflight":
            adapter=build_real_workflow_adapter(plan,plan.project_root,runtime_path)
            task=compile_initial_tasks(plan)[0]; result=adapter.preflight(task)
            _emit_json({"execution_mode":"real","ready":bool(result.get("ready")),
                        "backend":plan.execution.get("backend"),"runtime_config":str(runtime_path),
                        "preflight":dict(result)})
            return 0 if result.get("ready") else 1
        state_path=Path(args.state_db).expanduser().resolve() if args.state_db else _state_path(plan)
        store=WorkflowStore(state_path)
        adapter=MockCP2KWorkflowAdapter() if args.mock else build_real_workflow_adapter(plan,plan.project_root,runtime_path)
        ctl=WorkflowController(store,adapter); run_id=ctl.create(plan); status=ctl.run(run_id,plan)
        mode="mock" if args.mock else getattr(adapter,"execution_mode","real")
        payload={"workflow_run_id":run_id,"status":status,"state_db":str(store.path),
                 "execution_mode":mode,"runtime_config":None if args.mock else str(runtime_path)}
        detail=getattr(adapter,"reason",None)
        if detail: payload["unavailable_reason"]=detail
        _emit_json(payload); store.close()
        return 0 if status=="COMPLETED" else 1

    store=WorkflowStore(args.state_db)
    try:
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
        _emit_json(result)
        return 0
    finally:
        store.close()


if __name__=="__main__":
    raise SystemExit(main())
