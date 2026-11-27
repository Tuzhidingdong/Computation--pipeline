"""Conservative reconciliation of Project Profile values with Manifest evidence.

This module is deliberately read-only: it never edits a profile, claim, or source
evidence record. Automatic support requires an exact field-identifier match and
an exact value match under the narrow normalisation rules below.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

RECONCILIATION_SCHEMA_VERSION = "1.0.0"

SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
SOURCE_MISMATCH = "SOURCE_MISMATCH"
PROFILE_ONLY = "PROFILE_ONLY"
MENTION_ONLY = "MENTION_ONLY"
NEEDS_REVIEW = "NEEDS_REVIEW"

# These are profile/document metadata, not project parameters to be reconciled.
_IGNORED_ROOT_FIELDS = {"schema_version", "project_id", "description", "known_blockers"}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_QUANTITY_RE = re.compile(
    rf"^\s*(?P<number>{_NUMBER})\s*(?P<unit>[A-Za-zÅåÅ%°][A-Za-z0-9ÅåÅ%°/^._-]*)?\s*$"
)
_KEY_VALUE_RE = re.compile(r"^\s*(?P<key>[^:=：=]{2,100})\s*[:：=]\s*(?P<value>.+?)\s*$")

# A Profile key's conventional unit suffix is an explicit unit declaration.
# These are exact suffixes only; arbitrary key text is never interpreted as a unit.
_PROFILE_UNIT_SUFFIXES = (
    ("ev_per_angstrom", "eV/Angstrom"),
    ("hartree", "hartree"),
    ("angstrom", "Angstrom"),
    ("bohr", "Bohr"),
    ("mev", "meV"),
    ("ry", "Ry"),
    ("ha", "Ha"),
    ("ev", "eV"),
    ("nm", "nm"),
    ("ps", "ps"),
    ("fs", "fs"),
    ("k", "K"),
)

_UNIT_ALIASES = {
    "å": "angstrom",
    "Å": "angstrom",
    "angstrom": "angstrom",
    "ha": "hartree",
    "hartree": "hartree",
    "ev/å": "ev/angstrom",
    "ev/Å": "ev/angstrom",
    "ev/angstrom": "ev/angstrom",
}


def _normalise_identifier(value: Any) -> str:
    """Mirror the Manifest label normaliser; matching remains exact, not fuzzy."""
    text = re.sub(r"\s+", "_", str(value).strip().casefold())
    return re.sub(r"[^a-z0-9_]+", "", text).strip("_")


def _normalise_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _canonical_unit(unit: str) -> str:
    folded = unit.casefold()
    return _UNIT_ALIASES.get(folded, folded)


def _decimal_token(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
            return number.normalize() if number.is_finite() else None
        except (InvalidOperation, ValueError):
            return None
    if not isinstance(value, str):
        return None
    match = _QUANTITY_RE.fullmatch(value)
    if not match:
        return None
    try:
        number = Decimal(match.group("number"))
    except InvalidOperation:
        return None
    return number.normalize() if number.is_finite() else None


def _canonical_value(value: Any) -> tuple[Any, ...]:
    """Return a strict comparison key without unit conversion or inference."""
    if isinstance(value, Mapping) and set(value) == {"value", "unit"}:
        return _canonical_value(f"{value['value']} {value['unit']}")
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_canonical_value(item) for item in value))
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        number = _decimal_token(value)
        return ("number", number) if number is not None else ("raw", repr(value))
    if isinstance(value, str):
        match = _QUANTITY_RE.fullmatch(value)
        if match:
            number = _decimal_token(value)
            unit = match.group("unit")
            if unit:
                return ("quantity", number, _canonical_unit(unit))
            return ("number", number)
        return ("text", _normalise_text(value))
    return ("raw", repr(value))


def _field_value(claim: Mapping[str, Any]) -> Any:
    """Accept either extractor-split values or an explicitly repeated KEY=VALUE."""
    value = claim.get("value")
    if not isinstance(value, str):
        return value
    match = _KEY_VALUE_RE.fullmatch(value)
    if not match:
        return value
    key = _normalise_identifier(match.group("key"))
    known = {
        _normalise_identifier(claim.get("field", "")),
        _normalise_identifier(claim.get("label", "")),
    }
    known.discard("")
    return match.group("value") if key in known else value


def _claim_comparison_value(claim: Mapping[str, Any]) -> Any:
    value = _field_value(claim)
    unit = claim.get("unit")
    if unit is None or not str(unit).strip():
        return value
    # Respect an explicit claim.unit only when value itself has no unit.
    if isinstance(value, (int, float, Decimal)):
        return {"value": value, "unit": str(unit)}
    if isinstance(value, str) and re.fullmatch(rf"\s*{_NUMBER}\s*", value):
        return {"value": value.strip(), "unit": str(unit)}
    return value


def _iter_profile_fields(profile: Mapping[str, Any]):
    def walk(value: Any, path: tuple[str, ...]):
        if isinstance(value, Mapping):
            if set(value) == {"value", "unit"}:
                yield ".".join(path), dict(value)
                return
            for key, child in value.items():
                if not path and str(key) in _IGNORED_ROOT_FIELDS:
                    continue
                walk_path = path + (str(key),)
                yield from walk(child, walk_path)
            return
        # Unset scalar fields remain visible as NEEDS_REVIEW in the report.
        # Lists are treated as one ordered field, rather than inventing indexed labels.
        yield ".".join(path), value

    for key, value in profile.items():
        if str(key) in _IGNORED_ROOT_FIELDS:
            continue
        yield from walk(value, (str(key),))


def _profile_comparison_value(path: str, value: Any) -> Any:
    """Apply only an explicit, whitelisted unit suffix from the Profile key."""
    if isinstance(value, Mapping) and set(value) == {"value", "unit"}:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return value
    if isinstance(value, str):
        parsed = _QUANTITY_RE.fullmatch(value)
        if not parsed or parsed.group("unit"):
            return value
    # Check nested path components too (e.g. method.scf_eps_scf_ha.geometry_optimization).
    keys = [_normalise_identifier(part) for part in path.split(".")]
    for key in reversed(keys):
        for suffix, unit in _PROFILE_UNIT_SUFFIXES:
            if key.endswith("_" + suffix):
                return {"value": value, "unit": unit}
    return value


def _field_aliases(path: str, explicit: Mapping[str, str | Sequence[str]] | None) -> set[str]:
    parts = path.split(".")
    if explicit and path in explicit:
        supplied = explicit[path]
        if isinstance(supplied, str):
            values = [supplied]
        elif isinstance(supplied, Sequence) and not isinstance(supplied, (bytes, bytearray)):
            values = list(supplied)
        else:
            raise TypeError(f"aliases[{path!r}] must be a string or sequence of strings")
        if any(not isinstance(item, str) for item in values):
            raise TypeError(f"aliases[{path!r}] must contain only strings")
        # Explicit entries replace default suffixes for this path, allowing
        # callers to resolve duplicate leaf names without retaining ambiguity.
        return {_normalise_identifier(item) for item in values if item.strip()}
    aliases = {
        _normalise_identifier("_".join(parts[index:]))
        for index in range(len(parts))
    }
    aliases.discard("")
    return aliases


def _claim_identifiers(claim: Mapping[str, Any]) -> set[str]:
    identifiers = {
        _normalise_identifier(claim.get("field", "")),
        _normalise_identifier(claim.get("label", "")),
    }
    identifiers.discard("")
    return identifiers


def _evidence_payload(
    claim: Mapping[str, Any], evidence_by_id: Mapping[str, list[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    evidence_id = claim.get("evidence_id")
    indexed = evidence_by_id.get(str(evidence_id), []) if evidence_id is not None else []
    if indexed:
        output = []
        for evidence in indexed:
            output.append({
                "evidence_id": evidence_id,
                "text": claim.get("source_text") or evidence.get("text"),
                "evidence_text": evidence.get("text"),
                "source": claim.get("source") or evidence.get("source"),
                "claim_field": claim.get("field"),
                "claim_label": claim.get("label"),
                "claim_value": _field_value(claim),
                "claim_unit": claim.get("unit"),
                "claim_status": claim.get("status"),
            })
        return output
    # Some compatible Manifest producers may inline provenance on the claim.
    return [{
        "evidence_id": evidence_id,
        "text": claim.get("source_text"),
        "evidence_text": None,
        "source": claim.get("source"),
        "claim_field": claim.get("field"),
        "claim_label": claim.get("label"),
        "claim_value": _field_value(claim),
        "claim_unit": claim.get("unit"),
        "claim_status": claim.get("status"),
    }]


def _has_complete_provenance(records: list[dict[str, Any]]) -> bool:
    return bool(records) and all(
        record.get("evidence_id") is not None
        and bool(record.get("text"))
        and record.get("source") is not None
        for record in records
    )


def _matches_mention(value: Any, text: str) -> bool:
    """Literal token/phrase mention test; never performs semantic similarity."""
    candidates: list[str] = []
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(_matches_mention(item, text) for item in value)
    if isinstance(value, Mapping) and set(value) == {"value", "unit"}:
        return _matches_mention(f"{value['value']} {value['unit']}", text)
    if isinstance(value, (int, float, Decimal)):
        candidates.append(str(value))
    elif isinstance(value, str):
        candidates.append(value.strip())
        quantity = _QUANTITY_RE.fullmatch(value)
        if quantity and quantity.group("unit"):
            candidates.append(quantity.group("number"))
    else:
        return False

    for candidate in candidates:
        if not candidate:
            continue
        pattern = re.escape(candidate)
        pattern = re.sub(r"\\\s+", r"\\s+", pattern)
        # Avoid matching 5 inside 15 or 500 inside 1500.
        if re.fullmatch(_NUMBER, candidate):
            boundary_pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])(?!\.\d)"
        else:
            boundary_pattern = rf"(?<![A-Za-z0-9_]){pattern}(?![A-Za-z0-9_])"
        if re.search(boundary_pattern, text, re.IGNORECASE):
            return True
    return False


def _mention_evidence(
    value: Any, evidence: Sequence[Mapping[str, Any]], claims: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, list[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    # Scan the original evidence corpus, not a lossy/filtered claim list.
    for item in evidence:
        text = item.get("text")
        evidence_id = item.get("evidence_id")
        if not isinstance(text, str) or evidence_id is None or not _matches_mention(value, text):
            continue
        key = (str(evidence_id), text)
        if key in seen:
            continue
        seen.add(key)
        matches.append({
            "evidence_id": evidence_id, "text": text, "evidence_text": text,
            "source": item.get("source"), "claim_field": None,
            "claim_label": None, "claim_value": None, "claim_status": "mention_only",
        })
    # Preserve inline-only Manifest claim provenance when it is not in evidence[].
    for claim in claims:
        if claim.get("field") not in (None, ""):
            continue
        records = _evidence_payload(claim, evidence_by_id)
        for record in records:
            text = record.get("text")
            evidence_id = record.get("evidence_id")
            key = (str(evidence_id), str(text))
            if (isinstance(text, str) and evidence_id is not None
                    and key not in seen and _matches_mention(value, text)):
                seen.add(key)
                matches.append(record)
    return matches


def reconcile_project_profile(
    profile: Mapping[str, Any],
    manifest: Mapping[str, Any],
    aliases: Mapping[str, str | Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Compare flattened Profile parameters with labelled Manifest claims.

    Args:
        profile: Parsed Project Profile mapping.
        manifest: Parsed Project Manifest mapping; neither input is mutated.
        aliases: Optional mapping from dotted profile field paths to exact
            Manifest field names/labels. Alias values may be one string or a
            sequence of strings. No fuzzy or partial matching is performed.

    Returns:
        A versioned report with one result per flattened profile field. Every
        result contains status, original profile value, evidence IDs, original
        evidence text/location and a deterministic rationale.
    """
    if not isinstance(profile, Mapping) or not isinstance(manifest, Mapping):
        raise TypeError("profile and manifest must be mappings")
    if aliases is not None and not isinstance(aliases, Mapping):
        raise TypeError("aliases must be a mapping of profile paths to exact labels")
    claims = manifest.get("claims", [])
    evidence = manifest.get("evidence", [])
    if not isinstance(claims, list) or not isinstance(evidence, list):
        raise ValueError("manifest claims and evidence must be lists")
    if any(not isinstance(item, Mapping) for item in claims + evidence):
        raise ValueError("manifest claims/evidence entries must be mappings")

    evidence_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        evidence_id = item.get("evidence_id")
        if evidence_id is not None:
            evidence_by_id.setdefault(str(evidence_id), []).append(item)

    fields = list(_iter_profile_fields(profile))
    aliases_by_path = {
        path: _field_aliases(path, aliases) for path, _ in fields
    }
    claims_by_path: dict[str, list[Mapping[str, Any]]] = {path: [] for path, _ in fields}
    claim_candidate_paths: dict[int, list[str]] = {}
    for claim in claims:
        identifiers = _claim_identifiers(claim)
        if not identifiers:
            continue
        matched_paths = [
            path for path, alias_set in aliases_by_path.items()
            if identifiers.intersection(alias_set)
        ]
        if matched_paths:
            claim_candidate_paths[id(claim)] = matched_paths
            for path in matched_paths:
                claims_by_path[path].append(claim)

    results: list[dict[str, Any]] = []
    for path, profile_value in fields:
        field_claims = claims_by_path[path]
        evidence_records: list[dict[str, Any]] = []
        for claim in field_claims:
            evidence_records.extend(_evidence_payload(claim, evidence_by_id))

        evidence_ids = list(dict.fromkeys(
            record["evidence_id"] for record in evidence_records
            if record.get("evidence_id") is not None
        ))
        status: str
        rationale: str

        ambiguous_claims = [
            claim for claim in field_claims
            if len(claim_candidate_paths.get(id(claim), [])) > 1
        ]
        if profile_value is None or profile_value == "":
            status = NEEDS_REVIEW
            rationale = "The Profile field is unset/empty, so no source-value comparison can be made."
        elif ambiguous_claims:
            status = NEEDS_REVIEW
            rationale = (
                "At least one exact Manifest field identifier maps to multiple "
                "Profile paths; the module cannot choose a target field."
            )
        elif not field_claims:
            mention_records = _mention_evidence(profile_value, evidence, claims, evidence_by_id)
            if mention_records:
                status = MENTION_ONLY
                rationale = (
                    "The value or term occurs literally in source evidence, but no "
                    "Manifest claim has an exact field identifier for this Profile path."
                )
                evidence_records = mention_records
                evidence_ids = list(dict.fromkeys(
                    record["evidence_id"] for record in evidence_records
                    if record.get("evidence_id") is not None
                ))
            else:
                status = PROFILE_ONLY
                rationale = "No exact field claim or literal value/term mention was found in Manifest evidence."
        else:
            claim_values = [_claim_comparison_value(claim) for claim in field_claims]
            if any(value is None for value in claim_values) or not _has_complete_provenance(evidence_records):
                status = NEEDS_REVIEW
                rationale = (
                    "A field claim exists, but its value or evidence ID/text/source location "
                    "is incomplete; source support cannot be established."
                )
            else:
                distinct_values = {_canonical_value(value) for value in claim_values}
                if len(distinct_values) > 1:
                    status = SOURCE_CONFLICT
                    rationale = (
                        "The same exact field identifier has multiple semantically "
                        "different source values; all source claims are retained."
                    )
                elif next(iter(distinct_values)) == _canonical_value(
                    _profile_comparison_value(path, profile_value)
                ):
                    status = SOURCE_SUPPORTED
                    rationale = (
                        "An exact Manifest field identifier is linked to one unique "
                        "source value equal to the Profile value under conservative normalization."
                    )
                else:
                    status = SOURCE_MISMATCH
                    rationale = (
                        "An exact Manifest field identifier was found, but its source value "
                        "does not equal the Profile value; units are never converted or inferred."
                    )

        results.append({
            "profile_field": path,
            "profile_value": profile_value,
            "status": status,
            "evidence_id": evidence_ids[0] if evidence_ids else None,
            "evidence_ids": evidence_ids,
            "evidence": evidence_records,
            "rationale": rationale,
        })

    counts = {status: sum(result["status"] == status for result in results) for status in (
        SOURCE_SUPPORTED, SOURCE_CONFLICT, SOURCE_MISMATCH, PROFILE_ONLY,
        MENTION_ONLY, NEEDS_REVIEW,
    )}
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "result_count": len(results),
        "summary": counts,
        "results": results,
    }


# A descriptive alias for callers who think of this operation as a pairwise check.
reconcile_profile_manifest = reconcile_project_profile
