"""Bridge candidate packages into the existing Data_analysis Artifact Registry API."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Protocol
import hashlib


class DataAnalysisArtifactAPI(Protocol):
    def register_derived_artifact(self, project_root: str, file_path: str, *,
                                  source_artifact_ids: list[str], format_id: str,
                                  provenance: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def resolve_artifact_path(self, project_root: str, artifact_id: str) -> str: ...


def register_candidate_structure(
    structure_path: str | Path, *, project_root: str | Path,
    data_analysis_api: DataAnalysisArtifactAPI, format_id: str,
    parent_artifact_ids: list[str], provenance: Mapping[str, Any],
) -> dict:
    """Register and re-resolve one candidate structure through Data_analysis.

    No local registry, direct registry JSON access or hand-created Artifact ID is used.
    """
    supplied_path = Path(structure_path)
    if supplied_path.is_symlink() or not supplied_path.is_file():
        raise ValueError("candidate structure must be a regular non-symlink file")
    path = supplied_path.resolve(strict=True)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = data_analysis_api.register_derived_artifact(
        str(Path(project_root).resolve()), str(path),
        source_artifact_ids=list(parent_artifact_ids), format_id=format_id,
        provenance=dict(provenance),
    )
    if not isinstance(result, Mapping) or not result.get("artifact_id") or not result.get("sha256"):
        raise RuntimeError("Data_analysis did not return an Artifact ID and SHA-256")
    if str(result["sha256"]).lower() != before.lower():
        raise RuntimeError("Data_analysis registered a different candidate structure SHA-256")
    resolved = Path(data_analysis_api.resolve_artifact_path(
        str(Path(project_root).resolve()), str(result["artifact_id"])
    )).resolve(strict=True)
    after = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if after.lower() != before.lower():
        raise RuntimeError("Data_analysis Artifact resolver returned bytes with a different SHA-256")
    return {
        "artifact_id": str(result["artifact_id"]), "sha256": before,
        "format_id": format_id, "uri": resolved.as_uri(),
        "source_system": "Data_analysis", "verified": True,
    }
