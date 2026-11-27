"""Minimal synchronous CST (optional) -> Data_analysis -> Evidence runner."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import CSTAdapter, DataAnalysisAdapter
from .models import (
    AdapterOutcome, AnalysisOutcome, AnalysisRequest, ArtifactRef, CSTTaskRequest,
    ContractError, Diagnostic, DiagnosticSeverity, EvidenceRef, TaskStatus,
)


@dataclass(frozen=True)
class CSTValidationSpec:
    operation: str
    input_artifact_ids: tuple[str, ...] = ()
    arguments: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ContractError("CST validation operation must be a non-empty string")
        object.__setattr__(self, "input_artifact_ids", tuple(self.input_artifact_ids))
        if not isinstance(self.arguments, Mapping) or not isinstance(self.parameters, Mapping):
            raise ContractError("CST validation arguments and parameters must be mappings")
        if not isinstance(self.required, bool):
            raise ContractError("CST validation required must be boolean")


@dataclass(frozen=True)
class PipelineTaskManifest:
    task_id: str
    project_root: str | Path
    input_artifact_ids: tuple[str, ...]
    operation: str = "dft.artifact.read"
    parameters: Mapping[str, Any] = field(default_factory=dict)
    input_artifact_hashes: Mapping[str, str] = field(default_factory=dict)
    input_artifact_formats: Mapping[str, str] = field(default_factory=dict)
    cst_validation: CSTValidationSpec | Mapping[str, Any] | None = None
    structure_metadata: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ContractError("task_id must be a non-empty string")
        root = str(self.project_root).strip()
        if not root:
            raise ContractError("project_root must be a non-empty path")
        object.__setattr__(self, "project_root", root)
        ids = tuple(self.input_artifact_ids)
        if not ids or any(not isinstance(x, str) or not x.strip() for x in ids):
            raise ContractError("input_artifact_ids must contain at least one non-empty Artifact ID")
        if len(set(ids)) != len(ids):
            raise ContractError("input_artifact_ids must not contain duplicates")
        object.__setattr__(self, "input_artifact_ids", ids)
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ContractError("operation must be a non-empty string")
        for name, value in (
            ("parameters", self.parameters),
            ("input_artifact_hashes", self.input_artifact_hashes),
            ("input_artifact_formats", self.input_artifact_formats),
            ("structure_metadata", self.structure_metadata),
            ("metadata", self.metadata),
        ):
            if not isinstance(value, Mapping):
                raise ContractError(f"{name} must be a mapping")
        if set(self.input_artifact_hashes).difference(ids) or set(self.input_artifact_formats).difference(ids):
            raise ContractError("Artifact hash/format metadata may only refer to listed input IDs")
        for artifact_id, digest in self.input_artifact_hashes.items():
            ArtifactRef(artifact_id=artifact_id, sha256=digest)
        if isinstance(self.cst_validation, Mapping):
            object.__setattr__(self, "cst_validation", CSTValidationSpec(**dict(self.cst_validation)))
        elif self.cst_validation is not None and not isinstance(self.cst_validation, CSTValidationSpec):
            raise ContractError("cst_validation must be CSTValidationSpec, mapping, or None")
        if isinstance(self.cst_validation, CSTValidationSpec):
            selected = self.cst_validation.input_artifact_ids
            if selected and not set(selected).issubset(ids):
                raise ContractError("CST validation may select only manifest input Artifact IDs")


@dataclass(frozen=True)
class PipelineStageResult:
    name: str
    status: TaskStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class PipelineTaskResult:
    task_id: str
    status: TaskStatus
    state_history: tuple[TaskStatus, ...]
    stages: tuple[PipelineStageResult, ...]
    input_artifacts: tuple[ArtifactRef, ...]
    cst_outcome: AdapterOutcome | None = None
    analysis_outcome: AnalysisOutcome | None = None
    analysis_run_id: str | None = None
    analysis_run_record: Mapping[str, Any] = field(default_factory=dict)
    output_artifacts: tuple[ArtifactRef, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    evidence_package: Mapping[str, Any] | None = None
    qc_status: str = "not_assessed"
    diagnostics: tuple[Diagnostic, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
    execution_mode: str = "real"

    @property
    def succeeded(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED


class PipelineRunner:
    """Run one post-processing task. Adapters are explicit dependencies."""

    def __init__(
        self,
        *,
        data_analysis_adapter: DataAnalysisAdapter | None,
        cst_adapter: CSTAdapter | None = None,
    ) -> None:
        self.data_analysis_adapter = data_analysis_adapter
        self.cst_adapter = cst_adapter

    @staticmethod
    def _unavailable(status: TaskStatus, diagnostics: Sequence[Diagnostic]) -> bool:
        if status == TaskStatus.UNAVAILABLE:
            return True
        if status != TaskStatus.FAILED:
            return False
        codes = " ".join(d.code.upper() for d in diagnostics)
        return any(x in codes for x in ("UNAVAILABLE", "DEPENDENCY_MISSING", "DEPENDENCY_UNAVAILABLE"))

    @staticmethod
    def _input_refs(manifest: PipelineTaskManifest, mock: bool) -> tuple[ArtifactRef, ...]:
        refs = []
        for artifact_id in manifest.input_artifact_ids:
            options: dict[str, Any] = {
                "artifact_id": artifact_id,
                "sha256": manifest.input_artifact_hashes.get(artifact_id),
                "format_id": manifest.input_artifact_formats.get(artifact_id),
                "source_system": "Data_analysis",
            }
            if mock:
                options.update(uri=f"mock://pipeline-input/{manifest.task_id}/{artifact_id}", mock=True)
            refs.append(ArtifactRef(**options))
        return tuple(refs)

    def _cst_refs(
        self, inputs: tuple[ArtifactRef, ...], spec: CSTValidationSpec
    ) -> tuple[ArtifactRef, ...]:
        selected_ids = spec.input_artifact_ids or tuple(x.artifact_id for x in inputs)
        by_id = {x.artifact_id: x for x in inputs}
        selected = tuple(by_id[x] for x in selected_ids)
        resolver = getattr(self.data_analysis_adapter, "resolve_artifact_path", None)
        if not callable(resolver):
            return selected
        resolved = []
        for artifact in selected:
            path = Path(resolver(artifact)).expanduser().resolve(strict=True)
            digest = artifact.sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
            resolved.append(replace(artifact, uri=path.as_uri(), sha256=digest))
        return tuple(resolved)

    def _finish(
        self,
        manifest: PipelineTaskManifest,
        status: TaskStatus,
        history: list[TaskStatus],
        stages: list[PipelineStageResult],
        inputs: tuple[ArtifactRef, ...],
        cst: AdapterOutcome | None = None,
        analysis: AnalysisOutcome | None = None,
        error: str | None = None,
        extra: Sequence[Diagnostic] = (),
    ) -> PipelineTaskResult:
        history.append(status)
        diagnostics = [d for stage in stages for d in stage.diagnostics] + list(extra)
        warnings = []
        modes = set()
        for outcome in (cst, analysis):
            if outcome is not None:
                modes.add(outcome.execution_mode)
                warnings.extend(getattr(outcome, "warnings", ()))
        warnings.extend(d.message for d in diagnostics if d.severity == DiagnosticSeverity.WARNING)
        if error is None and analysis is not None:
            error = analysis.error
        if error is None and cst is not None and status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE}:
            error = cst.error
        execution_mode = "mock" if modes == {"mock"} else "real" if not modes or modes == {"real"} else "mixed"
        return PipelineTaskResult(
            task_id=manifest.task_id,
            status=status,
            state_history=tuple(history),
            stages=tuple(stages),
            input_artifacts=inputs,
            cst_outcome=cst,
            analysis_outcome=analysis,
            analysis_run_id=analysis.analysis_run_id if analysis else None,
            analysis_run_record=dict(analysis.analysis_run_record) if analysis else {},
            output_artifacts=analysis.output_artifacts if analysis else (),
            evidence_refs=analysis.evidence_refs if analysis else (),
            evidence_package=analysis.evidence_package if analysis else None,
            qc_status=analysis.qc_status if analysis else "not_assessed",
            diagnostics=tuple(diagnostics),
            warnings=tuple(dict.fromkeys(warnings)),
            error=error,
            execution_mode=execution_mode,
        )

    def run(self, task_manifest: PipelineTaskManifest) -> PipelineTaskResult:
        if not isinstance(task_manifest, PipelineTaskManifest):
            raise ContractError("run() requires a PipelineTaskManifest")
        history = [TaskStatus.PENDING, TaskStatus.RUNNING]
        stages: list[PipelineStageResult] = []

        if self.data_analysis_adapter is None:
            message = "No Data_analysis adapter was injected; no implicit Mock or Real fallback is performed."
            diagnostic = Diagnostic("DATA_ANALYSIS_ADAPTER_UNAVAILABLE", message, DiagnosticSeverity.ERROR)
            stages.append(PipelineStageResult("data_analysis", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
            return self._finish(task_manifest, TaskStatus.UNAVAILABLE, history, stages, ())

        adapter_root = getattr(self.data_analysis_adapter, "project_root", None)
        if adapter_root is not None and Path(adapter_root).expanduser().resolve() != Path(task_manifest.project_root).expanduser().resolve():
            message = "PipelineTaskManifest.project_root does not match the injected Data_analysis adapter project_root."
            diagnostic = Diagnostic("PIPELINE_PROJECT_ROOT_MISMATCH", message, DiagnosticSeverity.ERROR)
            stages.append(PipelineStageResult("preflight", TaskStatus.FAILED, (diagnostic,), error=message))
            return self._finish(task_manifest, TaskStatus.FAILED, history, stages, (), error=message)

        mock_mode = getattr(self.data_analysis_adapter, "execution_mode", None) == "mock"
        inputs = self._input_refs(task_manifest, mock=mock_mode)
        cst_outcome = None
        spec = task_manifest.cst_validation

        if spec is not None:
            if self.cst_adapter is None:
                message = "CST validation was requested but no CST adapter was injected."
                diagnostic = Diagnostic("CST_ADAPTER_UNAVAILABLE", message, DiagnosticSeverity.ERROR)
                if spec.required:
                    stages.append(PipelineStageResult("cst_validation", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
                    return self._finish(task_manifest, TaskStatus.UNAVAILABLE, history, stages, inputs, error=message)
                stages.append(PipelineStageResult(
                    "cst_validation", TaskStatus.WARNING,
                    (Diagnostic("CST_VALIDATION_SKIPPED", message, DiagnosticSeverity.WARNING),),
                    summary={"required": False, "skipped": True},
                ))
            else:
                try:
                    cst_refs = self._cst_refs(inputs, spec)
                    cst_request = CSTTaskRequest(
                        task_id=task_manifest.task_id,
                        operation=spec.operation,
                        task_config={"arguments": dict(spec.arguments)},
                        input_artifacts=cst_refs,
                        parameters=dict(spec.parameters),
                        metadata={**dict(task_manifest.metadata), "pipeline_task_id": task_manifest.task_id,
                                  "stage": "cst_validation"},
                    )
                    cst_outcome = self.cst_adapter.execute(cst_request)
                except (ImportError, ModuleNotFoundError) as exc:
                    message = f"CST dependency unavailable: {type(exc).__name__}: {exc}"
                    diagnostic = Diagnostic("CST_DEPENDENCY_UNAVAILABLE", message, DiagnosticSeverity.ERROR)
                    if spec.required:
                        stages.append(PipelineStageResult("cst_validation", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
                        return self._finish(task_manifest, TaskStatus.UNAVAILABLE, history, stages, inputs, error=message)
                    stages.append(PipelineStageResult(
                        "cst_validation", TaskStatus.WARNING,
                        (Diagnostic("CST_VALIDATION_SKIPPED", message, DiagnosticSeverity.WARNING),),
                        summary={"required": False, "skipped": True},
                    ))
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    diagnostic = Diagnostic("CST_VALIDATION_SETUP_FAILED", message, DiagnosticSeverity.ERROR)
                    stages.append(PipelineStageResult("cst_validation", TaskStatus.FAILED, (diagnostic,), error=message))
                    return self._finish(task_manifest, TaskStatus.FAILED, history, stages, inputs, error=message)

                if cst_outcome is not None:
                    cst_status = cst_outcome.status
                    if self._unavailable(cst_status, cst_outcome.diagnostics):
                        cst_status = TaskStatus.UNAVAILABLE
                    if cst_status == TaskStatus.UNAVAILABLE and not spec.required:
                        stages.append(PipelineStageResult(
                            "cst_validation", TaskStatus.WARNING,
                            (Diagnostic(
                                "CST_VALIDATION_SKIPPED",
                                cst_outcome.error or "Optional CST validation is unavailable.",
                                DiagnosticSeverity.WARNING,
                            ),),
                            summary=dict(cst_outcome.structured_result),
                        ))
                    else:
                        stages.append(PipelineStageResult(
                            "cst_validation", cst_status, tuple(cst_outcome.diagnostics),
                            summary=dict(cst_outcome.structured_result), error=cst_outcome.error,
                        ))
                        if cst_status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE}:
                            return self._finish(
                                task_manifest, cst_status, history, stages, inputs,
                                cst=cst_outcome, error=cst_outcome.error,
                            )
                        if cst_status not in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}:
                            message = f"CST stage ended in non-terminal status {cst_status.value!r}."
                            diagnostic = Diagnostic("CST_STAGE_NOT_TERMINAL", message, DiagnosticSeverity.ERROR)
                            stages.append(PipelineStageResult("cst_validation", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
                            return self._finish(
                                task_manifest, TaskStatus.UNAVAILABLE, history, stages, inputs,
                                cst=cst_outcome, error=message,
                            )

        request = AnalysisRequest(
            task_id=task_manifest.task_id,
            operation=task_manifest.operation,
            input_artifacts=inputs,
            analysis_task={
                "operation_id": task_manifest.operation,
                "question": task_manifest.metadata.get("question", "CP2K output post-processing and provenance"),
                "workflow": "dft.postprocess.v1",
            },
            parameters=dict(task_manifest.parameters),
            structure_metadata=dict(task_manifest.structure_metadata),
            metadata={
                **dict(task_manifest.metadata),
                "pipeline_task_id": task_manifest.task_id,
                "project_root": str(task_manifest.project_root),
            },
        )
        try:
            analysis = self.data_analysis_adapter.analyze(request)
        except (ImportError, ModuleNotFoundError) as exc:
            message = f"Data_analysis dependency unavailable: {type(exc).__name__}: {exc}"
            diagnostic = Diagnostic("DATA_ANALYSIS_DEPENDENCY_UNAVAILABLE", message, DiagnosticSeverity.ERROR)
            stages.append(PipelineStageResult("data_analysis", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
            return self._finish(task_manifest, TaskStatus.UNAVAILABLE, history, stages, inputs, cst=cst_outcome, error=message)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            diagnostic = Diagnostic("DATA_ANALYSIS_STAGE_FAILED", message, DiagnosticSeverity.ERROR)
            stages.append(PipelineStageResult("data_analysis", TaskStatus.FAILED, (diagnostic,), error=message))
            return self._finish(task_manifest, TaskStatus.FAILED, history, stages, inputs, cst=cst_outcome, error=message)

        analysis_status = analysis.status
        if self._unavailable(analysis_status, analysis.diagnostics):
            analysis_status = TaskStatus.UNAVAILABLE
        stages.append(PipelineStageResult(
            "data_analysis", analysis_status, tuple(analysis.diagnostics),
            summary={
                "analysis_run_id": analysis.analysis_run_id,
                "output_artifact_ids": [x.artifact_id for x in analysis.output_artifacts],
                "evidence_package_id": (
                    analysis.evidence_package.get("evidence_package_id") if analysis.evidence_package else None
                ),
                "qc_status": analysis.qc_status,
            },
            error=analysis.error,
        ))
        if analysis_status in {TaskStatus.FAILED, TaskStatus.UNAVAILABLE}:
            return self._finish(
                task_manifest, analysis_status, history, stages, inputs,
                cst=cst_outcome, analysis=analysis, error=analysis.error,
            )
        if analysis_status not in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}:
            message = f"Data_analysis stage ended in non-terminal status {analysis_status.value!r}."
            diagnostic = Diagnostic("DATA_ANALYSIS_STAGE_NOT_TERMINAL", message, DiagnosticSeverity.ERROR)
            stages.append(PipelineStageResult("data_analysis", TaskStatus.UNAVAILABLE, (diagnostic,), error=message))
            return self._finish(
                task_manifest, TaskStatus.UNAVAILABLE, history, stages, inputs,
                cst=cst_outcome, analysis=analysis, error=message,
            )

        missing = []
        if analysis_status == TaskStatus.SUCCEEDED:
            if not analysis.analysis_run_id:
                missing.append("Analysis Run ID")
            if not analysis.output_artifacts:
                missing.append("registered output Artifact")
            if not analysis.evidence_refs:
                missing.append("Evidence reference")
            if not analysis.evidence_package:
                missing.append("Evidence Package")
        if missing:
            message = "Pipeline result is incomplete: missing " + ", ".join(missing)
            diagnostic = Diagnostic("PIPELINE_RESULT_INCOMPLETE", message, DiagnosticSeverity.WARNING)
            stages.append(PipelineStageResult(
                "result_integrity", TaskStatus.WARNING, (diagnostic,), summary={"missing": missing}
            ))

        warning = (
            analysis_status == TaskStatus.WARNING
            or (cst_outcome is not None and cst_outcome.status == TaskStatus.WARNING)
            or bool(missing)
            or any(stage.status == TaskStatus.WARNING for stage in stages)
        )
        final_status = TaskStatus.WARNING if warning else TaskStatus.SUCCEEDED
        extra = ()
        if analysis.qc_status in {"not_assessed", "not_evaluated"}:
            extra = (Diagnostic(
                "SCIENTIFIC_QC_NOT_ASSESSED",
                "Post-processing/provenance completed; scientific QC was not performed.",
                DiagnosticSeverity.INFO,
            ),)
        return self._finish(
            task_manifest, final_status, history, stages, inputs,
            cst=cst_outcome, analysis=analysis, extra=extra,
        )
