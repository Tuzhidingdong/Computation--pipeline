"""Compile a deterministic ResearchPlan DAG without inventing scientific tasks."""
from __future__ import annotations
from typing import Any, Mapping

from .bundle import seal_object
from .contracts import PLANNING_SCHEMA_VERSION
from .decision_policy import decision_for_gap, evidence_gap
from .intent_compiler import _provenance


def build_research_plan(intent: Mapping[str, Any], gaps: list[dict],
                        dependencies: Mapping[str, list[str]] | None = None,
                        approved_decisions: list[dict] | None = None,
                        source_resolutions: list[dict] | None = None) -> dict:
    families = list(intent.get("requested_task_families") or [])
    observables = list(intent.get("requested_observables") or [])
    refs = intent.get("source_evidence_refs", [])
    effective_gaps = list(gaps)
    if not observables:
        effective_gaps.append(evidence_gap("RESEARCH_OBJECTIVE_MISSING", "research_plan.objectives",
            "A ResearchPlan requires at least one explicit success observable.",
            "Declare the requested observable(s).", refs))
        objective_values = ["UNRESOLVED: success observable required"]
    else:
        objective_values = observables
    objectives = [{
        "objective_id": f"OBJ-{index + 1:02d}",
        "statement": f"Evaluate the declared observable: {value}.",
        "success_observable": value,
        "source_evidence_refs": refs,
    } for index, value in enumerate(objective_values)]
    if not families:
        effective_gaps.append(evidence_gap("RESEARCH_TASK_MISSING", "research_plan.work_packages",
            "A ResearchPlan requires at least one selected task family.",
            "Select the task family that answers this research question.", refs))
        families = ["UNRESOLVED"]
    work_packages = []
    dependency_map = dependencies or {}
    for index, family in enumerate(families):
        package_id = f"WP-{index + 1:02d}"
        # A DAG edge is included only when the Project Profile names it.
        # List order alone is not scientific evidence of task dependency.
        work_packages.append({
            "work_package_id": package_id, "question_ids": [],
            "task_family": str(family),
            "purpose": f"Address the requested task family {family}.",
            "depends_on": list(dependency_map.get(family, [])),
            "required_inputs": ["approved_model_artifact"],
            "expected_outputs": list(objective_values),
            "status": "BLOCKED" if effective_gaps else "PROPOSED",
            "evidence_refs": refs,
        })
    decisions = [decision_for_gap(item, item.get("related_evidence_refs", [])) for item in effective_gaps]
    approved_records = [dict(item) for item in (approved_decisions or [])]
    source_records = []
    for source in source_resolutions or []:
        field_path = str(source.get("field_path") or "")
        issue_id = str(source.get("issue_id") or "")
        if not field_path or not issue_id:
            raise ValueError("source resolutions require issue_id and field_path")
        evidence_refs = list(source.get("source_evidence_refs") or [])
        source_records.append({
            "decision_id": "source-resolution-" + issue_id,
            "subject": field_path,
            "selection_mode": "A_EVIDENCE_OR_APPROVED_FACT",
            "status": "SELECTED_FROM_EVIDENCE",
            "selected_value": source.get("value"),
            "source_evidence_refs": evidence_refs,
            "policy_ref": None,
            "applicable_scope": "Frozen DOCX source for this Project Run",
            "candidates": [{"candidate_id": "unique-source-value", "value": source.get("value"),
                            "evidence_refs": evidence_refs,
                            "compatibility_status": "UNIQUE_HASH_PINNED_SOURCE_CLAIM"}],
            "excluded_candidates": [], "assumptions": [], "uncertainties": [],
            "requires_user_approval": False, "approval_ref": None,
            "missing_information": [], "minimum_questions": [],
        })
    body = {
        "schema_version": PLANNING_SCHEMA_VERSION, "plan_id": "",
        "intent_ref": {
            "object_type": "ScientificIntent", "object_id": intent["intent_id"],
            "schema_version": intent["schema_version"],
            "sha256": intent["planning_metadata"]["object_sha256"],
        },
        "intent_sha256": intent["planning_metadata"]["object_sha256"],
        "objectives": objectives, "work_packages": work_packages,
        "decision_records": decisions + source_records + approved_records, "evidence_gaps": effective_gaps,
        "assumptions": [],
        "status": "BLOCKED" if effective_gaps else "READY_FOR_MODEL_AND_METHOD_PLANNING",
        "provenance": _provenance(refs, intent["planning_metadata"]["object_sha256"],
                                  "pipeline.research_planner"),
    }
    return seal_object(body, object_type="ResearchPlan", id_field="plan_id", prefix="research",
        status="BLOCKED" if effective_gaps else "READY",
        source_evidence_refs=refs,
        upstream_sha256s={"scientific_intent": intent["planning_metadata"]["object_sha256"]},
        selection_records=decisions + source_records + approved_records, missing_items=effective_gaps)
