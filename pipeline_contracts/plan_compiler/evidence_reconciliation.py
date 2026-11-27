"""Conservative reconciliation of Project Profile values with Manifest evidence.

This module is deliberately read-only: it never edits a profile, claim, or source
evidence record. Automatic support requires an exact field-identifier match and
an exact value match under the narrow normalisation rules below.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence
import unicodedata

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
    """Mirror the latest Manifest normaliser; matching remains exact, not fuzzy."""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"[^a-z0-9_]+", "", text)
    return re.sub(r"_+", "_", text).strip("_")

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
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Resolve all claim references to exact original Manifest evidence records."""
    issues: list[str] = []
    referenced_ids: list[str] = []

    raw_ids = claim.get("evidence_ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list):
            issues.append("claim.evidence_ids is not a list")
        else:
            for item in raw_ids:
                if item is None or not str(item).strip():
                    issues.append("claim.evidence_ids contains an empty reference")
                elif str(item) not in referenced_ids:
                    referenced_ids.append(str(item))

    raw_sources = claim.get("sources")
    source_entries: list[Mapping[str, Any]] | None = None
    if raw_sources is not None:
        if not isinstance(raw_sources, list) or not raw_sources:
            issues.append("claim.sources is present but not a non-empty list")
            source_entries = []
        else:
            source_entries = []
            source_ids: list[str] = []
            for index, item in enumerate(raw_sources):
                if not isinstance(item, Mapping):
                    issues.append(f"claim.sources[{index}] is not an object")
                    continue
                source_id = item.get("evidence_id")
                if source_id is None or not str(source_id).strip():
                    issues.append(f"claim.sources[{index}] has no evidence_id")
                    continue
                source_ids.append(str(source_id))
                source_entries.append(item)
            if not referenced_ids:
                referenced_ids = list(dict.fromkeys(source_ids))
            elif source_ids != referenced_ids:
                issues.append("claim.sources evidence IDs do not exactly match claim.evidence_ids order")
            if len(source_ids) != len(raw_sources):
                issues.append("one or more claim.sources entries have incomplete references")

    legacy_id = claim.get("evidence_id")
    if legacy_id is not None and str(legacy_id).strip():
        if not referenced_ids:
            referenced_ids.append(str(legacy_id))
        elif referenced_ids[0] != str(legacy_id):
            issues.append("claim.evidence_id does not identify the first evidence reference")

    if not referenced_ids:
        issues.append("claim has no evidence_id/evidence_ids/sources reference")

    source_by_id = (
        {str(item.get("evidence_id")): item for item in source_entries}
        if source_entries is not None else {}
    )
    records: list[dict[str, Any]] = []
    for index, evidence_id in enumerate(referenced_ids):
        indexed = evidence_by_id.get(evidence_id, [])
        if len(indexed) != 1:
            issues.append(
                f"evidence reference {evidence_id!r} resolves to {len(indexed)} Manifest evidence records"
            )
            continue
        raw_evidence = indexed[0]
        raw_text = raw_evidence.get("text")
        raw_source = raw_evidence.get("source")
        if not isinstance(raw_text, str) or not raw_text.strip():
            issues.append(f"evidence {evidence_id!r} has no original text")
        if not isinstance(raw_source, Mapping) or not raw_source:
            issues.append(f"evidence {evidence_id!r} has no source location")

        if source_entries is not None:
            source_entry = source_by_id.get(evidence_id)
            if source_entry is None:
                issues.append(f"evidence {evidence_id!r} is missing from claim.sources")
            else:
                if source_entry.get("source_text") != raw_text:
                    issues.append(f"claim.sources text for {evidence_id!r} differs from original evidence text")
                if source_entry.get("source") != raw_source:
                    issues.append(f"claim.sources location for {evidence_id!r} differs from original evidence location")

        if isinstance(raw_text, str) and isinstance(raw_source, Mapping):
            records.append({
                "evidence_id": evidence_id,
                # Never substitute the row-level claim excerpt for a cell's text.
                "text": raw_text,
                "evidence_text": raw_text,
                "source": dict(raw_source),
                "contribution": (
                    "field_assertion" if len(referenced_ids) == 1
                    else ("field_label" if index == 0 else "field_value")
                ),
                "claim_field": claim.get("field"),
                "claim_label": claim.get("label"),
                "claim_value": _field_value(claim),
                "claim_unit": claim.get("unit"),
                "claim_status": claim.get("status"),
                "claim_source_text": claim.get("source_text"),
            })

    # Validate the claim-level pointer against the first original record.
    if records and claim.get("source") is not None:
        if claim.get("source") != records[0]["source"]:
            issues.append("claim.source differs from the first original evidence location")

    if len(referenced_ids) == 1 and records:
        if claim.get("source_text") is not None and claim.get("source_text") != records[0]["text"]:
            issues.append("single-source claim.source_text differs from original evidence text")

    if len(referenced_ids) > 1 and len(records) == len(referenced_ids):
        cell_texts = [record["text"] for record in records]
        aggregate_text = " | ".join(cell_texts)
        if claim.get("source_text") is not None and claim.get("source_text") != aggregate_text:
            issues.append("claim.source_text does not equal the ordered original cell-text aggregate")

        label_text = cell_texts[0].strip()
        if claim.get("label") and _normalise_identifier(claim["label"]) != _normalise_identifier(label_text):
            issues.append("first source cell does not match claim.label")
        if claim.get("field") and _normalise_identifier(claim["field"]) != _normalise_identifier(label_text):
            issues.append("first source cell does not match claim.field")

        value_from_cells = " | ".join(text.strip() for text in cell_texts[1:])
        if not value_from_cells:
            issues.append("multi-cell assertion has no value cell")
        elif _canonical_value(value_from_cells) != _canonical_value(_field_value(claim)):
            issues.append("claim.value does not equal the ordered original value-cell text")

        locations = [record["source"] for record in records]
        if any(not {"table", "row", "column"}.issubset(location) for location in locations):
            issues.append("multi-cell source locations do not identify table/row/column")
        elif len({(location["table"], location["row"]) for location in locations}) != 1:
            issues.append("multi-cell evidence references more than one table row")
        else:
            try:
                columns = [int(location["column"]) for location in locations]
                if columns != sorted(columns) or len(set(columns)) != len(columns):
                    issues.append("multi-cell evidence is not in unique ascending column order")
            except (TypeError, ValueError):
                issues.append("multi-cell source columns are not integers")

    return records, issues, referenced_ids


def _has_complete_provenance(
    records: list[dict[str, Any]], issues: Sequence[str] = ()
) -> bool:
    return (
        bool(records)
        and not issues
        and all(
            record.get("evidence_id") is not None
            and isinstance(record.get("text"), str)
            and bool(record.get("text").strip())
            and isinstance(record.get("source"), Mapping)
            and bool(record.get("source"))
            for record in records
        )
    )


def _normalise_wp_scope(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"WP\s*[-_#]?\s*(\d+)", text, re.IGNORECASE)
    return f"wp{int(match.group(1))}" if match else _normalise_identifier(text)


def _profile_scope(path: str) -> dict[str, str | None]:
    parts = path.split(".")
    system_id = None
    work_package = None
    if len(parts) > 1 and parts[0].casefold() in {"systems", "models"}:
        system_id = _normalise_identifier(parts[1])
    if len(parts) > 1 and parts[0].casefold() == "tasks":
        work_package = _normalise_wp_scope(parts[1])
    return {"system_id": system_id, "work_package": work_package}


def _claim_scope_status(path: str, claim: Mapping[str, Any]) -> str:
    """Return match, mismatch, or ambiguous for system/WP ownership."""
    profile_scope = _profile_scope(path)
    context = claim.get("context") or {}
    if not isinstance(context, Mapping):
        return "ambiguous"
    claim_system = context.get("system_id")
    claim_wp = context.get("work_package")
    claim_system_norm = _normalise_identifier(claim_system) if claim_system else None
    claim_wp_norm = _normalise_wp_scope(claim_wp) if claim_wp else None
    profile_system = profile_scope["system_id"]
    profile_wp = profile_scope["work_package"]

    # A scoped Profile needs matching explicit context. A narrower scoped source
    # cannot silently support a broader/global Profile field either.
    if profile_system and not claim_system_norm:
        return "ambiguous"
    if profile_wp and not claim_wp_norm:
        return "ambiguous"
    if claim_system_norm and not profile_system:
        return "ambiguous"
    if claim_wp_norm and not profile_wp:
        return "ambiguous"
    if profile_system and claim_system_norm != profile_system:
        return "mismatch"
    if profile_wp and claim_wp_norm != profile_wp:
        return "mismatch"
    return "match"


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
    value: Any, evidence: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return literal mentions from raw evidence records only."""
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        text = item.get("text")
        evidence_id = item.get("evidence_id")
        source = item.get("source")
        if (
            not isinstance(text, str)
            or evidence_id is None
            or not isinstance(source, Mapping)
            or not source
            or not _matches_mention(value, text)
        ):
            continue
        key = (str(evidence_id), text)
        if key in seen:
            continue
        seen.add(key)
        matches.append({
            "evidence_id": evidence_id,
            "text": text,
            "evidence_text": text,
            "source": dict(source),
            "contribution": "literal_mention",
            "claim_field": None,
            "claim_label": None,
            "claim_value": None,
            "claim_status": "mention_only",
        })
    return matches


def reconcile_project_profile(
    profile: Mapping[str, Any],
    manifest: Mapping[str, Any],
    aliases: Mapping[str, str | Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Compare Profile fields with exact, scope-compatible Manifest claims.

    Supports legacy evidence_id plus Agent B's evidence_ids/sources arrays and
    claim.context.system_id/work_package. Each emitted evidence item is one
    original Manifest evidence record; aggregate row text is kept separately.
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
    aliases_by_path = {path: _field_aliases(path, aliases) for path, _ in fields}
    claims_by_path: dict[str, list[Mapping[str, Any]]] = {path: [] for path, _ in fields}
    claim_candidate_paths: dict[int, list[str]] = {}
    scope_review_paths: set[str] = set()

    for claim in claims:
        identifiers = _claim_identifiers(claim)
        if not identifiers:
            continue
        possible_paths = [
            path for path, alias_set in aliases_by_path.items()
            if identifiers.intersection(alias_set)
        ]
        matched_paths: list[str] = []
        for path in possible_paths:
            scope_status = _claim_scope_status(path, claim)
            if scope_status == "match":
                matched_paths.append(path)
            elif scope_status == "ambiguous":
                scope_review_paths.add(path)
            # A claim explicitly scoped to another system/WP is excluded.
        if matched_paths:
            claim_candidate_paths[id(claim)] = matched_paths
            for path in matched_paths:
                claims_by_path[path].append(claim)

    results: list[dict[str, Any]] = []
    for path, profile_value in fields:
        field_claims = claims_by_path[path]
        evidence_records: list[dict[str, Any]] = []
        referenced_ids: list[str] = []
        missing_evidence_ids: list[str] = []
        provenance_issues: list[dict[str, Any]] = []

        for claim in field_claims:
            claim_records, claim_issues, claim_ids = _evidence_payload(claim, evidence_by_id)
            evidence_records.extend(claim_records)
            for evidence_id in claim_ids:
                if evidence_id not in referenced_ids:
                    referenced_ids.append(evidence_id)
            actual_ids = {str(record["evidence_id"]) for record in claim_records}
            for evidence_id in claim_ids:
                if evidence_id not in actual_ids and evidence_id not in missing_evidence_ids:
                    missing_evidence_ids.append(evidence_id)
            if claim_issues:
                provenance_issues.append({
                    "claim_field": claim.get("field"),
                    "claim_label": claim.get("label"),
                    "claim_value": _field_value(claim),
                    "evidence_ids": claim_ids,
                    "issues": claim_issues,
                })

        status: str
        rationale: str
        ambiguous_claims = [
            claim for claim in field_claims
            if len(claim_candidate_paths.get(id(claim), [])) > 1
        ]

        if profile_value is None or profile_value == "":
            status = NEEDS_REVIEW
            rationale = "The Profile field is unset/empty, so no source-value comparison can be made."
        elif ambiguous_claims or path in scope_review_paths:
            status = NEEDS_REVIEW
            rationale = (
                "The exact field identifier has an ambiguous target or lacks the explicit "
                "system/Work Package context required to bind this Profile field."
            )
        elif not field_claims:
            mention_records = _mention_evidence(profile_value, evidence)
            if mention_records:
                status = MENTION_ONLY
                rationale = (
                    "The value or term occurs literally in original Manifest evidence, "
                    "but no exact, scope-compatible field claim binds it to this Profile path."
                )
                evidence_records = mention_records
                referenced_ids = list(dict.fromkeys(
                    str(record["evidence_id"]) for record in evidence_records
                ))
                missing_evidence_ids = []
            else:
                status = PROFILE_ONLY
                rationale = "No exact scope-compatible field claim or literal value/term mention was found."
        elif provenance_issues or not _has_complete_provenance(evidence_records):
            status = NEEDS_REVIEW
            rationale = (
                "At least one claim has a missing, duplicated, inconsistent, or incomplete "
                "evidence reference; every referenced source block must resolve exactly."
            )
        else:
            claim_values = [_claim_comparison_value(claim) for claim in field_claims]
            if any(value is None for value in claim_values):
                status = NEEDS_REVIEW
                rationale = "A field claim has no comparable source value."
            else:
                distinct_values = {_canonical_value(value) for value in claim_values}
                if len(distinct_values) > 1:
                    status = SOURCE_CONFLICT
                    rationale = (
                        "The same exact field identifier in the same system/WP scope has "
                        "multiple semantically different source values; all claims are retained."
                    )
                elif next(iter(distinct_values)) == _canonical_value(
                    _profile_comparison_value(path, profile_value)
                ):
                    status = SOURCE_SUPPORTED
                    rationale = (
                        "An exact field identifier and matching system/WP context link the "
                        "Profile value to a unique source value; every source block resolves to original Manifest evidence."
                    )
                else:
                    status = SOURCE_MISMATCH
                    rationale = (
                        "An exact field identifier in the matching scope was found, but its "
                        "source value differs from the Profile value; units are never converted or inferred."
                    )

        evidence_ids = list(referenced_ids)
        results.append({
            "profile_field": path,
            "profile_value": profile_value,
            "status": status,
            "evidence_id": evidence_ids[0] if evidence_ids else None,
            "evidence_ids": evidence_ids,
            "missing_evidence_ids": missing_evidence_ids,
            "evidence": evidence_records,
            "provenance_issues": provenance_issues,
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
