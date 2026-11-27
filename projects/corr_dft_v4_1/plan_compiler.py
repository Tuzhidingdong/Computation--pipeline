"""v4.1-specific Frozen DOCX compiler layered over the generic evidence compiler."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from pipeline_contracts.plan_compiler import CompilationResult, compile_docx
from .plan_rules import apply_v41_audit, load_v41_profile


def compile_v41_docx(docx_path: str | Path, *, plan_version: str | None = None) -> CompilationResult:
    base = compile_docx(docx_path, project_id="corr_dft_v4_1", plan_version=plan_version)
    manifest = dict(base.manifest)
    profile = load_v41_profile()
    manifest["project"]["profile_version"] = profile["schema_version"]
    manifest["systems"] = [{"system_id": key, **value} for key, value in profile["systems"].items()]
    manifest["method"] = dict(profile["method"])
    manifest["tasks"] = [{"work_package": key, **value} for key, value in profile["tasks"].items()]
    manifest["scientific_constraints"] = [
        {"constraint_id": key, "value": value} for key, value in profile["scientific_scope"].items()
    ]
    manifest["project_profile"] = {
        "profile_file": "projects/corr_dft_v4_1/project_profile.json",
        "topology_requirements": dict(profile["topology_requirements"]),
    }
    manifest = apply_v41_audit(manifest)
    diagnostics = tuple(manifest["diagnostics"])
    return CompilationResult(manifest, None, diagnostics)
