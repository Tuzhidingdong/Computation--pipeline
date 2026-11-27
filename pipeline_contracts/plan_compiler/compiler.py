"""Frozen DOCX -> Project Manifest -> existing CalculationPlan compiler."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json
import hashlib
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


def compile_docx(docx_path: str | Path, *, project_id: str,
                 plan_version: str | None = None) -> CompilationResult:
    source = Path(docx_path)
    source_bytes = source.read_bytes()
    blocks = read_frozen_docx(source)
    manifest = build_project_manifest(blocks, project_id=project_id, plan_version=plan_version)
    manifest["source_document"] = {
        "file_name": source.name,
        "size_bytes": len(source_bytes),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "parser": "pipeline_contracts.plan_compiler.docx_reader",
    }
    return CompilationResult(manifest, None, tuple(manifest["diagnostics"]))


def confirm_manifest_claims(manifest: Mapping[str, Any], *, evidence_ids: list[str],
                             confirmer: str, rationale: str) -> dict:
    """Record explicit owner confirmation without changing or deleting source evidence."""
    if not confirmer.strip() or not rationale.strip() or not evidence_ids:
        raise ValueError("confirmer, rationale and at least one evidence_id are required")
    result = dict(manifest)
    claims = [dict(item) for item in result.get("claims", [])]
    selected = set(evidence_ids)
    matched = set()
    for claim in claims:
        claim_evidence_ids = set(claim.get("evidence_ids") or [claim.get("evidence_id")])
        claim_evidence_ids.discard(None)
        matched_evidence_ids = claim_evidence_ids & selected
        if claim.get("status") == "requires_confirmation" and matched_evidence_ids:
            claim["status"] = "user_confirmed"
            claim["confirmation"] = {"confirmed_by": confirmer, "rationale": rationale}
            matched.update(matched_evidence_ids)
    missing = selected - matched
    if missing:
        raise ValueError("no unconfirmed labelled claims for evidence IDs: " + ", ".join(sorted(missing)))
    result["claims"] = claims
    result["unresolved_definitions"] = [
        item for item in result.get("unresolved_definitions", [])
        if not (set(item.get("evidence_ids") or [item.get("evidence_id")]) & selected)
    ]
    result.setdefault("confirmations", []).append({
        "evidence_ids": sorted(selected), "confirmed_by": confirmer, "rationale": rationale,
    })
    return result


def compile_confirmed_manifest(manifest: Mapping[str, Any],
                               calculation_plan_data: Mapping[str, Any]) -> CalculationPlan:
    """Convert only a confirmed Manifest after model Artifact approval."""
    blocking = [d for d in manifest.get("diagnostics", []) if d.get("blocks_execution")]
    unresolved = manifest.get("unresolved_definitions", [])
    if blocking:
        raise PlanValidationError([f"{d.get('code')}: {d.get('message')}" for d in blocking])
    if unresolved:
        raise PlanValidationError([
            "Manifest contains unconfirmed scientific definitions; confirm them before CalculationPlan conversion."
        ])
    plan = CalculationPlan.from_mapping(calculation_plan_data)
    plan.require_valid()
    structure = plan.structure
    if not (structure.get("artifact_id") and structure.get("sha256")):
        raise PlanValidationError([
            "Approved model Artifact ID and SHA-256 are required before formal CalculationPlan creation."
        ])
    return plan


def write_manifest(result: CompilationResult | Mapping[str, Any], path: str | Path) -> Path:
    manifest = result.manifest if isinstance(result, CompilationResult) else result
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target
