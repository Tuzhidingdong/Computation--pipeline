"""v4.1-only planning reconciliation rules; never imported by generic Pipeline core."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

_PROFILE = Path(__file__).with_name("project_profile.json")
_LEGACY_SIX_RESOLUTION = "preserve_detailed_six_correct_summary"


def load_v41_profile(path: str | Path = _PROFILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _confirmed(manifest: Mapping[str, Any], key: str, accepted: set[str]) -> bool:
    value = (manifest.get("confirmed_resolutions") or {}).get(key)
    return isinstance(value, str) and value in accepted


def _spin_candidate_ids(profile: Mapping[str, Any]) -> list[str]:
    spins = profile["tasks"]["WP1"]["isolated_fragment_spin_candidates"]
    return [f"{fragment}:M{int(multiplicity)}"
            for fragment, values in spins.items() for multiplicity in values]


def _spin_resolution_valid(resolutions: Mapping[str, Any], candidate_ids: list[str]) -> bool:
    mode = resolutions.get("wp1_fragment_spin_count_resolution")
    selected = resolutions.get("wp1_selected_fragment_spin_candidates")
    if mode in {"retain_all_six", _LEGACY_SIX_RESOLUTION}:
        return isinstance(selected, list) and selected == candidate_ids
    if mode == "select_four_explicitly":
        return (
            isinstance(selected, list) and len(selected) == 4
            and len(set(selected)) == 4 and set(selected).issubset(candidate_ids)
        )
    return False


def audit_v41_plan(manifest: Mapping[str, Any], profile: Mapping[str, Any] | None = None) -> list[dict]:
    """Return blockers without selecting the orientation count or fragment-spin scope."""
    profile = dict(profile or load_v41_profile())
    diagnostics = []
    wp1 = profile["tasks"]["WP1"]
    if not _confirmed(manifest, "wp1_orientation_scope", {"per_catalyst", "across_both_systems"}):
        diagnostics.append({
            "code": "WP1_ORIENTATION_SCOPE_UNRESOLVED", "severity": "error",
            "field": "tasks.WP1.orientation_scope",
            "message": "The 15 docking orientations are not scoped as per catalyst or across both systems.",
            "candidate_values": ["per_catalyst", "across_both_systems"],
            "evidence": [{"source": "projects/corr_dft_v4_1/project_profile.json",
                          "field": "tasks.WP1.support_cluster_docking_orientation_count"}],
            "blocks_execution": True,
        })

    detailed = int(wp1["isolated_fragment_spin_candidate_count"])
    summary = int(wp1["summary_fragment_single_point_count"])
    candidate_ids = _spin_candidate_ids(profile)
    resolutions = manifest.get("confirmed_resolutions") or {}
    if detailed != summary and not _spin_resolution_valid(resolutions, candidate_ids):
        diagnostics.append({
            "code": "WP1_FRAGMENT_SPIN_COUNT_MISMATCH", "severity": "error",
            "field": "tasks.WP1.isolated_fragment_spin_candidate_count",
            "message": (
                f"The explicit isolated-fragment spin list contains {detailed} candidates, "
                f"but the WP1 summary states {summary}. An owner must either retain all detailed "
                "candidates or identify exactly four selected candidates; no candidate is inferred."
            ),
            "detailed_list_count": detailed, "summary_count": summary,
            "candidate_ids": candidate_ids,
            "allowed_resolutions": ["retain_all_six", "select_four_explicitly"],
            "evidence": [{"source": "projects/corr_dft_v4_1/project_profile.json",
                          "field": "tasks.WP1.isolated_fragment_spin_candidates"},
                         {"source": "projects/corr_dft_v4_1/project_profile.json",
                          "field": "tasks.WP1.summary_fragment_single_point_count"}],
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


def confirm_v41_resolutions(
    manifest: Mapping[str, Any], *, orientation_scope: str,
    fragment_spin_resolution: str, confirmed_by: str, rationale: str,
    selected_fragment_spin_candidates: Sequence[str] | None = None,
) -> dict:
    if orientation_scope not in {"per_catalyst", "across_both_systems"}:
        raise ValueError("orientation_scope must be per_catalyst or across_both_systems")
    if not confirmed_by.strip() or not rationale.strip():
        raise ValueError("confirmed_by and rationale are required")

    candidate_ids = _spin_candidate_ids(load_v41_profile())
    if fragment_spin_resolution == "retain_all_six":
        selected = candidate_ids
    elif fragment_spin_resolution == "select_four_explicitly":
        selected = list(selected_fragment_spin_candidates or [])
        if len(selected) != 4 or len(set(selected)) != 4 or not set(selected).issubset(candidate_ids):
            raise ValueError(
                "select_four_explicitly requires exactly four unique candidate IDs from the detailed six"
            )
    else:
        raise ValueError(
            "fragment_spin_resolution must be retain_all_six or select_four_explicitly"
        )

    result = dict(manifest)
    result["confirmed_resolutions"] = {
        "wp1_orientation_scope": orientation_scope,
        "wp1_fragment_spin_count_resolution": fragment_spin_resolution,
        "wp1_selected_fragment_spin_candidates": selected,
    }
    result.setdefault("project_decision_records", []).append({
        "confirmed_by": confirmed_by, "rationale": rationale,
        "resolutions": dict(result["confirmed_resolutions"]),
    })
    return apply_v41_audit(result)
