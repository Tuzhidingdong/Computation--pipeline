"""Fail-closed decision status aggregation shared by planning compilers."""
from __future__ import annotations

from typing import Any, Iterable, Mapping


def evidence_gap(
    code: str, field_path: str, why_decisive: str, minimum_question: str,
    related_evidence_refs: Iterable[Mapping[str, Any]] | None = None,
) -> dict:
    item = {
        "code": str(code),
        "field_path": str(field_path),
        "why_decisive": str(why_decisive),
        "minimum_question": str(minimum_question),
    }
    refs = list(related_evidence_refs or [])
    if refs:
        item["related_evidence_refs"] = refs
    return item


def decision_for_gap(gap: Mapping[str, Any], refs: Iterable[Mapping[str, Any]] | None = None) -> dict:
    field_path = str(gap.get("field_path") or "unknown")
    question = str(gap.get("minimum_question") or "Resolve the missing decision.")
    return {
        "decision_id": "decision-" + str(gap.get("code") or "missing").lower().replace("_", "-"),
        "subject": field_path,
        "selection_mode": "C_MISSING_DECISIVE_INFORMATION",
        "status": "BLOCKED",
        "selected_value": None,
        "source_evidence_refs": list(refs or gap.get("related_evidence_refs") or []),
        "policy_ref": None,
        "applicable_scope": "current Project Run",
        "candidates": [],
        "excluded_candidates": [],
        "assumptions": [],
        "uncertainties": [str(gap.get("why_decisive") or "Decisive information is missing.")],
        "requires_user_approval": False,
        "approval_ref": None,
        "missing_information": [field_path],
        "minimum_questions": [{
            "question_id": str(gap.get("code") or "missing-decision"),
            "question": question,
            "field_path": field_path,
            "answer_type": "explicit_source_or_user_decision",
        }],
    }


def aggregate_status(*statuses: str, has_gaps: bool = False, has_proposals: bool = False) -> str:
    values = {str(item or "").upper() for item in statuses}
    if has_gaps or "BLOCKED" in values:
        return "BLOCKED"
    if "UNSUPPORTED" in values:
        return "UNSUPPORTED"
    if "PLANNABLE_ONLY" in values:
        return "PLANNABLE_ONLY"
    if has_proposals or "NEEDS_DECISION" in values:
        return "NEEDS_DECISION"
    if any(value not in {"READY", "READY_FOR_REVIEW", "READY_FOR_MODEL_AND_METHOD_PLANNING",
                         "READY_FOR_RESEARCH_PLANNING", "APPROVED", "FROZEN"}
           for value in values):
        return "BLOCKED"
    return "READY"


__all__ = ["evidence_gap", "decision_for_gap", "aggregate_status"]
