"""Evidence-preserving Project Manifest extraction and conflict diagnostics."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, Iterable
from .docx_reader import ExtractedBlock

MANIFEST_SCHEMA_VERSION = "1.0.0"
_NUMBER_UNIT = re.compile(
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>eV/Å|eV/Angstrom|eV|Ha|hartree|Ry|K|Å|angstrom|nm|ps|fs|meV|Bohr|"
    r"Bohr\^3|e/Bohr\^3|V|%|atoms?|candidates?|orientations?)\b", re.IGNORECASE
)
_LABEL_VALUE = re.compile(r"^\s*(?P<label>[^:：=]{2,100})\s*[:：=]\s*(?P<value>.+?)\s*$")


@dataclass(frozen=True)
class CompilationDiagnostic:
    code: str
    severity: str
    message: str
    field: str | None = None
    evidence_ids: tuple[str, ...] = ()
    blocks_execution: bool = False

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "field": self.field, "evidence_ids": list(self.evidence_ids),
                "blocks_execution": self.blocks_execution}


def _normalise_label(value: str) -> str:
    value = re.sub(r"\s+", "_", value.strip().lower())
    return re.sub(r"[^a-z0-9_]+", "", value).strip("_")


def _evidence(block: ExtractedBlock, index: int) -> dict:
    return {"evidence_id": f"docx-block-{index:06d}", "source": block.location,
            "block_kind": block.kind, "style": block.style,
            "list_info": block.list_info, "text": block.text}


def detect_conflicts(claims: Iterable[dict]) -> list[CompilationDiagnostic]:
    grouped: dict[str, list[dict]] = {}
    for claim in claims:
        if claim.get("field"):
            grouped.setdefault(claim["field"], []).append(claim)
    diagnostics = []
    for field, items in grouped.items():
        values = {str(item.get("value", "")).strip().casefold() for item in items}
        if len(values) > 1:
            diagnostics.append(CompilationDiagnostic(
                "PLAN_FIELD_CONFLICT", "error",
                f"Multiple source values were found for '{field}'; no value was selected.",
                field, tuple(item["evidence_id"] for item in items), True))
    return diagnostics


def extract_claims(blocks: Iterable[ExtractedBlock]) -> tuple[list[dict], list[dict], list[dict]]:
    claims: list[dict] = []
    evidence: list[dict] = []
    table_rows: dict[tuple, list[tuple[ExtractedBlock, dict]]] = {}
    for index, block in enumerate(blocks, start=1):
        ev = _evidence(block, index)
        evidence.append(ev)
        if block.kind == "table_cell":
            key = (block.location.get("table"), block.location.get("row"))
            table_rows.setdefault(key, []).append((block, ev))
        text = block.text.strip()
        if not text:
            continue
        match = _LABEL_VALUE.match(text)
        if match:
            label, value = match.group("label").strip(), match.group("value").strip()
            claims.append({"field": _normalise_label(label), "label": label, "value": value,
                "unit": None, "status": "requires_confirmation", "evidence_id": ev["evidence_id"],
                "source": block.location, "source_text": block.text})
        for number in _NUMBER_UNIT.finditer(text):
            claims.append({"field": None, "label": None, "value": number.group("value"),
                "unit": number.group("unit"), "status": "mention_only",
                "evidence_id": ev["evidence_id"], "source": block.location,
                "source_text": block.text})
    # A two-or-more-cell row commonly stores a field name in column 1 and its value after it.
    for cells in table_rows.values():
        cells.sort(key=lambda pair: int(pair[0].location.get("column", 0)))
        if len(cells) < 2:
            continue
        label = cells[0][0].text.strip()
        value = " | ".join(pair[0].text.strip() for pair in cells[1:]).strip()
        if label and value and not _LABEL_VALUE.match(label):
            claims.append({"field": _normalise_label(label), "label": label, "value": value,
                "unit": None, "status": "requires_confirmation",
                "evidence_id": cells[0][1]["evidence_id"], "source": cells[0][0].location,
                "source_text": " | ".join(pair[0].text for pair in cells)})
    diagnostics = detect_conflicts(claims)
    return claims, evidence, [item.as_dict() for item in diagnostics]


def build_project_manifest(blocks: list[ExtractedBlock], *, project_id: str,
                           plan_version: str | None = None) -> dict[str, Any]:
    claims, evidence, diagnostics = extract_claims(blocks)
    sections = []
    heading_stack = []
    for index, block in enumerate(blocks, start=1):
        match = re.match(r"Heading([1-9])$", str(block.style or ""), re.IGNORECASE)
        if match:
            level = int(match.group(1))
            heading_stack = heading_stack[:level - 1]
            heading_stack.append(block.text.strip())
            sections.append({"heading": block.text.strip(), "level": level,
                "path": list(heading_stack), "evidence_id": f"docx-block-{index:06d}"})
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project": {"project_id": project_id, "plan_version": plan_version, "source_format": "docx"},
        "sections": sections, "systems": [], "models": [], "method": {}, "tasks": [],
        "task_count_claims": [], "dependencies": [], "input_outputs": {}, "resources": {},
        "scientific_constraints": [], "claims": claims,
        "unresolved_definitions": [{"field": c["field"], "label": c["label"],
            "value": c["value"], "evidence_id": c["evidence_id"]}
            for c in claims if c["status"] == "requires_confirmation"],
        "evidence": evidence, "diagnostics": diagnostics,
        "compilation_status": "BLOCKED" if any(d["blocks_execution"] for d in diagnostics)
                              else "NEEDS_REVIEW",
    }
