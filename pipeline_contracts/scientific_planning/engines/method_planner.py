"""Provenance-first MethodPlan mapping planner; deliberately no scientific defaults."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "cp2k": {
        "required": [
            "xc_functional", "dispersion", "basis_set", "pseudopotential",
            "basis_file_name", "potential_file_name", "kind_definitions",
            "cutoff_ry", "rel_cutoff_ry", "scf.method", "scf.eps_scf", "scf.max_scf",
            "charge", "multiplicity", "spin", "uks", "center_coordinates",
            "periodicity", "poisson_periodicity", "poisson_solver",
            "solvation.implicit", "solvation.explicit", "software_version",
        ],
        "optional": ["cell_periodicity"],
        "conditional": {"kpoints": "periodic", "smearing": "periodic"},
        "not_applicable": [],
        "keywords": ["RUN_TYPE", "XC_FUNCTIONAL", "BASIS_SET_FILE_NAME", "POTENTIAL",
                     "CUTOFF", "REL_CUTOFF", "SCF", "EPS_SCF", "MAX_SCF", "CHARGE",
                     "UKS", "CELL", "PERIODIC", "POISSON_SOLVER", "SCCS", "KPOINTS", "SMEAR"],
    },
    "vasp": {
        "required": [
            "xc_functional", "dispersion", "pseudopotential", "cutoff_ev",
            "scf.algorithm", "scf.ediff", "charge", "spin", "magmom",
            "cell", "periodicity", "kpoints", "smearing",
            "solvation.implicit", "solvation.explicit", "software_version",
        ],
        "conditional": {},
        "not_applicable": ["basis_set", "rel_cutoff_ry", "multiplicity", "poisson_solver"],
        "keywords": ["INCAR", "POSCAR", "POTCAR", "KPOINTS", "ENCUT", "EDIFF", "ISPIN", "MAGMOM", "ISMEAR", "SIGMA"],
    },
    "gaussian": {
        "required": [
            "xc_functional", "dispersion", "basis_set", "ecp", "scf.method",
            "scf.convergence", "charge", "multiplicity", "spin",
            "solvation.implicit", "solvation.explicit", "software_version",
        ],
        "conditional": {},
        "not_applicable": ["pseudopotential", "cutoff_ry", "rel_cutoff_ry", "cell",
                           "periodicity", "poisson_solver", "kpoints", "smearing", "uks"],
        "keywords": ["Opt", "SP", "Freq", "TS", "IRC", "SCF", "SCRF", "Gen", "GenECP"],
    },
}


def _lookup(mapping: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _source_kind(source: Mapping[str, Any]) -> str:
    kind = str(source.get("source_kind", "")).strip().casefold()
    return {
        "frozen_docx": "frozen_source", "paper": "frozen_source", "si": "frozen_source",
        "project_profile": "approved_profile", "policy": "approved_profile",
    }.get(kind, kind)


def _canonical(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _field_value(source: Mapping[str, Any], field: str) -> tuple[bool, Any, dict[str, Any]]:
    """Accept NOT_APPLICABLE only as an explicit, sourced assertion."""
    values = source.get("fields", {})
    if not isinstance(values, Mapping):
        return False, None, {}
    present, raw = _lookup(values, field)
    if not present:
        return False, None, {}
    if isinstance(raw, Mapping) and raw.get("status") == "NOT_APPLICABLE":
        metadata = dict(raw)
        ref = metadata.get("source_ref") or source.get("source_ref")
        rationale = metadata.get("rationale")
        if "value" not in metadata or metadata.get("value") is not None or not ref or not str(rationale or "").strip():
            metadata["_invalid_not_applicable"] = True
            metadata["source_ref"] = ref
            return True, None, metadata
        metadata["source_ref"] = ref
        metadata["_explicit_not_applicable"] = True
        return True, None, metadata
    metadata = dict(raw) if isinstance(raw, Mapping) and "value" in raw else {"value": raw}
    return True, metadata.get("value"), metadata

def _periodic_state(request: Mapping[str, Any]) -> bool | None:
    structure = request.get("structure", {})
    if not isinstance(structure, Mapping) or structure.get("periodicity") is None:
        return None
    return str(structure["periodicity"]).strip().casefold() not in {"none", "molecule", "cluster", "false", "0"}


def _record(value: Any, provenance: str, source_ref: str | None, applicability: str,
            rationale: str, uncertainty: str, approval_required: bool, status: str,
            **extra: Any) -> dict[str, Any]:
    result = {
        "value": deepcopy(value), "provenance": provenance, "source_ref": source_ref,
        "applicability": applicability, "rationale": rationale, "uncertainty": uncertainty,
        "approval_required": approval_required, "status": status,
    }
    result.update(deepcopy(extra))
    return result


def plan_method(request: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve fields by explicit source precedence and return field-level provenance.

    Priority: user_explicit > frozen_source > approved_profile > version-verified
    capability_rule. Candidate sources are comparisons only. Capability registry
    contains version/keyword compatibility, not universal scientific parameter defaults.
    """
    if not isinstance(request, Mapping):
        raise TypeError("request must be a Mapping")
    engine = str(request.get("engine", "")).strip().casefold()
    task_type = str(request.get("task_type", "")).strip()
    execution_mode = str(request.get("execution_mode", "real")).strip().casefold() or "real"
    if execution_mode not in {"mock", "real"}:
        return {
            "engine": engine or None, "task_type": task_type or None,
            "execution_mode": execution_mode, "status": "BLOCKED_INVALID_EXECUTION_MODE",
            "fields": {}, "missing_fields": [], "proposed_fields": [],
            "conflicting_fields": [], "blockers": ["execution_mode must be 'mock' or 'real'."],
            "ready_for_core_compilation": False, "parameter_defaults_applied": False,
        }
    if engine not in _FIELD_SPECS:
        return {"engine": engine or None, "task_type": task_type or None,
                "status": "UNVERIFIED_ENGINE", "fields": {}, "missing_fields": [],
                "proposed_fields": [], "conflicting_fields": [],
                "blockers": [f"No method-field specification is registered for engine {engine!r}"],
                "ready_for_core_compilation": False, "parameter_defaults_applied": False}

    specs = _FIELD_SPECS[engine]
    required = list(specs["required"])
    conditional = dict(specs.get("conditional", {}))
    optional = list(specs.get("optional", []))
    not_applicable = set(specs.get("not_applicable", []))
    periodic = _periodic_state(request)
    sources_raw = request.get("sources", [])
    sources = [s for s in sources_raw if isinstance(s, Mapping)] if isinstance(sources_raw, (list, tuple)) else []
    priority = {"user_explicit": 0, "frozen_source": 1, "approved_profile": 2, "capability_rule": 3}
    ordered = sorted(sources, key=lambda s: priority.get(_source_kind(s), 99))

    requested_version_raw = request.get("software_version")
    requested_version = str(requested_version_raw).strip() if requested_version_raw is not None else ""
    requested_version = requested_version or None
    runtime_version_verified = request.get("runtime_version_verified") is True
    runtime_verified_version_raw = request.get("runtime_verified_version")
    runtime_verified_version = (
        str(runtime_verified_version_raw).strip()
        if runtime_verified_version_raw is not None else ""
    ) or None
    runtime_version_matches = bool(
        requested_version and runtime_verified_version
        and runtime_verified_version == requested_version
    )
    fields: dict[str, Any] = {}
    missing: list[str] = []
    proposed: list[str] = []
    conflicts: list[str] = []
    all_fields = list(dict.fromkeys(required + list(conditional) + optional + list(not_applicable)))

    for field in all_fields:
        if field in not_applicable:
            fields[field] = _record(
                None, "engine_applicability", f"registry:{engine}", "NOT_APPLICABLE",
                "The field is not part of the selected engine method interface.",
                "NOT_APPLICABLE", False, "NOT_APPLICABLE",
            )
            continue
        if field in conditional and conditional[field] == "periodic" and periodic is False:
            fields[field] = _record(
                None, "structure.periodicity", "request.structure.periodicity", "NOT_APPLICABLE",
                "The supplied structure explicitly declares a non-periodic system.",
                "NOT_APPLICABLE", False, "NOT_APPLICABLE",
            )
            continue

        decisive: list[tuple[int, Mapping[str, Any], Any, dict[str, Any]]] = []
        candidate_values: list[dict[str, Any]] = []
        for source in ordered:
            kind = _source_kind(source)
            present, value, metadata = _field_value(source, field)
            if not present:
                continue
            is_na = metadata.get("_explicit_not_applicable") is True
            if metadata.get("_invalid_not_applicable") is True:
                missing.append(field)
                fields[field] = _record(
                    None, "invalid_not_applicable", metadata.get("source_ref") or source.get("source_ref"),
                    "APPLICABLE", "NOT_APPLICABLE requires value:null, a non-empty rationale and a source_ref.",
                    "INVALID_DECLARATION", True, "MISSING",
                )
                continue
            if value is None and not is_na:
                continue
            source_ref = metadata.get("source_ref") or source.get("source_ref")
            if kind == "candidate":
                candidate_values.append({"value": deepcopy(value), "status": metadata.get("status", "CANDIDATE"),
                                         "source_ref": source_ref,
                                         "rationale": metadata.get("rationale", source.get("rationale"))})
                continue
            if kind not in priority:
                continue
            if kind == "approved_profile" and source.get("approved") is not True:
                candidate_values.append({"value": deepcopy(value), "status": metadata.get("status", "CANDIDATE"),
                                         "source_ref": source_ref,
                                         "rationale": "Profile is not explicitly marked approved."})
                continue
            if kind == "capability_rule":
                verified = source.get("rule_verified") is True and requested_version is not None and str(source.get("verified_for_version")) == str(requested_version)
                if not verified:
                    candidate_values.append({"value": deepcopy(value), "status": metadata.get("status", "CANDIDATE"),
                                             "source_ref": source_ref,
                                             "rationale": "Rule is not verified for the exact requested software version."})
                    continue
            decisive.append((priority[kind], source, value, metadata))

        if decisive:
            best_priority = min(x[0] for x in decisive)
            best = [x for x in decisive if x[0] == best_priority]
            if len({_canonical({"status": x[3].get("status", "VALUE"), "value": x[2]}) for x in best}) > 1:
                conflicts.append(field)
                fields[field] = _record(
                    None, "conflicting_sources", None, "APPLICABLE",
                    "Highest-priority sources disagree; no value was selected.",
                    "CONFLICT", True, "CONFLICT",
                    conflicting_sources=[{"source_kind": _source_kind(s), "source_ref": m.get("source_ref") or s.get("source_ref"),
                                          "status": m.get("status", "VALUE"), "value": deepcopy(v)} for _, s, v, m in best],
                )
                continue
            _, source, value, metadata = best[0]
            kind, ref = _source_kind(source), metadata.get("source_ref") or source.get("source_ref")
            if field == "software_version":
                if metadata.get("_explicit_not_applicable") is True or value is None or not str(value).strip():
                    missing.append(field)
                    fields[field] = _record(
                        None, "missing", ref, "APPLICABLE",
                        "software_version must be a concrete source-backed version; NOT_APPLICABLE/empty values are not accepted.",
                        "UNKNOWN", True, "MISSING",
                        declared_value=requested_version,
                    )
                    continue
                if not requested_version:
                    missing.append(field)
                    fields[field] = _record(
                        None, "missing", ref, "APPLICABLE",
                        "A non-empty request software_version is required and must be supported by source evidence.",
                        "UNKNOWN", True, "MISSING",
                        source_value=deepcopy(value),
                    )
                    continue
                if not ref or not str(ref).strip() or str(ref).strip() == "request.software_version":
                    missing.append(field)
                    fields[field] = _record(
                        None, "missing", None, "APPLICABLE",
                        "software_version source evidence requires a non-empty source_ref; the request declaration is not evidence.",
                        "UNKNOWN", True, "MISSING",
                        declared_value=requested_version, source_value=deepcopy(value),
                    )
                    continue
                if str(value).strip() != requested_version:
                    conflicts.append(field)
                    fields[field] = _record(
                        None, "conflicting_sources", ref, "APPLICABLE",
                        "The source-backed software_version does not exactly match request.software_version.",
                        "CONFLICT", True, "CONFLICT",
                        declared_value=requested_version, source_value=deepcopy(value),
                    )
                    continue
                if metadata.get("approval_required") is True:
                    proposed.append(field)
                    fields[field] = _record(
                        value, kind, ref, "APPLICABLE",
                        str(metadata.get("rationale", source.get("rationale", "Software version source requires approval."))),
                        str(metadata.get("uncertainty", "APPROVAL_REQUIRED")),
                        True, "PROPOSED",
                    )
                    continue
            if metadata.get("_explicit_not_applicable") is True:
                fields[field] = _record(
                    None, kind, ref, "NOT_APPLICABLE", str(metadata["rationale"]),
                    "NOT_APPLICABLE", False, "NOT_APPLICABLE",
                )
            else:
                status = "APPROVED_POLICY" if kind == "approved_profile" else ("VERSION_VERIFIED_RULE" if kind == "capability_rule" else "SOURCE_CONFIRMED")
                fields[field] = _record(
                    value, kind, ref, str(metadata.get("applicability", "APPLICABLE")),
                    str(metadata.get("rationale", source.get("rationale", "Selected by declared source precedence."))),
                    str(metadata.get("uncertainty", source.get("uncertainty", "UNSPECIFIED_BY_SOURCE"))),
                    bool(metadata.get("approval_required", False)), status,
                )
            continue

        if field == "software_version" and requested_version:
            source_ref = request.get("software_version_source_ref")
            source_ref = str(source_ref).strip() if source_ref is not None else ""
            if source_ref and source_ref != "request.software_version":
                provenance_value = str(request.get("software_version_provenance") or "explicit_source_reference")
                rationale_value = str(request.get("software_version_rationale") or
                    "The caller explicitly supplied this source reference for the requested software version.")
                approval_required = request.get("software_version_approval_required") is True
                requested_status = str(request.get("software_version_status") or "SOURCE_CONFIRMED")
                if requested_status not in {"SOURCE_CONFIRMED", "APPROVED_POLICY", "VERSION_VERIFIED_RULE"}:
                    approval_required = True
                if approval_required:
                    proposed.append(field)
                fields[field] = _record(
                    requested_version, provenance_value, source_ref, "APPLICABLE",
                    rationale_value,
                    "APPROVAL_REQUIRED" if approval_required else "SOURCE_DECLARED_NOT_RUNTIME_VERIFIED",
                    approval_required,
                    "PROPOSED" if approval_required else requested_status,
                )
            else:
                missing.append(field)
                fields[field] = _record(
                    None, "missing", None, "APPLICABLE",
                    "A source-backed software_version record with a non-empty source_ref is required; request.software_version alone is only a declaration.",
                    "UNKNOWN", True, "MISSING",
                    declared_value=requested_version,
                )
            continue
        if field in optional:
            if candidate_values:
                proposed.append(field)
                fields[field] = _record(
                    None, "candidate_comparison", None, "APPLICABLE",
                    "No approved policy selects an optional field candidate.",
                    "UNRESOLVED_CHOICE", True, "PROPOSED", candidates=candidate_values,
                )
            continue
        if candidate_values:
            proposed.append(field)
            fields[field] = _record(
                None, "candidate_comparison", None, "APPLICABLE",
                "No approved policy selects among the supplied candidates.",
                "UNRESOLVED_CHOICE", True, "PROPOSED", candidates=candidate_values,
            )
        else:
            missing.append(field)
            fields[field] = _record(
                None, "missing", None, "APPLICABLE",
                "No user, frozen-source, approved-profile or version-verified capability evidence supplied this field.",
                "UNKNOWN", True, "MISSING",
            )

    # The registry can state which keywords are documented, but only local executable
    # preflight can validate an input deck against the actual build.
    keyword_source = "https://manual.cp2k.org/" if engine == "cp2k" else (
        "https://vasp.at/wiki/" if engine == "vasp" else "https://gaussian.com/"
    )
    keyword_status = "DOCUMENTATION_BASELINE_ONLY" if requested_version else "UNVERIFIED"
    fields["keyword_compatibility"] = _record(
        {"documented_keywords": list(specs.get("keywords", [])), "runtime_input_validation": "REQUIRED",
         "software_version": requested_version},
        "capability_registry", keyword_source, "APPLICABLE",
        "Keyword index is advisory; exact installed version and generated input require runtime validation.",
        "NOT_RUNTIME_VERIFIED", True, keyword_status,
    )

    blockers: list[str] = []
    if execution_mode == "real":
        if not runtime_version_verified:
            blockers.append("Exact software version must be verified against the installed executable before Real planning.")
        if not runtime_version_matches:
            blockers.append("runtime_verified_version must exactly match the requested software_version for Real planning.")
    if periodic is None and conditional:
        if "structure.periodicity" not in missing:
            missing.append("structure.periodicity")
        blockers.append("structure.periodicity is required to establish k-point/smearing applicability.")
    if missing:
        blockers.append("Missing method fields: " + ", ".join(missing))
    if proposed:
        blockers.append("Unapproved method choices require approval: " + ", ".join(proposed))
    if conflicts:
        blockers.append("Conflicting highest-priority method sources: " + ", ".join(conflicts))
    if missing:
        status = "BLOCKED_MISSING_METHOD_FIELDS"
    elif conflicts:
        status = "BLOCKED_SOURCE_CONFLICT"
    elif execution_mode == "real" and (not runtime_version_verified or not runtime_version_matches):
        status = "BLOCKED_RUNTIME_VERSION_UNVERIFIED"
    elif proposed:
        status = "PROPOSED"
    else:
        status = "METHOD_FIELDS_RESOLVED"
    ready = status == "METHOD_FIELDS_RESOLVED" and not blockers
    return {
        "engine": engine, "task_type": task_type, "execution_mode": execution_mode,
        "software_version": requested_version,
        "runtime_version_verified": runtime_version_verified,
        "runtime_verified_version": runtime_verified_version,
        "runtime_version_matches": runtime_version_matches,
        "status": status, "fields": fields,
        "required_fields": required, "missing_fields": missing, "proposed_fields": proposed,
        "conflicting_fields": conflicts, "parameter_defaults_applied": False,
        "source_precedence": ["user_explicit", "frozen_source", "approved_profile", "version_verified_capability_rule", "candidate_only"],
        "ready_for_core_compilation": ready, "blockers": blockers,
        "calculation_plan_context": deepcopy(request.get("calculation_plan_context")),
    }


__all__ = ["plan_method"]
