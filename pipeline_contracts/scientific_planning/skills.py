"""Version-pinned access to selected K-Dense skill assets.

Skill files are external reference material. This module never executes shell
commands from them and does not provide a second Agent runtime.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "_vendor" / "kdense" / "upstream-lock.json"


class SkillIntegrityError(RuntimeError):
    """Vendored upstream content differs from the audited lock."""


class SkillUnavailable(RuntimeError):
    """The requested upstream skill is disabled or quarantined."""


def load_upstream_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def verify_vendored_asset(relative_path: str, expected_sha256: str) -> bool:
    candidate = (ROOT.parents[1] / relative_path).resolve()
    repository_root = ROOT.parents[1]
    try:
        candidate.relative_to(repository_root)
    except ValueError as exc:
        raise SkillIntegrityError("vendored asset escapes repository root") from exc
    if not candidate.is_file():
        raise SkillIntegrityError(f"vendored asset is missing: {relative_path}")
    actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise SkillIntegrityError(
            f"SHA-256 mismatch for {relative_path}: expected {expected_sha256}, got {actual}"
        )
    return True


def get_skill_record(name: str) -> dict[str, Any]:
    lock = load_upstream_lock()
    for record in lock.get("skills", []):
        if record.get("name") == name:
            return dict(record)
    raise SkillUnavailable(f"skill is not in the selected allow-list: {name}")


def load_skill_instructions(name: str) -> str:
    """Load an allow-listed skill only after hash verification.

    literature-review is deliberately quarantined because the pinned upstream
    security report labelled it CRITICAL. The text is retained for audit only.
    """
    record = get_skill_record(name)
    if record.get("runtime_status") != "ENABLED":
        raise SkillUnavailable(
            f"{name} is {record.get('runtime_status')}; it must not enter an Agent prompt"
        )
    relative = str(record["vendored_path"])
    verify_vendored_asset(relative, str(record["sha256"]))
    return (ROOT.parents[1] / relative).read_text(encoding="utf-8")


def list_selected_skills() -> list[dict[str, Any]]:
    return [
        {key: record.get(key) for key in
         ("name", "version", "security_status", "runtime_status", "upstream_path",
          "vendored_path", "git_blob_sha", "sha256", "license")}
        for record in load_upstream_lock().get("skills", [])
    ]


def run_existing_skill_executor(
    executor: Callable[..., Any] | None,
    *,
    skill_name: str,
    task: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Invoke a caller-supplied existing host executor; never starts a runtime.

    Adapter contract: executor(skill_name=..., instructions=..., task=...,
    payload=...) -> JSON-compatible mapping. Its output is untrusted data and
    may only annotate a dossier; it cannot mutate Pipeline state.
    """
    if executor is None:
        return {"status": "UNAVAILABLE", "reason": "No existing Skill executor was configured."}
    instructions = load_skill_instructions(skill_name)
    result = executor(
        skill_name=skill_name,
        instructions=instructions,
        task=task,
        payload=dict(payload),
    )
    if not isinstance(result, Mapping):
        raise TypeError("Skill executor must return a JSON-compatible mapping")
    # Round-trip rejects opaque objects and ensures no executable Python object
    # crosses the adapter boundary.
    return json.loads(json.dumps(dict(result), ensure_ascii=False, allow_nan=False))


__all__ = [
    "SkillIntegrityError", "SkillUnavailable", "get_skill_record",
    "list_selected_skills", "load_skill_instructions", "load_upstream_lock",
    "run_existing_skill_executor", "verify_vendored_asset",
]
