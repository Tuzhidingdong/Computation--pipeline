"""Human-review package builder for validated model candidates."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, Sequence
import json


def build_review_package(
    candidates: Sequence[Mapping[str, Any]], output_dir: str | Path, *,
    preview_renderer=None,
) -> Path:
    """Create a review index; preview generation is delegated to a real renderer."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in candidates:
        candidate_id = str(item["candidate_id"])
        validation = dict(item.get("validation_report") or {})
        if validation.get("status") != "PASS":
            raise ValueError(f"{candidate_id}: review package cannot label an unvalidated candidate as valid")
        preview = None
        if preview_renderer is not None:
            preview_path = root / f"{candidate_id}.png"
            preview_renderer(item, preview_path)
            if not preview_path.is_file() or preview_path.stat().st_size == 0:
                raise RuntimeError(f"{candidate_id}: preview renderer did not create a non-empty image")
            preview = preview_path.name
        entries.append({
            "candidate_id": candidate_id, "artifact": dict(item.get("artifact") or {}),
            "structure_sha256": validation.get("structure_sha256"),
            "composition": validation.get("composition"), "formula": validation.get("formula"),
            "atom_count": validation.get("atom_count"), "charge": validation.get("charge"),
            "pseudopotential_electron_count": validation.get("pseudopotential_electron_count"),
            "multiplicity": validation.get("multiplicity"), "coordination": item.get("coordination", []),
            "differences": item.get("differences", []), "validation_report": validation,
            "preview": preview,
        })
    package = {
        "schema_version": "1.0.0", "review_status": "AWAITING_USER_REVIEW",
        "candidate_count": len(entries), "candidates": entries,
        "unresolved_scientific_definitions": [],
    }
    target = root / "model_review_package.json"
    target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
