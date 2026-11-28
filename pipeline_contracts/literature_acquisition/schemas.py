"""Schema accessors for deterministic Source Packages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema


SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "source_package.schema.json"


def source_package_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_source_package(package: Mapping[str, Any]) -> None:
    schema = source_package_schema()
    jsonschema.Draft7Validator.check_schema(schema)
    errors = sorted(
        jsonschema.Draft7Validator(schema).iter_errors(dict(package)),
        key=lambda item: list(item.path),
    )
    if errors:
        detail = "; ".join(f"{list(item.path)}: {item.message}" for item in errors[:10])
        raise ValueError(f"Source Package schema validation failed: {detail}")
