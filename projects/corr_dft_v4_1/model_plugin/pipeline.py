"""v4.1 model-generation, validation, review and approval orchestration."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import json

from .spec import ModelSpec
from .builder import build_candidates
from .validation import validate_candidate
from .artifacts import register_candidate_package
from .review import build_review_package
from .approval import create_approval_record


def generate_validate_review(
    model_specs: Sequence[Mapping[str, Any]], output_dir: str | Path, *,
    lifecycle, project_run_id: str, data_analysis_api,
    format_ids: Mapping[str, str], parent_artifact_ids: list[str],
    pseudopotential_valence_by_model: Mapping[str, Mapping[str, int]],
    structure_writer=None, validator: Callable = validate_candidate,
    preview_renderer=None,
) -> dict:
    """Run candidate generation through review and stop at the user approval gate.

    Model specs must contain the complete explicit graph and deterministic transforms.
    The function never creates placeholder coordinates or silently reduces candidates.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    lifecycle.transition(project_run_id, "MODEL_GENERATE", "RUNNING")
    generated = []
    try:
        for raw_spec in model_specs:
            spec = ModelSpec.from_mapping(raw_spec)
            candidates = build_candidates(
                spec, root / spec.model_id, writer=structure_writer,
            )
            for candidate in candidates:
                generated.append((spec, candidate))
        lifecycle.transition(project_run_id, "MODEL_GENERATE", "COMPLETED",
                             outputs={"candidate_ids": [c.candidate_id for _, c in generated]})
    except Exception as exc:
        lifecycle.transition(project_run_id, "MODEL_GENERATE", "FAILED", error=str(exc))
        raise

    lifecycle.transition(project_run_id, "MODEL_VALIDATE", "RUNNING")
    review_entries = []
    registrations = {}
    try:
        for spec, candidate in generated:
            valence = pseudopotential_valence_by_model.get(spec.model_id)
            if not valence:
                raise ValueError(f"{spec.model_id}: explicit CP2K pseudopotential valence map is required")
            report = validator(candidate.structure_path, candidate.topology_path, spec.expected,
                               pseudopotential_valence=valence)
            if report.get("status") != "PASS":
                lifecycle.transition(project_run_id, "MODEL_VALIDATE", "BLOCKED",
                                     outputs={"candidate_id": candidate.candidate_id,
                                              "validation_report": dict(report)},
                                     error="candidate validation failed")
                return {"status": "BLOCKED", "candidate_results": review_entries}
            package = register_candidate_package(
                candidate, report, project_root=root, data_analysis_api=data_analysis_api,
                format_ids=format_ids, parent_artifact_ids=parent_artifact_ids,
            )
            registrations[candidate.candidate_id] = package
            coordination = [dict(bond) for bond in spec.bonds if bond.get("kind") == "coordination"]
            review_entries.append({
                "candidate_id": candidate.candidate_id,
                "validation_report": dict(report),
                "artifact": package["structure_artifact"],
                "coordination": coordination, "differences": [],
                "structure_path": str(candidate.structure_path),
                "topology_path": str(candidate.topology_path),
                "metadata_path": str(candidate.metadata_path),
            })
        lifecycle.transition(project_run_id, "MODEL_VALIDATE", "COMPLETED",
                             outputs={"registered_candidate_ids": list(registrations)})
    except Exception as exc:
        lifecycle.transition(project_run_id, "MODEL_VALIDATE", "FAILED", error=str(exc))
        raise

    lifecycle.transition(project_run_id, "MODEL_REVIEW", "RUNNING")
    review_path = build_review_package(review_entries, root / "review",
                                       preview_renderer=preview_renderer)
    review_package = json.loads(review_path.read_text(encoding="utf-8"))
    if review_package["review_status"] != "AWAITING_USER_REVIEW":
        lifecycle.transition(project_run_id, "MODEL_REVIEW", "BLOCKED",
                             outputs={"review_package": str(review_path),
                                      "review_status": review_package["review_status"]},
                             error="3D preview missing for one or more candidates")
        return {"status": "BLOCKED", "review_package": str(review_path),
                "candidate_results": review_entries, "registrations": registrations}
    lifecycle.transition(project_run_id, "MODEL_REVIEW", "COMPLETED",
                         outputs={"review_package": str(review_path),
                                  "candidate_count": len(review_entries)})
    lifecycle.transition(project_run_id, "MODEL_APPROVAL", "AWAITING_APPROVAL",
                         outputs={"candidate_ids": list(registrations)})
    return {"status": "AWAITING_APPROVAL", "review_package": str(review_path),
            "candidate_results": review_entries, "registrations": registrations}


def approve_candidate(
    pipeline_result: Mapping[str, Any], candidate_id: str, *, approver: str,
    approval_record_path: str | Path, lifecycle, project_run_id: str,
    approved: bool,
) -> dict:
    if pipeline_result.get("status") != "AWAITING_APPROVAL":
        raise ValueError("candidate review package is not ready for user approval")
    candidate = next((item for item in pipeline_result["candidate_results"]
                      if item["candidate_id"] == candidate_id), None)
    if candidate is None:
        raise KeyError(f"unknown candidate_id: {candidate_id}")
    artifact_ref = pipeline_result["registrations"][candidate_id]["structure_artifact"]
    record = create_approval_record(
        approval_record_path, approver=approver, candidate_id=candidate_id,
        artifact_ref=artifact_ref, structure_path=candidate["structure_path"],
        validation_report=candidate["validation_report"], approved=approved,
    )
    lifecycle.freeze_approval(project_run_id, record)
    return record
