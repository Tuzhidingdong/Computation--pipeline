"""Frozen DOCX -> Project Manifest -> existing CalculationPlan compiler."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json

from .docx_reader import read_frozen_docx
from .manifest import build_project_manifest
from ..calculation_plan import CalculationPlan, PlanValidationError


@dataclass(frozen=True)
class CompilationResult:
    manifest: Mapping[str, Any]
    calculation_plan: CalculationPlan | None
    diagnostics: tuple[Mapping[str, Any], ...]

    @property
    def executable(self) -> bool:
        return self.calculation_plan is not None and not any(
            item.get("blocks_execution") for item in self.diagnostics
        )


def compile_docx(
    docx_path: str | Path, *, project_id: str, plan_version: str | None = None,
) -> CompilationResult:
    blocks = read_frozen_docx(docx_path)
    manifest = build_project_manifest(blocks, project_id=project_id, plan_version=plan_version)
    diagnostics = tuple(manifest["diagnostics"])
    return CompilationResult(manifest, None, diagnostics)


def compile_confirmed_manifest(
    manifest: Mapping[str, Any], calculation_plan_data: Mapping[str, Any],
) -> CalculationPlan:
    """Convert only an explicitly confirmed manifest to the established plan model.

    The model Artifact must already be registered and approved. Pre-model inputs belong
    to the project lifecycle DAG, not to a fabricated CalculationPlan structure.path.
    """
    blocking = [d for d in manifest.get("diagnostics", []) if d.get("blocks_execution")]
    unresolved = manifest.get("unresolved_definitions", [])
    if blocking:
        raise PlanValidationError([
            f"{d.get('code')}: {d.get('message')}" for d in blocking
        ])
    if unresolved:
        raise PlanValidationError([
            "Manifest contains unconfirmed scientific definitions; confirm them before "
            "CalculationPlan conversion."
        ])
    plan = CalculationPlan.from_mapping(calculation_plan_data)
    plan.require_valid()
    structure = plan.structure
    if not (structure.get("artifact_id") and structure.get("sha256")):
        raise PlanValidationError([
            "Approved model Artifact ID and SHA-256 are required before formal CalculationPlan creation."
        ])
    return plan


def write_manifest(result: CompilationResult, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(result.manifest), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target
