"""Bridge complete candidate packages into the existing Data_analysis Artifact Registry API."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Protocol
import hashlib
import json


class DataAnalysisArtifactAPI(Protocol):
    def register_derived_artifact(self, project_root: str, file_path: str, *,
                                  source_artifact_ids: list[str], format_id: str,
                                  provenance: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def resolve_artifact_path(self, project_root: str, artifact_id: str) -> str: ...


def _register_file(path: str | Path, *, project_root: str | Path,
                   data_analysis_api: DataAnalysisArtifactAPI, format_id: str,
                   parent_artifact_ids: list[str], provenance: Mapping[str, Any]) -> dict:
    supplied = Path(path)
    if supplied.is_symlink() or not supplied.is_file():
        raise ValueError("candidate package files must be regular non-symlink files")
    resolved_source = supplied.resolve(strict=True)
    before = hashlib.sha256(resolved_source.read_bytes()).hexdigest()
    result = data_analysis_api.register_derived_artifact(
        str(Path(project_root).resolve()), str(resolved_source),
        source_artifact_ids=list(parent_artifact_ids), format_id=format_id,
        provenance=dict(provenance),
    )
    if not isinstance(result, Mapping) or not result.get("artifact_id") or not result.get("sha256"):
        raise RuntimeError("Data_analysis did not return an Artifact ID and SHA-256")
    if str(result["sha256"]).lower() != before.lower():
        raise RuntimeError("Data_analysis registered bytes with a different SHA-256")
    resolved = Path(data_analysis_api.resolve_artifact_path(
        str(Path(project_root).resolve()), str(result["artifact_id"])
    )).resolve(strict=True)
    after = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if after.lower() != before.lower():
        raise RuntimeError("Data_analysis resolver returned bytes with a different SHA-256")
    return {"artifact_id": str(result["artifact_id"]), "sha256": before,
            "format_id": format_id, "uri": resolved.as_uri(),
            "source_system": "Data_analysis", "verified": True}


def register_candidate_structure(
    structure_path: str | Path, *, project_root: str | Path,
    data_analysis_api: DataAnalysisArtifactAPI, format_id: str,
    parent_artifact_ids: list[str], provenance: Mapping[str, Any],
) -> dict:
    """Compatibility helper for registering only the structure file."""
    return _register_file(structure_path, project_root=project_root,
        data_analysis_api=data_analysis_api, format_id=format_id,
        parent_artifact_ids=parent_artifact_ids, provenance=provenance)


def register_candidate_package(
    candidate, validation_report: Mapping[str, Any], *, project_root: str | Path,
    data_analysis_api: DataAnalysisArtifactAPI, format_ids: Mapping[str, str],
    parent_artifact_ids: list[str],
) -> dict:
    """Register structure, topology, metadata and validation report as Data_analysis Artifacts."""
    if validation_report.get("status") != "PASS":
        raise ValueError("candidate package registration requires a passing validation report")
    structure_hash = hashlib.sha256(candidate.structure_path.read_bytes()).hexdigest()
    if validation_report.get("structure_sha256") != structure_hash:
        raise ValueError("validation report does not match current candidate structure bytes")
    validation_path = candidate.structure_path.parent / "validation_report.json"
    validation_path.write_text(json.dumps(dict(validation_report), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    files = {
        "structure": candidate.structure_path,
        "topology": candidate.topology_path,
        "metadata": candidate.metadata_path,
        "validation_report": validation_path,
    }
    registered = {}
    for role, file_path in files.items():
        format_id = str(format_ids.get(role, ""))
        if not format_id:
            raise ValueError(f"Data_analysis format_id for candidate {role} is required")
        registered[role] = _register_file(
            file_path, project_root=project_root, data_analysis_api=data_analysis_api,
            format_id=format_id, parent_artifact_ids=parent_artifact_ids,
            provenance={"candidate_id": candidate.candidate_id, "artifact_role": role,
                        "structure_sha256": structure_hash},
        )
    return {"candidate_id": candidate.candidate_id, "artifacts": registered,
            "structure_artifact": registered["structure"]}
