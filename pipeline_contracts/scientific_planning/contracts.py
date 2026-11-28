"""Validation contracts for the single Scientific Planning schema."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

PLANNING_SCHEMA_VERSION = "1.0.0"
SCHEMA_RELATIVE_PATH = Path("docs") / "architecture" / "schemas" / "scientific-planning.schema.json"


def schema_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    path = root / SCHEMA_RELATIVE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Scientific Planning schema is missing: {path}")
    return path


def load_schema() -> dict:
    data = json.loads(schema_path().read_text(encoding="utf-8"))
    if data.get("$ref") != "#/$defs/PlanningBundle" or "PlanningBundle" not in data.get("$defs", {}):
        raise ValueError("the existing Scientific Planning schema must define PlanningBundle")
    return data


def _validate(instance: Mapping[str, Any], definition: str) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise RuntimeError("Scientific Planning schema validation requires jsonschema") from exc
    schema = load_schema()
    wrapper = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}
    errors = sorted(
        Draft202012Validator(wrapper, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda err: (list(err.absolute_path), err.message),
    )
    if errors:
        details = [
            f"{'.'.join(str(part) for part in err.absolute_path) or '$'}: {err.message}"
            for err in errors
        ]
        raise ValueError(f"{definition} schema validation failed: " + "; ".join(details))


def validate_bundle(bundle: Mapping[str, Any]) -> None:
    if not isinstance(bundle, Mapping):
        raise TypeError("PlanningBundle must be a mapping")
    _validate(bundle, "PlanningBundle")


def validate_object(value: Mapping[str, Any], object_type: str) -> None:
    if object_type not in load_schema().get("$defs", {}):
        raise ValueError(f"unknown Scientific Planning schema definition: {object_type}")
    _validate(value, object_type)


__all__ = ["PLANNING_SCHEMA_VERSION", "load_schema", "schema_path", "validate_bundle", "validate_object"]
