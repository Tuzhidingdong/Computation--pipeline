"""Immutable approval record pinned to the exact model Artifact and file hash."""
from __future__ import annotations
from pathlib import Path
from typing import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os


def create_approval_record(
    path: str | Path, *, approver: str, candidate_id: str, artifact_id: str,
    structure_path: str | Path, validation_report: Mapping, approved: bool,
) -> dict:
    if not approver.strip() or not candidate_id.strip() or not artifact_id.strip():
        raise ValueError("approver, candidate_id and registered artifact_id are required")
    target = Path(path)
    if target.exists():
        raise FileExistsError(target)
    structure_path = Path(structure_path)
    digest = hashlib.sha256(structure_path.read_bytes()).hexdigest()
    if validation_report.get("status") != "PASS" or validation_report.get("structure_sha256") != digest:
        raise ValueError("approval requires a passing validation report for the current structure bytes")
    if approved is not True:
        raise ValueError("approval record can only be created after explicit approval")
    record = {
        "schema_version": "1.0.0", "approver": approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate_id, "artifact_id": artifact_id,
        "structure_sha256": digest, "validation_report_sha256": hashlib.sha256(
            json.dumps(dict(validation_report), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "approval_status": "APPROVED",
    }
    record["record_sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(target, flags, 0o444)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return record


def verify_approval_record(record: Mapping, structure_path: str | Path) -> bool:
    digest = hashlib.sha256(Path(structure_path).read_bytes()).hexdigest()
    return record.get("approval_status") == "APPROVED" and record.get("structure_sha256") == digest
