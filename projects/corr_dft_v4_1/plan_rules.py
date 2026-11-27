"""v4.1-only planning reconciliation rules; never imported by generic Pipeline core."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import json

_PROFILE = Path(__file__).with_name("project_profile.json")


def load_v41_profile(path: str | Path = _PROFILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _confirmed(manifest: Mapping[str, Any], key: str, accepted: set[str]) -> bool:
    value = (manifest.get("confirmed_resolutions") or {}).get(key)
    return isinstance(value, str) and value in accepted


def audit_v41_plan(manifest: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> list[dict]:
    """Return blockers for known v4.1 ambiguities without selecting a scientific value."""
    profile = dict(profile or load_v41_profile())
    diagnostics = []
    wp1 = profile["tasks"]["WP1"]
    if not _confirmed(manifest, "wp1_orientation_scope", {"per_catalyst", "across_both_systems"}):
        diagnostics.append({
            "code": "WP1_ORIENTATION_SCOPE_UNRESOLVED", "severity": "error",
            "field": "tasks.WP1.orientation_scope",
            "message": "The 15 docking orientations are not scoped as per catalyst or across both systems.",
            "candidate_values": ["per_catalyst", "across_both_systems"],
            "evidence": [{"source": "TASK_PLAN_v1.0.0.md", "section": "2.3 / WP1"}],
            "blocks_execution": True,
        })
    detailed = int(wp1["isolated_fragment_spin_candidate_count"])
    summary = int(wp1["summary_fragment_single_point_count"])
    if detailed != summary and not _confirmed(
        manifest, "wp1_fragment_spin_count_resolution", {"preserve_detailed_six_correct_summary"}
    ):
        diagnostics.append({
            "code": "WP1_FRAGMENT_SPIN_COUNT_MISMATCH", "severity": "error",
            "field": "tasks.WP1.isolated_fragment_spin_candidate_count",
            "message": (
                f"The explicit isolated-fragment spin list contains {detailed} candidates, "
                f"but the WP1 summary states {summary} fragment single points. No candidate was omitted."
            ),
            "detailed_list_count": detailed, "summary_count": summary,
            "evidence": [{"source": "TASK_PLAN_v1.0.0.md", "section": "2.3 / WP1"},
                         {"source": "TASK_PLAN_v1.0.0.md", "section": "2.4 / planning checks"}],
            "blocks_execution": True,
        })
    return diagnostics


def apply_v41_audit(manifest: Mapping[str, Any]) -> dict:
    result = dict(manifest)
    known_codes = {"WP1_ORIENTATION_SCOPE_UNRESOLVED", "WP1_FRAGMENT_SPIN_COUNT_MISMATCH"}
    diagnostics = [item for item in result.get("diagnostics", [])
                   if item.get("code") not in known_codes] + audit_v41_plan(result)
    result["diagnostics"] = diagnostics
    blocking = any(item.get("blocks_execution") for item in diagnostics)
    unresolved = bool(result.get("unresolved_definitions"))
    result["compilation_status"] = "BLOCKED" if blocking else (
        "NEEDS_REVIEW" if unresolved else "READY_FOR_APPROVAL"
    )
    return result


def confirm_v41_resolutions(manifest: Mapping[str, Any], *, orientation_scope: str,
                            fragment_spin_resolution: str, confirmed_by: str,
                            rationale: str) -> dict:
    if orientation_scope not in {"per_catalyst", "across_both_systems"}:
        raise ValueError("orientation_scope must be per_catalyst or across_both_systems")
    if fragment_spin_resolution != "preserve_detailed_six_correct_summary":
        raise ValueError("fragment spin resolution must preserve all six detailed candidates and correct the summary")
    if not confirmed_by.strip() or not rationale.strip():
        raise ValueError("confirmed_by and rationale are required")
    result = dict(manifest)
    result["confirmed_resolutions"] = {
        "wp1_orientation_scope": orientation_scope,
        "wp1_fragment_spin_count_resolution": fragment_spin_resolution,
    }
    result.setdefault("project_decision_records", []).append({
        "confirmed_by": confirmed_by, "rationale": rationale,
        "resolutions": dict(result["confirmed_resolutions"]),
    })
    return apply_v41_audit(result)
