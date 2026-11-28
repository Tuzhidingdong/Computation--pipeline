"""Deterministic Planning object identity, references and immutable persistence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def object_ref(value: Mapping[str, Any], *, object_type: str, id_field: str) -> dict:
    metadata = value.get("planning_metadata") or {}
    digest = metadata.get("object_sha256")
    object_id = value.get(id_field)
    version = value.get("schema_version") or value.get("bundle_schema_version")
    if not object_id or not isinstance(digest, str) or len(digest) != 64 or not version:
        raise ValueError(f"{object_type} has no stable object ID/schema version/SHA-256")
    return {
        "object_type": object_type,
        "object_id": str(object_id),
        "schema_version": str(version),
        "sha256": digest,
    }


def seal_object(
    body: Mapping[str, Any], *, object_type: str, id_field: str, prefix: str,
    status: str, source_evidence_refs: list[dict] | None = None,
    upstream_sha256s: Mapping[str, str] | None = None,
    selection_records: list[dict] | None = None,
    missing_items: list[dict] | None = None,
) -> dict:
    """Add a deterministic ID and a content digest without self-referential hashing."""
    value = dict(body)
    value.pop("planning_metadata", None)
    id_material = dict(value)
    id_material[id_field] = ""
    object_id = f"{prefix}-{canonical_sha256(id_material)[:20]}"
    value[id_field] = object_id
    digest = canonical_sha256(value)
    metadata = {
        "object_type": object_type,
        "object_sha256": digest,
        "source_evidence_refs": list(source_evidence_refs or []),
        "upstream_sha256s": dict(sorted((upstream_sha256s or {}).items())),
        "selection_records": list(selection_records or []),
        "missing_items": list(missing_items or []),
        "planning_status": str(status),
    }
    value["planning_metadata"] = metadata
    return value


def object_index(bundle: Mapping[str, Any]) -> dict:
    objects: dict[str, Any] = {}
    objects["scientific_intent"] = object_ref(
        bundle["scientific_intent"], object_type="ScientificIntent", id_field="intent_id"
    )
    objects["research_plan"] = object_ref(
        bundle["research_plan"], object_type="ResearchPlan", id_field="plan_id"
    )
    objects["model_recipes"] = [
        object_ref(item, object_type="ModelRecipe", id_field="recipe_id")
        for item in bundle.get("model_recipes", [])
    ]
    for key, object_type, id_field in (
        ("method_plan", "MethodPlan", "method_plan_id"),
        ("execution_plan", "ExecutionPlan", "execution_plan_id"),
        ("qc_plan", "QCPlan", "qc_plan_id"),
    ):
        objects[key] = object_ref(bundle[key], object_type=object_type, id_field=id_field)
    return {"bundle_id": bundle.get("bundle_id"), "objects": objects}


def write_immutable_json(path: str | Path, value: Any) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(f"refusing to overwrite unreadable immutable object: {target}") from exc
        if canonical_sha256(existing) != canonical_sha256(value):
            raise FileExistsError(f"refusing to overwrite a different immutable planning object: {target}")
        return digest
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    return digest


__all__ = ["canonical_json", "canonical_sha256", "object_ref", "seal_object", "object_index", "write_immutable_json"]
