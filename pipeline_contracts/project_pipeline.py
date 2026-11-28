"""End-to-end project orchestration over existing compiler, lifecycle and workflow APIs.

This module owns sequencing and provenance links only. Data_analysis remains the
Artifact/Evidence owner; WorkflowStore remains the sole persistent control ledger.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping
import hashlib
import importlib
import json
import shutil
import time

from .calculation_plan import CalculationPlan
from .plan_compiler.compiler import (
    CompilationResult, compile_confirmed_manifest, confirm_manifest_claims, write_manifest,
)
from .project_lifecycle import ProjectLifecycle
from .workflow import MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore
from projects.corr_dft_v4_1.model_plugin.pipeline import (
    generate_validate_review, approve_candidate,
)


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                      encoding="utf-8")
    return target


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stage_status(lifecycle: ProjectLifecycle, run_id: str, stage: str) -> str:
    return str(lifecycle.stage(run_id, stage)["status"])


class _RegisteredMockAdapter:
    """Decorates the existing Mock controller adapter with Data_analysis Artifact registration."""
    execution_mode = "mock"

    def __init__(self, delegate, data_analysis_api, project_root: Path,
                 approved_artifact_id: str, approved_structure_path: Path):
        self.delegate = delegate
        self.api = data_analysis_api
        self.root = project_root
        self.approved_artifact_id = approved_artifact_id
        self.approved_structure_path = approved_structure_path

    def preflight(self, task):
        return self.delegate.preflight(task)

    def execute(self, task, existing_job_id=None):
        result = self.delegate.execute(task, existing_job_id=existing_job_id)
        if result.status != "COMPLETED" or task.get("operation") != "cp2k.geo_opt":
            return result
        # Mock output bytes are explicitly copied from the approved input; they do
        # not claim a geometry optimization. They still exercise Artifact custody/SHA.
        output_dir = self.root / "mock_execution_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task['task_id']}-optimized.extxyz"
        if output_path.exists():
            if _sha256(output_path) != _sha256(self.approved_structure_path):
                raise ValueError("existing mock optimized structure differs from the frozen approved input")
        else:
            shutil.copyfile(self.approved_structure_path, output_path)
        before = _sha256(output_path)
        registered = self.api.register_derived_artifact(
            str(self.root), str(output_path),
            source_artifact_ids=[self.approved_artifact_id],
            format_id="extxyz",
            provenance={"execution_mode": "mock", "task_id": task["task_id"],
                        "kind": "optimized_structure", "not_a_scientific_optimization": True},
        )
        artifact_id = str(registered.get("artifact_id", ""))
        if not artifact_id or str(registered.get("sha256", "")).lower() != before.lower():
            raise ValueError("Data_analysis did not return the exact mock structure Artifact SHA")
        resolved = Path(self.api.resolve_artifact_path(str(self.root), artifact_id)).resolve(strict=True)
        if not resolved.is_file() or _sha256(resolved).lower() != before.lower():
            raise ValueError("resolved mock structure Artifact bytes failed SHA-256 verification")
        output_artifacts = []
        for item in result.output_artifacts:
            if item.get("kind") == "optimized_structure":
                output_artifacts.append({
                    "artifact_id": artifact_id, "sha256": before, "kind": "optimized_structure",
                    "source_system": "Data_analysis", "verified": True,
                    "uri": resolved.as_uri(), "execution_mode": "mock",
                })
            else:
                output_artifacts.append(dict(item))
        return replace(result, output_artifacts=tuple(output_artifacts))

    def analyze(self, task, artifacts):
        # The existing Mock adapter supplies deterministic mock Analysis Run and
        # Evidence Package references; no real Data_analysis run is claimed.
        return self.delegate.analyze(task, artifacts)


class ProjectPipeline:
    """Persistent end-to-end orchestration using one WorkflowStore database."""
    def __init__(self, state_db: str | Path, output_root: str | Path):
        self.store = WorkflowStore(state_db)
        self.lifecycle = ProjectLifecycle(self.store)
        self.output_root = Path(output_root).expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

    def close(self):
        self.store.close()

    def _run_root(self, run_id: str) -> Path:
        return self.output_root / run_id

    def start_docx(self, docx_path: str | Path, *, project_id: str,
                   compiler: str = "generic", plan_version: str | None = None) -> dict:
        source = Path(docx_path).expanduser().resolve(strict=True)
        if compiler == "corr_dft_v4_1":
            from projects.corr_dft_v4_1.plan_compiler import compile_v41_docx
            compilation = compile_v41_docx(source, plan_version=plan_version)
        elif compiler == "generic":
            from .plan_compiler.compiler import compile_docx
            compilation = compile_docx(source, project_id=project_id, plan_version=plan_version)
        else:
            raise ValueError("compiler must be generic or corr_dft_v4_1")
        return self.start_from_compilation(source, project_id=project_id,
                                           compilation=compilation, compiler=compiler)

    def start_from_compilation(self, source_path: str | Path, *, project_id: str,
                               compilation: CompilationResult, compiler: str) -> dict:
        """Persist a compilation result; also used by the extracted-block E2E fixture."""
        source = Path(source_path).expanduser().resolve(strict=True)
        source_hash = _sha256(source)
        manifest = dict(compilation.manifest)
        manifest.setdefault("source_document", {})
        manifest["source_document"].update({
            "file_name": source.name, "size_bytes": source.stat().st_size,
            "sha256": source_hash, "compiler": compiler,
        })
        run_id = self.lifecycle.create(project_id, manifest)
        root = self._run_root(run_id)
        root.mkdir(parents=True, exist_ok=False)
        source_copy = root / "source" / source.name
        source_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, source_copy)
        if _sha256(source_copy) != source_hash:
            raise ValueError("retained Frozen DOCX copy failed SHA-256 verification")
        manifest_path = write_manifest(manifest, root / "manifest.json")
        manifest_hash = _sha256(manifest_path)
        diagnostics_path = _write_json(root / "compile_diagnostics.json",
                                       list(manifest.get("diagnostics", [])))
        self.lifecycle.transition(run_id, "DOCX_INGEST", "COMPLETED",
            outputs={"source_docx": str(source_copy), "source_sha256": source_hash,
                     "source_size_bytes": source.stat().st_size})
        blocking = [item for item in manifest.get("diagnostics", [])
                    if item.get("blocks_execution")]
        if blocking or manifest.get("compilation_status") == "BLOCKED":
            self.lifecycle.transition(run_id, "PLAN_COMPILE", "BLOCKED",
                outputs={"manifest_path": str(manifest_path), "manifest_sha256": manifest_hash,
                         "diagnostics_path": str(diagnostics_path),
                         "blocking_diagnostics": blocking},
                error="Blocking compilation/scientific decisions remain unresolved.")
        else:
            self.lifecycle.transition(run_id, "PLAN_COMPILE", "COMPLETED",
                outputs={"manifest_path": str(manifest_path), "manifest_sha256": manifest_hash,
                         "diagnostics_path": str(diagnostics_path)})
            self.lifecycle.transition(run_id, "EVIDENCE_REVIEW", "RUNNING",
                outputs={"review_required": True})
        return self.status(run_id)

    def review(self, run_id: str) -> dict:
        manifest = self.lifecycle.manifest(run_id)
        stages = self.lifecycle.stages(run_id)
        root = self._run_root(run_id)
        review_path = root / "model_review" / "model_review_package.json"
        return {
            "project_run_id": run_id, "status": self.lifecycle.run_info(run_id)["status"],
            "source_document": manifest.get("source_document"),
            "manifest": manifest, "claims": manifest.get("claims", []),
            "evidence": manifest.get("evidence", []),
            "blocking_conflicts": [x for x in manifest.get("diagnostics", [])
                                   if x.get("blocks_execution")],
            "unresolved_structured_fields": manifest.get("unresolved_structured_fields", []),
            "unresolved_definitions": manifest.get("unresolved_definitions", []),
            "profile_reconciliation": manifest.get("profile_reconciliation", []),
            "confirmations": manifest.get("confirmations", []),
            "model_review_package": _load_json(review_path) if review_path.is_file() else None,
            "stages": stages,
        }

    def confirm_evidence(self, run_id: str, *, evidence_ids: list[str], confirmer: str,
                         rationale: str, changes: Mapping[str, Any]) -> dict:
        if not changes:
            raise ValueError("confirmation changes must describe what was confirmed or changed")
        if _stage_status(self.lifecycle, run_id, "PLAN_COMPILE") != "COMPLETED":
            raise RuntimeError("evidence confirmation cannot override a blocked compilation or scientific blocker")
        manifest = self.lifecycle.manifest(run_id)
        confirmed = confirm_manifest_claims(manifest, evidence_ids=evidence_ids,
                                             confirmer=confirmer, rationale=rationale)
        confirmed["confirmations"][-1]["changes"] = dict(changes)
        confirmed["confirmations"][-1]["recorded_at_unix"] = time.time()
        # Evidence IDs must remain references to the original DOCX evidence set.
        known = {item.get("evidence_id") for item in manifest.get("evidence", [])}
        if not set(evidence_ids).issubset(known):
            raise ValueError("confirmation references an evidence ID outside this Manifest")
        self.lifecycle.update_manifest(run_id, confirmed)
        path = _write_json(self._run_root(run_id) / "manifest.json", confirmed)
        unresolved = confirmed.get("unresolved_definitions", [])
        if unresolved:
            self.lifecycle.transition(run_id, "EVIDENCE_REVIEW", "BLOCKED",
                inputs={"evidence_ids": list(evidence_ids), "confirmed_by": confirmer},
                outputs={"manifest_path": str(path), "remaining_unresolved": unresolved},
                error="Additional source claims remain unconfirmed.")
        else:
            self.lifecycle.transition(run_id, "EVIDENCE_REVIEW", "COMPLETED",
                inputs={"evidence_ids": list(evidence_ids), "confirmed_by": confirmer,
                        "rationale": rationale, "changes": dict(changes)},
                outputs={"manifest_path": str(path), "manifest_sha256": _sha256(path)})
        return self.status(run_id)

    def generate_models(self, run_id: str, model_config: Mapping[str, Any], *,
                        data_analysis_api, preview_renderer, structure_writer=None,
                        validator=None) -> dict:
        if _stage_status(self.lifecycle, run_id, "EVIDENCE_REVIEW") != "COMPLETED":
            raise RuntimeError("model generation requires completed evidence review")
        manifest = self.lifecycle.manifest(run_id)
        blocking = [x for x in manifest.get("diagnostics", []) if x.get("blocks_execution")]
        if blocking or manifest.get("unresolved_definitions"):
            raise RuntimeError("model generation blocked by unresolved scientific decisions")
        specs = model_config.get("model_specs")
        if not isinstance(specs, list) or not specs:
            raise ValueError("model_specs must be a non-empty list of complete ModelSpec mappings")
        confirmed_ids = {
            evidence_id for record in manifest.get("confirmations", [])
            for evidence_id in record.get("evidence_ids", [])
        }
        source_ids = {item.get("evidence_id") for item in manifest.get("evidence", [])}
        for raw in specs:
            for item in raw.get("evidence", []):
                evidence_id = item.get("evidence_id")
                if evidence_id not in source_ids or evidence_id not in confirmed_ids:
                    raise ValueError(f"ModelSpec evidence must reference explicitly confirmed Manifest evidence: {evidence_id}")
        root = self._run_root(run_id)
        try:
            kwargs = {
                "lifecycle": self.lifecycle, "project_run_id": run_id,
                "data_analysis_api": data_analysis_api,
                "format_ids": dict(model_config.get("format_ids") or {}),
                "parent_artifact_ids": list(model_config.get("parent_artifact_ids") or []),
                "pseudopotential_valence_by_model": dict(model_config.get("pseudopotential_valence_by_model") or {}),
                "structure_writer": structure_writer, "preview_renderer": preview_renderer,
            }
            if validator is not None:
                kwargs["validator"] = validator
            result = generate_validate_review(
                specs, root / "model_candidates", **kwargs,
            )
            result_path = _write_json(root / "model_pipeline_result.json", result)
            if result.get("status") == "AWAITING_APPROVAL":
                self.lifecycle.transition(run_id, "MODEL_APPROVAL", "AWAITING_APPROVAL",
                    outputs={"pipeline_result": str(result_path),
                             "candidate_ids": [x["candidate_id"] for x in result["candidate_results"]],
                             "review_package": result["review_package"]})
            return {"pipeline_result": result, "pipeline_result_path": str(result_path)}
        except Exception as exc:
            stage = next((name for name in ("MODEL_GENERATE", "MODEL_VALIDATE", "MODEL_REVIEW")
                          if _stage_status(self.lifecycle, run_id, name) in {"RUNNING", "PENDING"}), None)
            if stage and _stage_status(self.lifecycle, run_id, stage) == "RUNNING":
                self.lifecycle.transition(run_id, stage, "FAILED", error=f"{type(exc).__name__}: {exc}")
            raise

    def approve_model(self, run_id: str, *, candidate_id: str, approver: str,
                      approved: bool, approval_record_path: str | Path | None = None) -> dict:
        if approved is not True:
            raise ValueError("only an explicit affirmative approval is supported; no implicit approval")
        stage = self.lifecycle.stage(run_id, "MODEL_APPROVAL")
        if stage["status"] != "AWAITING_APPROVAL":
            raise RuntimeError("project is not awaiting explicit model approval")
        result_path = Path(stage["outputs"]["pipeline_result"])
        pipeline_result = _load_json(result_path)
        record_path = Path(approval_record_path) if approval_record_path else self._run_root(run_id) / "approval" / "approval_record.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = approve_candidate(
            pipeline_result, candidate_id, approver=approver,
            approval_record_path=record_path, lifecycle=self.lifecycle,
            project_run_id=run_id, approved=True,
        )
        self.lifecycle.transition(run_id, "MODEL_ARTIFACT_FREEZE", "COMPLETED",
                                   outputs={"approval_record": str(record_path),
                                            "approval_record_sha256": _sha256(record_path),
                                            "artifact_id": record["artifact_id"],
                                            "structure_sha256": record["structure_sha256"]})
        return record

    def resume_mock(self, run_id: str, *, data_analysis_api,
                    model_config: Mapping[str, Any] | None = None,
                    calculation_plan_data: Mapping[str, Any] | None = None,
                    preview_renderer=None, structure_writer=None, validator=None) -> dict:
        """Resume a project using Mock workflow only; production execution is not exposed here."""
        if _stage_status(self.lifecycle, run_id, "PLAN_COMPILE") != "COMPLETED":
            return self.status(run_id)
        if _stage_status(self.lifecycle, run_id, "EVIDENCE_REVIEW") != "COMPLETED":
            return self.status(run_id)
        root = self._run_root(run_id)
        root.mkdir(parents=True, exist_ok=True)
        model_config_path = root / "model_spec_bundle.json"
        plan_path = root / "calculation_plan_input.json"
        if model_config is not None:
            _write_json(model_config_path, model_config)
        if calculation_plan_data is not None:
            _write_json(plan_path, calculation_plan_data)
        if _stage_status(self.lifecycle, run_id, "MODEL_GENERATE") == "PENDING":
            if not model_config_path.is_file() or preview_renderer is None:
                raise ValueError("first project resume requires a ModelSpec bundle and a 3D preview renderer")
            self.generate_models(run_id, _load_json(model_config_path),
                                 data_analysis_api=data_analysis_api,
                                 preview_renderer=preview_renderer,
                                 structure_writer=structure_writer, validator=validator)
            return self.status(run_id)
        approval_stage = _stage_status(self.lifecycle, run_id, "MODEL_APPROVAL")
        if approval_stage == "AWAITING_APPROVAL":
            return self.status(run_id)
        if approval_stage != "COMPLETED" or _stage_status(self.lifecycle, run_id, "MODEL_ARTIFACT_FREEZE") != "COMPLETED":
            return self.status(run_id)

        approval_row = self.lifecycle.stage(run_id, "MODEL_ARTIFACT_FREEZE")["outputs"]
        approval = self.lifecycle.approval(run_id, self.lifecycle.stage(run_id, "MODEL_APPROVAL")["outputs"]["candidate_id"])
        # The full record in stage output is the authoritative candidate binding.
        candidate_id = approval["candidate_id"]
        pipeline_result = _load_json(self.lifecycle.stage(run_id, "MODEL_APPROVAL")["outputs"]["pipeline_result"])
        candidate = next(item for item in pipeline_result["candidate_results"]
                         if item["candidate_id"] == candidate_id)
        structure_path = Path(candidate["structure_path"])
        if not verify_frozen_structure(approval, structure_path):
            raise ValueError("approved structure changed after freeze")
        if not plan_path.is_file():
            raise ValueError("approved model is frozen; an explicit complete CalculationPlan JSON is required")
        plan_raw = _load_json(plan_path)
        plan_raw.setdefault("structure", {}).pop("path", None)
        plan_raw["structure"]["artifact_id"] = approval["artifact_id"]
        plan_raw["structure"]["sha256"] = approval["structure_sha256"]
        plan = compile_confirmed_manifest(self.lifecycle.manifest(run_id), plan_raw)
        plan_file = _write_json(root / "calculation_plan.json", plan.as_dict())
        plan_hash = _sha256(plan_file)

        adapter = _RegisteredMockAdapter(
            MockCP2KWorkflowAdapter(), data_analysis_api, root,
            approval["artifact_id"], structure_path,
        )
        controller = WorkflowController(self.store, adapter)
        existing_workflow = self.lifecycle.stage(run_id, "CALCULATION_PLAN")["outputs"].get("workflow_run_id")
        if existing_workflow:
            workflow_run_id = existing_workflow
        else:
            workflow_run_id = self.lifecycle.create_calculation_run(
                run_id, candidate_id, structure_path, plan, controller,
            )
        self.lifecycle.transition(run_id, "WORKFLOW_EXECUTION", "RUNNING",
                                   outputs={"workflow_run_id": workflow_run_id,
                                            "execution_mode": "mock", "calculation_plan_sha256": plan_hash})
        workflow_status = controller.resume(workflow_run_id, plan) if existing_workflow else controller.run(workflow_run_id, plan)
        workflow_report = controller.report(workflow_run_id)
        _write_json(root / "workflow_report.json", workflow_report)
        if workflow_status != "COMPLETED":
            terminal = "BLOCKED" if workflow_status in {"BLOCKED", "UNAVAILABLE", "LOCKED",
                                                         "INTERRUPTED_RECOVERY", "SUBMISSION_UNKNOWN"} else "FAILED"
            self.lifecycle.transition(run_id, "WORKFLOW_EXECUTION", terminal,
                outputs={"workflow_run_id": workflow_run_id, "workflow_status": workflow_status,
                         "workflow_report": str(root / "workflow_report.json")},
                error=f"Mock Workflow ended as {workflow_status}")
            return self.status(run_id)
        self.lifecycle.transition(run_id, "WORKFLOW_EXECUTION", "COMPLETED",
            outputs={"workflow_run_id": workflow_run_id, "workflow_status": workflow_status,
                     "workflow_report": str(root / "workflow_report.json")})
        self.lifecycle.transition(run_id, "RESULT_DELIVERY", "RUNNING")
        final_report = self.report(run_id, write=False)
        final_path = _write_json(root / "final_project_report.json", final_report)
        self.lifecycle.transition(run_id, "RESULT_DELIVERY", "COMPLETED",
                                  outputs={"final_report": str(final_path),
                                           "final_report_sha256": _sha256(final_path)})
        return self.status(run_id)

    def status(self, run_id: str) -> dict:
        info = self.lifecycle.run_info(run_id)
        stages = self.lifecycle.stages(run_id)
        return {
            "project_run_id": run_id, "project_id": info["project_id"], "status": info["status"],
            "created_at": info["created_at"], "updated_at": info["updated_at"],
            "stages": [{"stage": x["stage"], "status": x["status"], "error": x["error"],
                        "outputs": x["outputs"]} for x in stages],
            "blocking_diagnostics": [x for x in info["manifest"].get("diagnostics", [])
                                     if x.get("blocks_execution")],
            "workflow_run_id": next((x["outputs"].get("workflow_run_id") for x in stages
                                     if x["outputs"].get("workflow_run_id")), None),
        }

    def report(self, run_id: str, *, write: bool = True) -> dict:
        info = self.lifecycle.run_info(run_id)
        manifest = info["manifest"]
        stages = self.lifecycle.stages(run_id)
        root = self._run_root(run_id)
        approval_stage = next(x for x in stages if x["stage"] == "MODEL_APPROVAL")
        freeze_stage = next(x for x in stages if x["stage"] == "MODEL_ARTIFACT_FREEZE")
        workflow_stage = next(x for x in stages if x["stage"] == "WORKFLOW_EXECUTION")
        workflow_report = None
        workflow_id = self.status(run_id)["workflow_run_id"]
        if workflow_id:
            try:
                plan_info = self.store.run_info(workflow_id)
                plan_controller = WorkflowController(self.store, MockCP2KWorkflowAdapter())
                workflow_report = plan_controller.report(workflow_id)
                workflow_report["calculation_plan"] = json.loads(plan_info["plan_json"])
            except KeyError:
                workflow_report = {"workflow_run_id": workflow_id, "diagnostic": "Workflow Run not found"}
        candidate_pipeline = None
        pipeline_path = approval_stage["outputs"].get("pipeline_result")
        if pipeline_path and Path(pipeline_path).is_file():
            candidate_pipeline = _load_json(pipeline_path)
        approval_record = None
        if approval_stage["outputs"].get("approval_record"):
            record_path = Path(approval_stage["outputs"]["approval_record"])
            if record_path.is_file():
                approval_record = _load_json(record_path)
        result = {
            "schema_version": "1.0.0", "project_run_id": run_id, "project_id": info["project_id"],
            "project_status": info["status"], "created_at": info["created_at"],
            "source_document": manifest.get("source_document"),
            "manifest": manifest, "manifest_sha256": _sha256(root / "manifest.json") if (root / "manifest.json").is_file() else None,
            "confirmations": manifest.get("confirmations", []),
            "model_pipeline": candidate_pipeline, "approval_record": approval_record,
            "approval_integrity_verified": bool(approval_record and
                __import__("projects.corr_dft_v4_1.model_plugin.approval", fromlist=["verify_approval_record_integrity"])
                .verify_approval_record_integrity(approval_record)),
            "approval_artifact_id": (approval_record or {}).get("artifact_id"),
            "approval_structure_sha256": (approval_record or {}).get("structure_sha256"),
            "workflow_run_id": workflow_id, "workflow": workflow_report,
            "stages": stages,
            "diagnostics": {
                "blocking": [x for x in manifest.get("diagnostics", []) if x.get("blocks_execution")],
                "unresolved": manifest.get("unresolved_structured_fields", []),
                "unconfirmed_claims": manifest.get("unresolved_definitions", []),
                "workflow_error": workflow_stage["error"],
            },
        }
        if write:
            _write_json(root / "final_project_report.json", result)
        return result


def verify_frozen_structure(approval: Mapping[str, Any], structure_path: str | Path) -> bool:
    from projects.corr_dft_v4_1.model_plugin.approval import verify_approval_record
    return verify_approval_record(approval, structure_path)


def load_integration_factory(spec: str, *, project_root: str | Path, run_root: str | Path) -> dict:
    """Load an explicit external Data_analysis integration factory; never create a local store."""
    if ":" not in spec:
        raise ValueError("integration factory must use module:function syntax")
    module_name, function_name = spec.split(":", 1)
    factory = getattr(importlib.import_module(module_name), function_name)
    supplied = factory(project_root=str(Path(project_root).resolve()),
                       run_root=str(Path(run_root).resolve()))
    if not isinstance(supplied, Mapping) or supplied.get("data_analysis_api") is None:
        raise ValueError("factory must return a mapping with the existing data_analysis_api object")
    return dict(supplied)
