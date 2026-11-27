"""Immutable approval record pinned to the exact model Artifact and file hash."""
from __future__ import annotations
from pathlib import Path
from typing import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os


def create_approval_record(
    path: str | Path, *, approver: str, candidate_id: str, artifact_ref: Mapping,
    structure_path: str | Path, validation_report: Mapping, approved: bool,
) -> dict:
    artifact_id = str(artifact_ref.get("artifact_id", ""))
    if (not approver.strip() or not candidate_id.strip() or not artifact_id.strip()
            or artifact_ref.get("source_system") != "Data_analysis"
            or artifact_ref.get("verified") is not True):
        raise ValueError("approval requires approver and a Data_analysis-verified ArtifactRef")
    target = Path(path)
    if target.exists():
        raise FileExistsError(target)
    structure_path = Path(structure_path)
    digest = hashlib.sha256(structure_path.read_bytes()).hexdigest()
    if (validation_report.get("status") != "PASS"
            or validation_report.get("structure_sha256") != digest
            or str(artifact_ref.get("sha256", "")).lower() != digest.lower()):
        raise ValueError("approval requires a passing validation report and verified ArtifactRef for current bytes")
    if approved is not True:
        raise ValueError("approval record can only be created after explicit approval")
    record = {
        "schema_version": "1.0.0", "approver": approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate_id, "artifact_id": artifact_id,
        "artifact_ref": dict(artifact_ref), "structure_sha256": digest, "validation_report_sha256": hashlib.sha256(
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
    payload = dict(record)
    recorded_hash = payload.pop("record_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    record_valid = recorded_hash == hashlib.sha256(canonical).hexdigest()
    digest = hashlib.sha256(Path(structure_path).read_bytes()).hexdigest()
    artifact_ref = record.get("artifact_ref") or {}
    return (
        record_valid and record.get("approval_status") == "APPROVED"
        and record.get("structure_sha256") == digest
        and artifact_ref.get("artifact_id") == record.get("artifact_id")
        and artifact_ref.get("sha256") == digest
        and artifact_ref.get("source_system") == "Data_analysis"
        and artifact_ref.get("verified") is True
    )
