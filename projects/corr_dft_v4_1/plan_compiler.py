"""v4.1 Frozen DOCX compiler with an isolated, provenance-labelled profile overlay."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from pipeline_contracts.plan_compiler import CompilationResult, compile_docx
from pipeline_contracts.plan_compiler.manifest import _normalise_field_value, _normalise_label
from .plan_rules import apply_v41_audit, load_v41_profile


_PROFILE_REL_PATH = "projects/corr_dft_v4_1/project_profile.json"


def _flatten_profile(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _flatten_profile(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from _flatten_profile(child, child_path)
    else:
        yield path, value


def _aliases(profile_path: str) -> set[str]:
    leaf = _normalise_label(profile_path.rsplit(".", 1)[-1].split("[", 1)[0])
    aliases = {leaf}
    explicit = {
        "cutoff_ry": {"cutoff"},
        "rel_cutoff_ry": {"rel_cutoff"},
        "xc": {"functional", "exchange_correlation", "xc_functional"},
        "complete_formula": {"formula"},
        "complete_atom_count": {"atom_count", "number_of_atoms"},
        "support_motif": {"motif"},
        "support_atom_count": {"atom_count", "number_of_atoms"},
        "cluster": {"cluster_formula", "cluster_atom_count"},
        "geometry_optimization": {"eps_scf_geometry_optimization"},
        "local_hessian_force": {"eps_scf_local_hessian_force"},
        "temperature_k": {"che_temperature_k"},
        "potential_v_vs_rhe": {"potential_v_vs_rhe"},
        "support_cluster_docking_orientation_count": {
            "orientation_count", "docking_orientations", "orientations",
            "docking_orientation_count", "number_of_docking_orientations",
            "number_of_orientations",
        },
        "isolated_fragment_spin_candidate_count": {
            "spin_candidate_count", "spin_candidate", "fragment_spin_count",
            "number_of_isolated_fragment_spin_candidates",
        },
        "summary_fragment_single_point_count": {
            "single_point_count", "summary_count",
        },
    }
    aliases.update(explicit.get(leaf, set()))
    return aliases


def _matching_docx_claims(manifest: dict, profile_path: str) -> list[dict]:
    parts = profile_path.split(".")
    aliases = _aliases(profile_path)
    if not parts:
        return []
    scope = parts[0]
    system_id = parts[1] if scope == "systems" and len(parts) > 2 else None
    work_package = parts[1] if scope == "tasks" and len(parts) > 2 else None
    matches = []
    for claim in manifest.get("claims", []):
        field = _normalise_label(str(claim.get("field") or ""))
        if field not in aliases:
            continue
        context = claim.get("context") or {}
        if system_id and str(context.get("system_id") or "").casefold() != system_id.casefold():
            continue
        if work_package and str(context.get("work_package") or "").casefold() != work_package.casefold():
            continue
        if scope == "method" and context.get("work_package") and field not in aliases:
            continue
        matches.append(claim)
    return matches


def _compare_profile_value(profile_value: Any, docx_value: str, profile_path: str) -> str:
    profile_normalised = _normalise_field_value(profile_value)
    docx_normalised = _normalise_field_value(docx_value)
    if profile_normalised == docx_normalised:
        return "consistent"

    # A unit-bearing DOCX value may be compared with a unit-encoded profile key.
    # Do not strip units: they must agree with the field's declared unit suffix.
    import re
    from decimal import Decimal, InvalidOperation

    if isinstance(profile_value, list):
        if not profile_value or not all(isinstance(item, (int, float)) and not isinstance(item, bool)
                                        for item in profile_value):
            return "needs_review"
        raw = docx_value if isinstance(docx_value, (list, tuple)) else re.findall(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", str(docx_value)
        )
        try:
            actual = [Decimal(str(item)) for item in raw]
            expected = [Decimal(str(item)) for item in profile_value]
        except InvalidOperation:
            return "needs_review"
        return "consistent" if actual == expected else "conflict"
    if isinstance(profile_value, (dict, list)):
        return "needs_review"
    if isinstance(profile_value, bool):
        return "consistent" if str(docx_value).strip().casefold() in ({"true", ".true.", "yes"} if profile_value else {"false", ".false.", "no"}) else "conflict"
    if isinstance(profile_value, (int, float)):
        match = re.fullmatch(
            r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-zÅ/0-9^]+)?\s*",
            str(docx_value),
        )
        if match:
            try:
                same_number = Decimal(match.group(1)) == Decimal(str(profile_value))
            except InvalidOperation:
                return "needs_review"
            unit = (match.group(2) or "").casefold()
            key = profile_path.casefold()
            expected_units = {
                "_ry": {"ry"}, "_ha": {"ha", "hartree"}, "_ev": {"ev"},
                "_angstrom": {"å", "angstrom"}, "_ev_per_angstrom": {"ev/å", "ev/angstrom"},
                "_k": {"k"}, "_v_vs_rhe": {"v"},
            }
            expected = next((units for suffix, units in expected_units.items() if suffix in key), None)
            if same_number and expected is not None and unit in expected:
                return "consistent"
            if same_number and expected is None and not unit:
                return "consistent"
            if expected is not None and unit not in expected:
                return "needs_review" if same_number else "conflict"
            return "conflict" if not same_number else "needs_review"
    if profile_path.endswith("support_motif"):
        def canonical_motif(value: str) -> str:
            value = _normalise_field_value(value)
            return value.replace("]^0", "]0")
        return "consistent" if canonical_motif(str(profile_value)) == canonical_motif(str(docx_value)) else "conflict"
    if profile_path.endswith("basis_sensitivity"):
        left = _normalise_field_value(profile_value)
        right = _normalise_field_value(docx_value)
        return "consistent" if right.startswith(left) else "conflict"
    return "conflict"


def _profile_provenance(manifest: dict, profile: dict) -> tuple[dict, list[dict]]:
    field_provenance = {}
    reconciliation = []
    for path, value in _flatten_profile(profile):
        matches = _matching_docx_claims(manifest, path)
        evidence_ids = []
        for claim in matches:
            for evidence_id in claim.get("evidence_ids", [claim.get("evidence_id")]):
                if evidence_id and evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)

        parts = path.split(".")
        root_scope = parts[0] if parts else ""
        system_id = parts[1] if root_scope == "systems" and len(parts) > 2 else None
        work_package = parts[1] if root_scope == "tasks" and len(parts) > 2 else None
        aliases = _aliases(path)
        unresolved_matches = []
        for item in manifest.get("unresolved_structured_fields", []):
            item_field = str(item.get("field", ""))
            item_scope = item_field.split(".", 1)[0]
            if item_scope != root_scope:
                continue
            item_system = str(item.get("system_id") or "").casefold()
            item_wp = str(item.get("work_package") or "").casefold()
            if system_id and item_system and item_system != system_id.casefold():
                continue
            if work_package and item_wp and item_wp != work_package.casefold():
                continue
            profile_tail = ".".join(parts[2:]) if len(parts) > 2 else parts[-1]
            profile_tail = re.sub(r"\[\d+\]", "", profile_tail)
            item_tail = item_field.split(".", 1)[1] if "." in item_field else item_field
            field_match = item_tail == profile_tail or item_tail.endswith("." + profile_tail)
            source_text = _normalise_label(str(item.get("source_text", "")))
            if field_match or any(alias and alias in source_text for alias in aliases):
                unresolved_matches.append(item)
                for evidence_id in item.get("evidence_ids", []):
                    if evidence_id and evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)

        if not matches and unresolved_matches:
            docx_status = "unresolved"
            reconciliation_status = "needs_review"
        elif not matches:
            docx_status = "absent"
            reconciliation_status = "profile_only"
        else:
            docx_status = "docx_evidence"
            unique_docx_values = {
                _normalise_field_value(claim.get("value", "")) for claim in matches
            }
            if len(unique_docx_values) > 1:
                reconciliation_status = "conflict"
            else:
                comparisons = {
                    _compare_profile_value(value, str(claim.get("value", "")), path)
                    for claim in matches
                }
                reconciliation_status = (
                    "consistent" if comparisons == {"consistent"}
                    else "conflict" if "conflict" in comparisons
                    else "needs_review"
                )

        field_provenance[path] = {
            "status": "profile",
            "source_kind": "profile",
            "source_path": _PROFILE_REL_PATH,
            "profile_field": path,
            "evidence_ids": [],
            "reconciliation_status": reconciliation_status,
        }
        reconciliation.append({
            "field": path,
            "profile_value": value,
            "profile_source": _PROFILE_REL_PATH,
            "docx_status": docx_status,
            "docx_evidence_ids": evidence_ids,
            "docx_values": [claim.get("value") for claim in matches],
            "unresolved_docx_sources": [
                item.get("source_text", "") for item in unresolved_matches
            ],
            "status": reconciliation_status,
        })
    return field_provenance, reconciliation

def compile_v41_docx(docx_path: str | Path, *, plan_version: str | None = None) -> CompilationResult:
    base = compile_docx(docx_path, project_id="corr_dft_v4_1", plan_version=plan_version)
    manifest = dict(base.manifest)
    profile = load_v41_profile()

    manifest["project"]["profile_version"] = profile["schema_version"]
    # Keep DOCX extraction as the only source of the primary structured fields.
    # Profile values are available to the v4.1 rules, but are never merged into
    # systems/models/method/tasks or represented as DOCX evidence.
    manifest["profile_overlay"] = {
        "source_kind": "profile",
        "profile_source": _PROFILE_REL_PATH,
        "profile_version": profile["schema_version"],
        "values": profile,
    }
    profile_fields, reconciliation = _profile_provenance(manifest, profile)
    manifest["profile_field_provenance"] = profile_fields
    manifest["profile_reconciliation"] = reconciliation
    manifest = apply_v41_audit(manifest)
    diagnostics = tuple(manifest["diagnostics"])
    return CompilationResult(manifest, None, diagnostics)
