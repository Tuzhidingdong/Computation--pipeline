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
from .workflow import ExecutionResult, MockCP2KWorkflowAdapter, WorkflowController, WorkflowStore
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
        if result.status != "COMPLETED":
            return result
        if task.get("operation") == "cp2k.geo_opt":
            from .scientific_planning.engines import evaluate_qc
            evidence = {
                "output_files_complete": bool(result.output_artifacts),
                "artifact_hashes_verified": all(len(str(x.get("sha256", ""))) == 64 for x in result.output_artifacts),
                "program_normal_termination": result.scheduler_state == "COMPLETED",
                "scheduler_completed": result.scheduler_state == "COMPLETED" and result.application_exit_code == 0,
                "technical_convergence": result.converged is True,
                "all_optimizer_criteria_met": result.converged is True,
                "numerical_values_finite": True,
                "structural_anomalies_absent": True,
                "atom_count_and_identity_preserved": True,
                "cell_constraints_preserved": True,
            }
            qc_result = evaluate_qc("geo_opt", evidence)
            mock_qc = {
                "agent_a_qc": qc_result,
                "qc_evidence_mode": "MOCK_ADAPTER_SYNTHETIC_EVIDENCE_NOT_SCIENTIFIC_VALIDATION",
                "scientific_conclusion_status": "REQUIRES_SCIENTIFIC_REVIEW",
                "user_acceptance_status": "WAITING_FOR_USER_ACCEPTANCE",
            }
            result = replace(result, converged=(result.converged is True and
                                                 qc_result.get("technical_qc_status") == "TECHNICAL_QC_PASSED"),
                             qc={**dict(result.qc), **mock_qc})
        if task.get("operation") != "cp2k.geo_opt":
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
        """Persist explicitly labelled Mock result, Analysis Run and Evidence Package via Data_analysis."""
        mock = self.delegate.analyze(task, artifacts)
        if mock.status != "COMPLETED":
            return mock
        from .scientific_planning.engines import evaluate_qc
        analysis_qc = evaluate_qc("energy_scf", {
            "output_files_complete": bool(artifacts),
            "artifact_hashes_verified": all(len(str(x.get("sha256", ""))) == 64 for x in artifacts),
            "program_normal_termination": True,
            "scheduler_completed": True,
            "technical_convergence": True,
            "scf_converged": True,
            "numerical_values_finite": True,
            "structural_anomalies_absent": True,
            "electronic_state_consistent": True,
            "energy_reference_declared": True,
        })
        task_id = str(task["task_id"])
        mock_dir = self.root / "mock_execution_outputs"
        mock_dir.mkdir(parents=True, exist_ok=True)
        result_path = mock_dir / f"{task_id}-analysis-result.json"
        result_payload = {
            "schema_version": "1.0.0", "result_type": "mock_energy_execution",
            "execution_mode": "mock", "not_scientific_result": True,
            "pipeline_task_id": task_id,
            "input_artifact_id": str(task.get("input", {}).get("artifact_id", "")),
            "mock_cp2k_output_artifacts": [dict(item) for item in artifacts],
            "scientific_qc": "not_assessed",
            "agent_a_qc": analysis_qc,
            "qc_evidence_mode": "MOCK_ADAPTER_SYNTHETIC_EVIDENCE_NOT_SCIENTIFIC_VALIDATION",
        }
        _write_json(result_path, result_payload)
        digest = _sha256(result_path)
        parent_ids = [self.approved_artifact_id]
        input_id = str(task.get("input", {}).get("artifact_id", ""))
        if input_id and input_id not in parent_ids:
            parent_ids.append(input_id)
        registered = self.api.register_derived_artifact(
            str(self.root), str(result_path),
            source_artifact_ids=parent_ids,
            format_id="json_records",
            parser_id="pipeline-mock-workflow",
            parser_version="1",
            parse_status="parsed",
            parse_assurance="unverified",
            quality_status="not_assessed",
            analysis_eligibility="not_assessed",
            use_status="undecided",
            warnings=["Mock execution only; no CP2K calculation or scientific result was produced."],
            provenance={
                "operation_id": "pipeline.mock.cp2k.energy",
                "operation_version": "1",
                "pipeline_task_id": task_id,
                "execution_mode": "mock",
            },
        )
        if not isinstance(registered, Mapping):
            raise TypeError("Data_analysis register_derived_artifact must return a mapping")
        required = {"artifact_id", "sha256", "format_id", "source_locator", "artifact", "record_path"}
        missing = required.difference(registered)
        if missing:
            raise ValueError("Data_analysis derived Artifact response missing: " + ", ".join(sorted(missing)))
        if str(registered["sha256"]).lower() != digest.lower():
            raise ValueError("Data_analysis mock result Artifact SHA-256 does not match persisted bytes")
        resolved_result = Path(self.api.resolve_artifact_path(
            str(self.root), str(registered["artifact_id"])
        )).resolve(strict=True)
        if not resolved_result.is_file() or _sha256(resolved_result).lower() != digest.lower():
            raise ValueError("Data_analysis resolver returned mock result bytes with a different SHA-256")
        analysis_response = self.api.create_dft_analysis_run_from_project(
            project_root=str(self.root),
            input_artifact_ids=[input_id] if input_id else [self.approved_artifact_id],
            output_artifacts=[dict(registered)],
            operation_id="pipeline.mock.cp2k.energy",
            operation_version="1",
            parameters={
                "pipeline_task_id": task_id, "execution_mode": "mock",
                "not_scientific_result": True,
            },
            software={"pipeline": "Computation--pipeline", "execution_mode": "mock"},
            persist=True, status="completed",
            structure_artifact_id=input_id or self.approved_artifact_id,
            structure_sha256=str(task.get("input", {}).get("sha256") or
                                 _sha256(self.approved_structure_path)),
            approved_model_sha256=_sha256(self.approved_structure_path),
            upstream_job_reference=task.get("_upstream_job_reference"),
            parser_id="pipeline-mock-workflow", parser_version="1",
            units={}, assumptions=("No CP2K execution was performed.",),
            warnings=("Mock result only; no scientific energy value is represented.",),
            qc_status="not_assessed", environment={"execution_mode": "mock"},
        )
        if (not isinstance(analysis_response, Mapping)
                or not isinstance(analysis_response.get("analysis_run"), Mapping)
                or not analysis_response.get("record_path")):
            raise ValueError("Data_analysis did not persist a valid Mock Analysis Run")
        analysis_run = dict(analysis_response["analysis_run"])
        analysis_id = str(analysis_run.get("analysis_run_id") or "")
        if not analysis_id:
            raise ValueError("Data_analysis Analysis Run has no analysis_run_id")
        if str(registered["artifact_id"]) not in list(analysis_run.get("output_artifact_ids", [])):
            raise ValueError("Data_analysis Analysis Run did not retain the registered Mock result Artifact ID")
        output_hashes = dict(analysis_run.get("output_hashes", {}))
        if str(output_hashes.get(str(registered["artifact_id"]), "")).lower() != digest.lower():
            raise ValueError("Data_analysis Analysis Run did not retain the registered Mock result Artifact SHA-256")
        evidence_response = self.api.build_evidence_package(
            dft_analysis_runs=[analysis_response["record_path"]],
            question="Mock Pipeline workflow result and provenance (not scientific evidence)",
        )
        if not isinstance(evidence_response, Mapping) or not evidence_response.get("evidence_package_id"):
            raise ValueError("Data_analysis did not build a Mock Evidence Package")
        evidence_id = str(evidence_response["evidence_package_id"])
        return replace(
            mock, output_artifacts=({"artifact_id": str(registered["artifact_id"]),
                                     "sha256": digest, "kind": "mock_analysis_result",
                                     "source_system": "Data_analysis", "verified": True,
                                     "record_path": str(registered["record_path"]),
                                     "execution_mode": "mock"},),
            analysis_run_id=analysis_id, evidence_package_id=evidence_id,
            runtime={**dict(mock.runtime), "analysis_execution_mode": "mock",
                     "analysis_result_artifact_id": str(registered["artifact_id"]),
                     "analysis_result_sha256": digest},
        )


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
        if _stage_status(self.lifecycle, run_id, "PLAN_COMPILE") != "COMPLETED":
            raise RuntimeError("evidence confirmation cannot override a blocked compilation or scientific blocker")

        # Evidence Review is the only mutable confirmation window. BLOCKED is
        # intentional here: it permits additional batches while unresolved
        # source definitions remain. Once completed, the Manifest is immutable.
        review_status = _stage_status(self.lifecycle, run_id, "EVIDENCE_REVIEW")
        if review_status not in {"RUNNING", "BLOCKED"}:
            raise RuntimeError(
                f"Manifest confirmation is closed when EVIDENCE_REVIEW is {review_status}"
            )
        downstream_stages = (
            "MODEL_GENERATE", "MODEL_VALIDATE", "MODEL_REVIEW", "MODEL_APPROVAL",
            "MODEL_ARTIFACT_FREEZE", "CALCULATION_PLAN", "WORKFLOW_EXECUTION",
            "RESULT_DELIVERY",
        )
        started = [
            stage for stage in downstream_stages
            if _stage_status(self.lifecycle, run_id, stage) != "PENDING"
        ]
        if started:
            raise RuntimeError(
                "Manifest confirmation is closed after downstream stages have started: "
                + ", ".join(started)
            )
        if not changes:
            raise ValueError("confirmation changes must describe what was confirmed or changed")

        # No Manifest read/transform or persistent write occurs before the phase
        # and downstream-stage guards above have passed.
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

    def plan_scientific(self, run_id: str, *, profile_path: str | Path | None = None,
                        data_analysis_api=None, data_analysis_project_root: str | Path | None = None) -> dict:
        """Compile the Scientific Planning Bundle using existing lifecycle and Artifact APIs."""
        from .scientific_planning.planning_orchestrator import plan_project_run
        return plan_project_run(
            self, run_id, profile_path=profile_path,
            data_analysis_api=data_analysis_api,
            data_analysis_project_root=data_analysis_project_root,
        )

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
        if pipeline_result.get("planning_mode") == "scientific_planning_core":
            from projects.corr_dft_v4_1.model_plugin.approval import create_approval_record
            candidate = next((item for item in pipeline_result.get("candidate_results", [])
                              if item.get("candidate_id") == candidate_id), None)
            if candidate is None:
                raise KeyError(f"unknown Planning Core model candidate {candidate_id!r}")
            record = create_approval_record(
                record_path, approver=approver, candidate_id=candidate_id,
                artifact_ref=candidate["artifact_ref"], structure_path=candidate["structure_path"],
                validation_report=candidate["validation_report"], approved=True,
            )
            self.lifecycle.freeze_approval(run_id, record)
            freeze_outputs = self.lifecycle.stage(run_id, "MODEL_ARTIFACT_FREEZE")["outputs"]
            freeze_outputs.update({
                "approval_record": str(record_path),
                "approval_record_sha256": _sha256(record_path),
            })
            self.lifecycle.transition(run_id, "MODEL_ARTIFACT_FREEZE", "COMPLETED",
                                      outputs=freeze_outputs)
            return record

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

    def _bind_approved_calculation_plan(self, run_id: str, raw_plan: Mapping[str, Any],
                                        approval: Mapping[str, Any]) -> CalculationPlan:
        if not isinstance(raw_plan, Mapping):
            raise ValueError("CalculationPlan input must be a JSON object")
        bound = dict(raw_plan)
        structure = dict(bound.get("structure") or {})
        structure.pop("path", None)
        structure["artifact_id"] = approval["artifact_id"]
        structure["sha256"] = approval["structure_sha256"]
        bound["structure"] = structure
        return compile_confirmed_manifest(self.lifecycle.manifest(run_id), bound)

    @staticmethod
    def _require_same_calculation_plan(candidate: CalculationPlan, frozen: CalculationPlan,
                                       *, source: str) -> None:
        if (candidate.plan_id != frozen.plan_id
                or candidate.sha256 != frozen.sha256
                or candidate.as_dict() != frozen.as_dict()):
            raise ValueError(
                f"{source} CalculationPlan differs from the WorkflowStore-frozen Plan "
                f"(plan_id={frozen.plan_id}, sha256={frozen.sha256})"
            )

    def _load_frozen_workflow_plan(self, workflow_run_id: str) -> tuple[CalculationPlan, dict]:
        info = self.store.run_info(workflow_run_id)
        try:
            persisted_json = json.loads(info["plan_json"])
            frozen = CalculationPlan.from_mapping(persisted_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("WorkflowStore contains an unreadable frozen CalculationPlan") from exc
        normalized = frozen.as_dict()
        if (persisted_json != normalized
                or frozen.plan_id != info["plan_id"]
                or frozen.sha256 != info["plan_hash"]):
            raise ValueError(
                "WorkflowStore frozen CalculationPlan integrity failed: plan_json, plan_id and plan_hash disagree"
            )
        frozen.require_valid()
        return frozen, info

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
        model_generation_pending = _stage_status(self.lifecycle, run_id, "MODEL_GENERATE") == "PENDING"
        if model_config is not None and model_generation_pending:
            _write_json(model_config_path, model_config)
        if _stage_status(self.lifecycle, run_id, "MODEL_GENERATE") == "PENDING":
            if calculation_plan_data is not None:
                _write_json(plan_path, calculation_plan_data)
            if not model_config_path.is_file() or preview_renderer is None:
                raise ValueError("first project resume requires a ModelSpec bundle and a 3D preview renderer")
            self.generate_models(run_id, _load_json(model_config_path),
                                 data_analysis_api=data_analysis_api,
                                 preview_renderer=preview_renderer,
                                 structure_writer=structure_writer, validator=validator)
            return self.status(run_id)
        approval_stage = _stage_status(self.lifecycle, run_id, "MODEL_APPROVAL")
        if approval_stage == "AWAITING_APPROVAL":
            # Before a Workflow Run exists the owner may still provide the
            # complete Plan that will be compiled after explicit approval.
            if calculation_plan_data is not None:
                _write_json(plan_path, calculation_plan_data)
            return self.status(run_id)
        if approval_stage != "COMPLETED" or _stage_status(self.lifecycle, run_id, "MODEL_ARTIFACT_FREEZE") != "COMPLETED":
            return self.status(run_id)

        approval = self.lifecycle.approval(
            run_id, self.lifecycle.stage(run_id, "MODEL_APPROVAL")["outputs"]["candidate_id"]
        )
        candidate_id = approval["candidate_id"]
        pipeline_result = _load_json(
            self.lifecycle.stage(run_id, "MODEL_APPROVAL")["outputs"]["pipeline_result"]
        )
        candidate = next(item for item in pipeline_result["candidate_results"]
                         if item["candidate_id"] == candidate_id)
        structure_path = Path(candidate["structure_path"])
        if not verify_frozen_structure(approval, structure_path):
            raise ValueError("approved structure changed after freeze")

        calculation_stage_outputs = self.lifecycle.stage(run_id, "CALCULATION_PLAN")["outputs"]
        existing_workflow = calculation_stage_outputs.get("workflow_run_id")
        if existing_workflow:
            # Once a Workflow Run exists, its WorkflowStore plan_json/plan_hash
            # is the only executable Plan. Check every supplied representation
            # before any input/final Plan file can be overwritten.
            frozen_plan, workflow_info = self._load_frozen_workflow_plan(existing_workflow)
            if (calculation_stage_outputs.get("plan_id") != frozen_plan.plan_id
                    or calculation_stage_outputs.get("plan_sha256") != frozen_plan.sha256):
                raise ValueError("ProjectLifecycle CalculationPlan reference differs from WorkflowStore frozen Plan")

            if not plan_path.is_file():
                raise ValueError("frozen Workflow Run is missing its original calculation_plan_input.json")
            disk_plan = self._bind_approved_calculation_plan(
                run_id, _load_json(plan_path), approval
            )
            self._require_same_calculation_plan(disk_plan, frozen_plan, source="On-disk input")
            if calculation_plan_data is not None:
                supplied_plan = self._bind_approved_calculation_plan(
                    run_id, calculation_plan_data, approval
                )
                self._require_same_calculation_plan(
                    supplied_plan, frozen_plan, source="Newly supplied"
                )

            plan_file = root / "calculation_plan.json"
            if not plan_file.is_file():
                raise ValueError("frozen Workflow Run is missing its final calculation_plan.json")
            frozen_file_plan = CalculationPlan.from_mapping(_load_json(plan_file))
            self._require_same_calculation_plan(
                frozen_file_plan, frozen_plan, source="Persisted final"
            )
            plan_hash = _sha256(plan_file)
            workflow_stage_outputs = self.lifecycle.stage(run_id, "WORKFLOW_EXECUTION")["outputs"]
            recorded_file_hash = workflow_stage_outputs.get("calculation_plan_sha256")
            if recorded_file_hash and recorded_file_hash != plan_hash:
                raise ValueError("Persisted final CalculationPlan file SHA-256 differs from its recorded value")
            # Resume with the exact object reconstructed from the WorkflowStore,
            # never with a caller-provided or disk-recompiled replacement.
            plan = frozen_plan
            workflow_run_id = existing_workflow
        else:
            # First Workflow Run: the complete input is still editable only
            # until this point. Persist it once, bind the approved Artifact ID/SHA,
            # validate and freeze the compiled Plan before creating the Run.
            approval_outputs = self.lifecycle.stage(run_id, "MODEL_APPROVAL")["outputs"]
            pipeline_result_path = approval_outputs.get("pipeline_result")
            planning_mode = bool(
                pipeline_result_path and Path(pipeline_result_path).is_file()
                and _load_json(pipeline_result_path).get("planning_mode") == "scientific_planning_core"
            )
            if planning_mode:
                if calculation_plan_data is not None:
                    raise ValueError("Scientific Planning Core owns CalculationPlan compilation; caller-supplied Plan JSON is rejected")
                planner_context_path = self.lifecycle.stage(run_id, "MODEL_GENERATE")["outputs"].get("planner_context_path")
                bundle_path = self.lifecycle.stage(run_id, "MODEL_GENERATE")["outputs"].get("planning_bundle_path")
                if not planner_context_path or not bundle_path:
                    raise ValueError("Planning Core bundle/context references are missing from MODEL_GENERATE")
                context = _load_json(planner_context_path)
                bundle = _load_json(bundle_path)
                from .scientific_planning.calculation_plan_compiler import compile_runtime_calculation_plan
                approval_stage_outputs = self.lifecycle.stage(run_id, "MODEL_ARTIFACT_FREEZE")["outputs"]
                approval_record_path = Path(approval_stage_outputs["approval_record"])
                approval_ref = {
                    "object_type": "ModelApproval",
                    "object_id": str(approval["candidate_id"]),
                    "schema_version": "1.0.0",
                    "sha256": _sha256(approval_record_path),
                }
                from .scientific_planning.calculation_plan_compiler import (
                    compile_runtime_calculation_plan, build_frozen_calculation_plan_object,
                )
                runtime_plan = compile_runtime_calculation_plan(
                    project_id=str(context["project_id"]), project_root=str(root),
                    title=str(context["planning_config"].get("title") or bundle["scientific_intent"]["research_question"]),
                    scientific_question=str(bundle["scientific_intent"]["research_question"]),
                    model_recipe=bundle["model_recipes"][0], method_plan=bundle["method_plan"],
                    execution_plan=bundle["execution_plan"], qc_plan=bundle["qc_plan"],
                    runtime_config=context["runtime_config"],
                    runtime_execution=context["runtime_execution"],
                    approved_artifact={"artifact_id": approval["artifact_id"],
                                        "structure_sha256": approval["structure_sha256"]},
                    approval_ref=approval_ref,
                )
                runtime_plan.require_valid()
                frozen_plan_object = build_frozen_calculation_plan_object(
                    bundle=bundle, runtime_plan=runtime_plan, approval_ref=approval_ref,
                    frozen_at=str(approval.get("approved_at") or ""),
                )
                planning_directory = Path(planner_context_path).parent
                frozen_object_path = planning_directory / "calculation_plan_object.json"
                from .scientific_planning.bundle import write_immutable_json
                write_immutable_json(frozen_object_path, frozen_plan_object)
                calculation_index_entry = {
                    "object_type": "CalculationPlan",
                    "object_id": frozen_plan_object["plan_id"],
                    "schema_version": frozen_plan_object["schema_version"],
                    "sha256": frozen_plan_object["sha256"],
                    "approval_ref": approval_ref,
                    "runtime_projection_sha256": runtime_plan.sha256,
                }
                write_immutable_json(
                    planning_directory / "calculation_plan_object.index.json",
                    calculation_index_entry,
                )
                if plan_path.exists():
                    existing = CalculationPlan.from_mapping(_load_json(plan_path))
                    self._require_same_calculation_plan(existing, runtime_plan, source="Existing generated input")
                else:
                    _write_json(plan_path, runtime_plan.as_dict())
            else:
                if calculation_plan_data is not None:
                    _write_json(plan_path, calculation_plan_data)
                if not plan_path.is_file():
                    raise ValueError("approved model is frozen; an explicit complete CalculationPlan JSON is required")
            plan = self._bind_approved_calculation_plan(
                run_id, _load_json(plan_path), approval
            )
            plan.require_valid()
            plan_file = _write_json(root / "calculation_plan.json", plan.as_dict())
            plan_hash = _sha256(plan_file)

            controller = WorkflowController(self.store, MockCP2KWorkflowAdapter())
            workflow_run_id = self.lifecycle.create_calculation_run(
                run_id, candidate_id, structure_path, plan, controller,
            )
            if planning_mode:
                calculation_outputs = self.lifecycle.stage(run_id, "CALCULATION_PLAN")["outputs"]
                calculation_outputs.update({
                    "planning_calculation_plan_object_path": str(frozen_object_path),
                    "planning_calculation_plan_object_sha256": frozen_plan_object["sha256"],
                    "runtime_calculation_plan_sha256": runtime_plan.sha256,
                })
                self.lifecycle.transition(run_id, "CALCULATION_PLAN", "COMPLETED",
                                          outputs=calculation_outputs)

        # Candidate package registration already bound Data_analysis to this
        # project root. All subsequent derived Artifacts and Analysis Runs must
        # use that same registry root and namespace.
        data_analysis_project_root = root / "model_candidates"
        if pipeline_result.get("planning_mode") == "scientific_planning_core":
            planner_context_path = self.lifecycle.stage(run_id, "MODEL_GENERATE")["outputs"].get("planner_context_path")
            if planner_context_path:
                planner_context = _load_json(planner_context_path)
                configured_root = planner_context.get("data_analysis_project_root")
                if configured_root:
                    data_analysis_project_root = Path(configured_root)
        adapter = _RegisteredMockAdapter(
            MockCP2KWorkflowAdapter(), data_analysis_api, data_analysis_project_root,
            approval["artifact_id"], structure_path,
        )
        controller = WorkflowController(self.store, adapter)
        self.lifecycle.transition(run_id, "WORKFLOW_EXECUTION", "RUNNING",
                                   outputs={"workflow_run_id": workflow_run_id,
                                            "execution_mode": "mock", "calculation_plan_sha256": plan_hash})
        workflow_status = (
            controller.resume(workflow_run_id, plan) if existing_workflow
            else controller.run(workflow_run_id, plan)
        )
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
        final_path = root / "final_project_report.json"
        self.lifecycle.transition(run_id, "RESULT_DELIVERY", "COMPLETED",
                                  outputs={"final_report": str(final_path)})
        final_report = self.report(run_id, write=False)
        _write_json(final_path, final_report)
        delivery_outputs = self.lifecycle.stage(run_id, "RESULT_DELIVERY")["outputs"]
        delivery_outputs["final_report_sha256"] = _sha256(final_path)
        self.lifecycle.transition(run_id, "RESULT_DELIVERY", "COMPLETED",
                                  outputs=delivery_outputs)
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
        if freeze_stage["outputs"].get("approval_record"):
            record_path = Path(freeze_stage["outputs"]["approval_record"])
            if record_path.is_file():
                approval_record = _load_json(record_path)
        approval_integrity = False
        structure_integrity = False
        if approval_record:
            from projects.corr_dft_v4_1.model_plugin.approval import (
                verify_approval_record_integrity, verify_approval_record,
            )
            approval_integrity = verify_approval_record_integrity(approval_record)
            if candidate_pipeline:
                candidate = next((item for item in candidate_pipeline.get("candidate_results", [])
                                  if item.get("candidate_id") == approval_record.get("candidate_id")), None)
                if candidate and candidate.get("structure_path"):
                    structure_integrity = verify_approval_record(approval_record, candidate["structure_path"])
        planning_bundle = None
        planning_index = None
        planning_outputs = self.lifecycle.stage(run_id, "MODEL_GENERATE")["outputs"]
        planning_path = planning_outputs.get("planning_bundle_path")
        if planning_path and Path(planning_path).is_file():
            planning_bundle = _load_json(planning_path)
            index_path = Path(planning_path).with_name("planning_index.json")
            if index_path.is_file():
                planning_index = _load_json(index_path)
        calculation_plan_object = None
        calculation_plan_object_path = (
            self.lifecycle.stage(run_id, "CALCULATION_PLAN")["outputs"].get("planning_calculation_plan_object_path")
        )
        if calculation_plan_object_path and Path(calculation_plan_object_path).is_file():
            calculation_plan_object = _load_json(calculation_plan_object_path)
        result = {
            "schema_version": "1.0.0", "project_run_id": run_id, "project_id": info["project_id"],
            "project_status": info["status"], "created_at": info["created_at"],
            "source_document": manifest.get("source_document"),
            "manifest": manifest, "manifest_sha256": _sha256(root / "manifest.json") if (root / "manifest.json").is_file() else None,
            "confirmations": manifest.get("confirmations", []),
            "model_pipeline": candidate_pipeline, "scientific_planning_bundle": planning_bundle,
            "scientific_planning_index": planning_index,
            "scientific_calculation_plan": calculation_plan_object,
            "approval_record": approval_record,
            "approval_integrity_verified": approval_integrity,
            "approved_structure_current_sha_verified": structure_integrity,
            "approval_artifact_id": (approval_record or {}).get("artifact_id"),
            "approval_structure_sha256": (approval_record or {}).get("structure_sha256"),
            "approval_validation_report_sha256": (approval_record or {}).get("validation_report_sha256"),
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
            final_path = root / "final_project_report.json"
            for item in result["stages"]:
                if item["stage"] == "RESULT_DELIVERY":
                    item["outputs"].pop("final_report_sha256", None)
            _write_json(final_path, result)
            digest = _sha256(final_path)
            delivery_outputs = self.lifecycle.stage(run_id, "RESULT_DELIVERY")["outputs"]
            delivery_outputs.update({"final_report": str(final_path), "final_report_sha256": digest})
            self.lifecycle.transition(run_id, "RESULT_DELIVERY",
                                      self.lifecycle.stage(run_id, "RESULT_DELIVERY")["status"],
                                      outputs=delivery_outputs)
            result["final_report_path"] = str(final_path)
            result["final_report_sha256"] = digest
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
