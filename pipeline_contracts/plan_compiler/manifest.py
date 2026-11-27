"""Evidence-preserving Project Manifest extraction and conflict diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable

from .docx_reader import ExtractedBlock

MANIFEST_SCHEMA_VERSION = "1.0.0"
_NUMBER_UNIT = re.compile(
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>eV/Å|eV/Angstrom|eV|Ha|hartree|Ry|K|Å|angstrom|nm|ps|fs|meV|Bohr|"
    r"Bohr\^3|e/Bohr\^3|V|%|atoms?|candidates?|orientations?)\b", re.IGNORECASE
)
_LABEL_VALUE = re.compile(r"^\s*(?P<label>[^:：=]{2,100})\s*[:：=]\s*(?P<value>.+?)\s*$")
_IMPLICIT_LABEL_VALUE = re.compile(
    r"^\s*(?P<label>[A-Za-z][A-Za-z0-9_]{1,60})\s+(?P<value>\S(?:.*\S)?)\s*$"
)
_WP_HEADING = re.compile(
    r"^\s*(?:work\s*package|wp)\s*[-#]?\s*(?P<number>\d+)\s*"
    r"(?P<separator>[:.)\-–—]?\s*)(?P<title>.*)$",
    re.IGNORECASE,
)
_SYSTEM_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_]\d+[A-Za-z0-9_-]*)\b")
_DEPENDS = re.compile(
    r"\b(?P<dependent>WP\s*\d+)\s+(?:depends\s+on|is\s+dependent\s+on|requires|follows|after)\s+"
    r"(?P<prerequisite>WP\s*\d+)\b", re.IGNORECASE
)
_ARROW_DEPENDENCY = re.compile(
    r"\b(?P<upstream>WP\s*\d+)\s*(?:->|→)\s*(?P<downstream>WP\s*\d+)\b",
    re.IGNORECASE,
)

_METHOD_TERMS = (
    "engine", "code", "cp2k", "functional", "exchange_correlation", "xc",
    "dispersion", "cutoff", "added_mos", "basis", "pseudopotential", "periodicity",
    "poisson", "cell", "smearing", "temperature", "eps_scf", "scf", "hessian",
    "force_threshold", "vibrat", "frequency", "thermo", "ase", "mace", "solvation",
    "dielectric", "sccs", "che", "optimization", "optimisation", "multipole",
    "spin", "potential", "displacement", "frozen_support",
)
_MODEL_TERMS = (
    "formula", "composition", "atom_count", "number_of_atoms", "charge",
    "multiplicity", "spin", "motif", "geometry", "coordination",
    "valence_electrons", "cluster_atom_count", "cluster_formula", "support_atom_count",
    "complete_atom_count", "support_motif", "complete_formula", "donor",
    "bond", "topology", "structure",
)
_RESOURCE_TERMS = (
    "resource", "node", "cpu", "core", "thread", "memory", "ram", "walltime",
    "time_limit", "partition", "queue", "gpu", "scratch", "disk", "account",
)
_INPUT_TERMS = ("input", "source_file", "source_data", "starting_structure")
_OUTPUT_TERMS = ("output", "result_file", "artifact", "copyready", "report", "text")
_COUNT_TERMS = ("count", "number", "total", "candidate", "orientation", "structure_count")
_CONSTRAINT_TERMS = ("constraint", "prohibited", "forbidden", "must_not", "excluded")


@dataclass(frozen=True)
class CompilationDiagnostic:
    code: str
    severity: str
    message: str
    field: str | None = None
    evidence_ids: tuple[str, ...] = ()
    blocks_execution: bool = False
    conflicting_values: tuple[dict, ...] = ()
    scope: dict | None = None

    def as_dict(self) -> dict:
        result = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field": self.field,
            "evidence_ids": list(self.evidence_ids),
            "blocks_execution": self.blocks_execution,
        }
        if self.scope:
            result["scope"] = dict(self.scope)
        if self.conflicting_values:
            result["conflicting_values"] = [dict(item) for item in self.conflicting_values]
        return result


def _normalise_label(value: str) -> str:
    """Canonicalise a field name without changing the field's scientific meaning."""
    value = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    value = re.sub(r"[\s\-]+", "_", value)
    value = re.sub(r"[^a-z0-9_]+", "", value)
    return re.sub(r"_+", "_", value).strip("_")


def _normalise_field_value(value: Any) -> str:
    """Normalise presentation only; preserve numbers, units, punctuation and operators."""
    value = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    value = re.sub(r"\s+", " ", value)
    # Spaces around operators/delimiters and between a number and its unit are
    # formatting only. The unit token and numeric magnitude remain unchanged.
    value = re.sub(r"\s*([=,:;()\[\]{}+\-*/])\s*", r"\1", value)
    value = re.sub(
        r"(?<=\d)\s+(?=(?:ev|ha|hartree|ry|k|å|angstrom|nm|ps|fs|mev|bohr|v|atoms?|"
        r"candidates?|orientations?)\b)",
        "",
        value,
    )
    return value


def _evidence(block: ExtractedBlock, index: int) -> dict:
    return {
        "evidence_id": f"docx-block-{index:06d}",
        "source": dict(block.location),
        "block_kind": block.kind,
        "style": block.style,
        "list_info": block.list_info,
        "text": block.text,
    }


def _claim_evidence_ids(claim: dict) -> list[str]:
    ids = claim.get("evidence_ids")
    if isinstance(ids, list) and ids:
        return [str(item) for item in ids]
    evidence_id = claim.get("evidence_id")
    return [str(evidence_id)] if evidence_id else []


def _claim_source_records(claim: dict) -> list[dict]:
    ids = _claim_evidence_ids(claim)
    sources = claim.get("sources")
    if isinstance(sources, list) and sources:
        return [
            {
                "evidence_id": str(item.get("evidence_id")),
                "source": dict(item.get("source") or {}),
                "source_text": item.get("source_text", claim.get("source_text", "")),
                "raw_value": claim.get("value", ""),
            }
            for item in sources
        ]
    return [
        {
            "evidence_id": evidence_id,
            "source": dict(claim.get("source") or {}),
            "source_text": claim.get("source_text", ""),
            "raw_value": claim.get("value", ""),
        }
        for evidence_id in ids
    ]



def _claim_label_identity(claim: dict) -> str:
    """Preserve meaningful non-ASCII label words when distinguishing prose claims."""
    label = unicodedata.normalize("NFKC", str(claim.get("label") or "")).casefold()
    return "".join(char for char in label if char.isalnum())


def _charge_value_and_explanation(label: str, value: str) -> tuple[str, str | None]:
    """Separate a scalar CHARGE value from its following explanatory sentence."""
    if _normalise_label(label) != "charge":
        return value, None
    match = re.match(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*[;；]\s*(.+?)\s*$", value, re.S)
    if not match:
        return value, None
    return match.group(1), match.group(2)


def _append_inline_claim(claims: list[dict], block: ExtractedBlock, index: int,
                         context: dict, field: str, value: Any, *, label: str | None = None,
                         unit: str | None = None) -> None:
    evidence_id = f"docx-block-{index:06d}"
    for existing in claims:
        if (existing.get("field") == field
                and evidence_id in _claim_evidence_ids(existing)
                and _normalise_field_value(existing.get("value", "")) == _normalise_field_value(value)):
            return
    claims.append({
        "field": field, "label": label or field, "value": value, "unit": unit,
        "status": "requires_confirmation", "evidence_id": evidence_id,
        "evidence_ids": [evidence_id], "source": dict(block.location),
        "source_text": block.text, "context": dict(context),
    })


def _extract_explicit_inline_claims(blocks: list[ExtractedBlock], contexts: dict[str, dict],
                                    claims: list[dict]) -> None:
    """Extract only explicit machine keywords and unambiguous labelled quantities."""
    patterns = [
        ("xc", re.compile(r"\bXC_FUNCTIONAL\s+(PBE)\b", re.I), lambda m: m.group(1).upper()),
        ("dispersion", re.compile(r"\bTYPE\s+DFTD3\s*\(\s*BJ\s*\)", re.I), lambda m: "D3(BJ)"),
        ("cutoff_ry", re.compile(r"\b(?:CUTOFF|density cutoff of)\s*(\d+(?:\.\d+)?)\s*Ry\b", re.I), lambda m: f"{m.group(1)} Ry"),
        ("rel_cutoff_ry", re.compile(r"\b(?:REL_CUTOFF|relative cutoff of)\s*(\d+(?:\.\d+)?)\s*Ry\b", re.I), lambda m: f"{m.group(1)} Ry"),
        ("spin_polarized", re.compile(r"\bUKS\s+\.TRUE\.", re.I), lambda m: "true"),
        ("smearing_temperature_K", re.compile(r"\bELECTRONIC_TEMP\s+(\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)} K"),
        ("added_mos", re.compile(r"\bADDED_MOS\s+(\d+)\b", re.I), lambda m: m.group(1)),
        ("periodicity", re.compile(r"\bPERIODIC\s+NONE\b", re.I), lambda m: "NONE"),
        ("poisson_solver", re.compile(r"\bMartyna[- ]Tuckerman\b", re.I), lambda m: "MT"),
        ("sccs_dielectric", re.compile(r"\bSCCS\b.{0,40}?ε\s*=\s*(\d+(?:\.\d+)?)", re.I | re.S), lambda m: m.group(1)),
        ("basis_sensitivity", re.compile(r"\b(TZV2P)(?:-MOLOPT-GTH)?\b", re.I), lambda m: "TZV2P"),
        ("engine", re.compile(r"\b(?:CP2K.{0,100}?Quickstep.{0,100}?GPW|Quickstep.{0,100}?CP2K.{0,100}?GPW)\b", re.I | re.S), lambda m: "CP2K Quickstep / GPW"),
        ("force_threshold_ev_per_angstrom", re.compile(r"(?:force threshold|MAX_FORCE).{0,100}?(?:~|<|≤)?\s*(0?\.\d+)\s*eV/Å", re.I | re.S), lambda m: f"{m.group(1)} eV/Å"),
        ("che_temperature_K", re.compile(r"\bT\s*=\s*(\d+(?:\.\d+)?)\s*K\b", re.I), lambda m: f"{m.group(1)} K"),
        ("potential_v_vs_rhe", re.compile(r"\bU\s*=\s*([+-]?\d+(?:\.\d+)?)\s*V\s*vs\.?\s*RHE\b", re.I), lambda m: f"{m.group(1)} V"),
    ]
    rows: dict[tuple, list[tuple[int, ExtractedBlock]]] = {}
    for index, block in enumerate(blocks, start=1):
        text = block.text
        if not text.strip():
            continue
        evidence_id = f"docx-block-{index:06d}"
        context = contexts[evidence_id]
        for field, pattern, render in patterns:
            for match in pattern.finditer(text):
                _append_inline_claim(claims, block, index, context, field, render(match))

        if re.search(r"\bEPS_SCF\b", text, re.I):
            for field, pattern in (
                ("eps_scf_geometry_optimization", r"(1\.0E-\d+)\s*\((?:优化/静态|geometry\s*optimization)\)"),
                ("eps_scf_local_hessian_force", r"(1\.0E-\d+)\s*\((?:力计算|force\s*calculation)\)"),
            ):
                match = re.search(pattern, text, re.I)
                if match:
                    _append_inline_claim(claims, block, index, context, field, match.group(1))

        if re.search(r"(?:finite displacement|有限位移|Vibrations)", text, re.I):
            displacement = re.search(r"±\s*(\d+(?:\.\d+)?)\s*Å", text, re.I)
            if displacement:
                _append_inline_claim(claims, block, index, context, "displacement_angstrom", f"{displacement.group(1)} Å")
            if re.search(r"冻结(?:基底|支持体)|frozen support", text, re.I):
                _append_inline_claim(claims, block, index, context, "frozen_support_and_Cu13", "true")

        if re.search(r"\d+(?:\.\d+)?\s*Å\s*vs\.?\s*\d+(?:\.\d+)?\s*Å", text, re.I) or re.search(r"(?:双盒子|cell|box|超胞).{0,100}(?:vs\.?|与|and)", text, re.I | re.S):
            sizes = list(dict.fromkeys(re.findall(r"(\d+(?:\.\d+)?)\s*Å", text, re.I)))
            if len(sizes) >= 2:
                _append_inline_claim(claims, block, index, context, "cell_sizes_angstrom", sizes[:2])

        markers = list(re.finditer(r"\b(Cu-20|SnCu-20)\s*:", text, re.I))
        for marker_index, marker in enumerate(markers):
            system_id = marker.group(1)
            end = markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
            segment = text[marker.end():end]
            scoped_context = dict(context)
            scoped_context["system_id"] = system_id
            motif_match = re.match(r"\s*(.+?)\s*,\s*\d+\s+support atoms", segment, re.I | re.S)
            if motif_match:
                motif_and_cluster = motif_match.group(1).strip()
                motif = re.split(r"\s*\+\s*Cu13\b", motif_and_cluster, maxsplit=1, flags=re.I)[0].strip()
                _append_inline_claim(claims, block, index, scoped_context, "support_motif", motif)
                _append_inline_claim(claims, block, index, scoped_context, "cluster_formula", "Cu13")
            quantities = (
                ("support_atom_count", r"(\d+)\s+support atoms\b"),
                ("cluster_atom_count", r"(\d+)\s+cluster atoms\b"),
                ("complete_atom_count", r"=\s*(\d+)\s+atoms\b"),
                ("explicit_valence_electrons", r"(\d+)\s+valence electrons\b"),
                ("charge", r"net charge\s+([+-]?\d+(?:\.\d+)?)\b"),
            )
            for field, pattern in quantities:
                found = re.search(pattern, segment, re.I)
                if found:
                    _append_inline_claim(claims, block, index, scoped_context, field, found.group(1))

    for index, block in enumerate(blocks, start=1):
        if block.kind == "table_cell":
            rows.setdefault((block.location.get("table"), block.location.get("row")), []).append((index, block))
    for cells in rows.values():
        cells.sort(key=lambda pair: int(pair[1].location.get("column", 0)))
        if not cells or not re.search(r"\bWP\s*4\b", cells[0][1].text, re.I):
            continue
        for index, block in cells[1:]:
            context = dict(contexts[f"docx-block-{index:06d}"])
            context["work_package"] = "WP4"
            calls = re.search(r"(\d+)\s*次?\s*(?:快速)?单点力调用", block.text)
            if calls:
                _append_inline_claim(claims, block, index, context, "total_force_evaluations", calls.group(1))
            states = re.search(r"(\d+)\s*个吸附态", block.text)
            if states:
                _append_inline_claim(claims, block, index, context, "adsorbed_state_hessians", states.group(1))


def detect_conflicts(claims: Iterable[dict]) -> list[CompilationDiagnostic]:
    """Compare claims within the same field, label and explicit system/WP scope."""
    grouped: dict[tuple[str, str, str, str], list[dict]] = {}
    for claim in claims:
        field = claim.get("field")
        if not field or _field_category(str(field)) == "outputs":
            continue
        context = claim.get("context") or {}
        system_id = str(context.get("system_id") or "")
        work_package = str(context.get("work_package") or "")
        label_identity = _claim_label_identity(claim) or _normalise_label(str(field))
        identity = (
            _normalise_label(str(field)), label_identity,
            _normalise_label(system_id), _normalise_label(work_package),
        )
        grouped.setdefault(identity, []).append(claim)

    diagnostics: list[CompilationDiagnostic] = []
    for (field, _label_identity, system_id, work_package), items in grouped.items():
        value_groups: dict[str, list[dict]] = {}
        for item in items:
            normalised = _normalise_field_value(item.get("value", ""))
            value_groups.setdefault(normalised, []).append(item)
        if len(value_groups) <= 1:
            continue
        conflicting_values = []
        all_evidence_ids: list[str] = []
        for normalised_value, value_claims in value_groups.items():
            raw_values = []
            evidence_records = []
            for item in value_claims:
                raw_value = str(item.get("value", ""))
                if raw_value not in raw_values:
                    raw_values.append(raw_value)
                for evidence_record in _claim_source_records(item):
                    evidence_records.append(evidence_record)
                    evidence_id = evidence_record.get("evidence_id")
                    if evidence_id and evidence_id not in all_evidence_ids:
                        all_evidence_ids.append(evidence_id)
            conflicting_values.append({
                "normalised_value": normalised_value,
                "raw_values": raw_values,
                "evidence": evidence_records,
            })
        diagnostics.append(CompilationDiagnostic(
            "PLAN_FIELD_CONFLICT", "error",
            f"Multiple semantically different source values were found for '{field}'; no value was selected.",
            field, tuple(all_evidence_ids), True, tuple(conflicting_values),
            {
                "system_id": (items[0].get("context") or {}).get("system_id"),
                "work_package": (items[0].get("context") or {}).get("work_package"),
            } if system_id or work_package else None,
        ))
    return diagnostics


def _parse_label_value(text: str) -> tuple[str, str] | None:
    match = _LABEL_VALUE.match(text)
    if match:
        return match.group("label").strip(), match.group("value").strip()

    match = _IMPLICIT_LABEL_VALUE.match(text)
    if not match:
        return None
    label = match.group("label").strip()
    value = match.group("value").strip()
    # The no-delimiter form is accepted only for unambiguous machine-style keys
    # (for example ADDED_MOS 80 or ase_vibrations__cp2k on/off), not prose.
    if "_" not in label and not label.isupper():
        return None
    if re.fullmatch(r"WP\d+", label, re.IGNORECASE):
        return None
    return label, value


def _normalise_wp(value: str) -> str:
    match = re.search(r"WP\s*(\d+)", value, re.IGNORECASE)
    return f"WP{int(match.group(1))}" if match else value.strip()


def _numbered_section(text: str) -> tuple[int, str] | None:
    """Recognise explicit Chinese or decimal section numbering, not ordinary lists."""
    chinese = re.match(r"^\\s*([一二三四五六七八九十]+)、\\s*(\\S.*)$", text)
    if chinese:
        return 1, chinese.group(2).strip()
    decimal = re.match(r"^\\s*(\\d+(?:\\.\\d+)+)\\s+(\\S.*)$", text)
    if decimal:
        return decimal.group(1).count(".") + 1, decimal.group(2).strip()
    return None


def _system_id_from_heading(text: str) -> str | None:
    for match in _SYSTEM_ID.finditer(text):
        value = match.group(0)
        if not value.upper().startswith("WP"):
            return value
    return None


def _build_block_contexts(blocks: list[ExtractedBlock]) -> dict[str, dict]:
    contexts: dict[str, dict] = {}
    heading_stack: list[str] = []
    current_system: str | None = None
    current_wp: str | None = None

    for index, block in enumerate(blocks, start=1):
        text = block.text.strip()
        evidence_id = f"docx-block-{index:06d}"
        style_match = re.fullmatch(r"Heading([1-9])", str(block.style or ""), re.IGNORECASE)
        numbered = _numbered_section(text) if text else None
        wp_match = _WP_HEADING.match(text) if text else None
        if style_match or numbered:
            level = int(style_match.group(1)) if style_match else numbered[0]
            title = text if style_match else numbered[1]
            heading_stack = heading_stack[:level - 1]
            if title:
                heading_stack.append(title)
            if level == 1:
                current_system = None
                current_wp = None
            candidate_system = _system_id_from_heading(title)
            if candidate_system:
                current_system = candidate_system
        if wp_match:
            current_wp = f"WP{int(wp_match.group('number'))}"
            if not (style_match or numbered):
                heading_stack.append(text)
        parsed = _parse_label_value(text) if text else None
        if parsed and _normalise_label(parsed[0]) in {"system", "system_id", "catalyst", "model_id"}:
            current_system = parsed[1].strip()
        contexts[evidence_id] = {
            "section_path": list(heading_stack),
            "system_id": current_system,
            "work_package": current_wp,
        }

    # A table row label may explicitly name WP1–WP5 after a phase prefix.
    # Apply that scope to the row only; never propagate it to following prose.
    rows: dict[tuple, list[tuple[int, ExtractedBlock]]] = {}
    for index, block in enumerate(blocks, start=1):
        if block.kind == "table_cell":
            rows.setdefault((block.location.get("table"), block.location.get("row")), []).append((index, block))
    for cells in rows.values():
        cells.sort(key=lambda pair: int(pair[1].location.get("column", 0)))
        if not cells:
            continue
        match = re.search(r"\\bWP\\s*(\\d+)\\b", cells[0][1].text, re.I)
        if match:
            work_package = f"WP{int(match.group(1))}"
            for index, _block in cells:
                contexts[f"docx-block-{index:06d}"]["work_package"] = work_package
    return contexts


def extract_claims(blocks: Iterable[ExtractedBlock]) -> tuple[list[dict], list[dict], list[dict]]:
    blocks = list(blocks)
    claims: list[dict] = []
    evidence: list[dict] = []
    table_rows: dict[tuple, list[tuple[ExtractedBlock, dict]]] = {}
    contexts = _build_block_contexts(blocks)

    for index, block in enumerate(blocks, start=1):
        ev = _evidence(block, index)
        evidence.append(ev)
        if block.kind == "table_cell":
            key = (block.location.get("table"), block.location.get("row"))
            table_rows.setdefault(key, []).append((block, ev))

        text = block.text.strip()
        if not text:
            continue
        parsed = _parse_label_value(text)
        if parsed:
            label, value = parsed
            value, explanation = _charge_value_and_explanation(label, value)
            evidence_ids = [ev["evidence_id"]]
            claim = {
                "field": _normalise_label(label),
                "label": label,
                "value": value,
                "unit": None,
                "status": "requires_confirmation",
                "evidence_id": ev["evidence_id"],
                "evidence_ids": evidence_ids,
                "source": dict(block.location),
                "source_text": block.text,
                "context": dict(contexts[ev["evidence_id"]]),
            }
            if explanation:
                claim["value_explanation"] = explanation
            claims.append(claim)
        for number in _NUMBER_UNIT.finditer(text):
            claims.append({
                "field": None,
                "label": None,
                "value": number.group("value"),
                "unit": number.group("unit"),
                "status": "mention_only",
                "evidence_id": ev["evidence_id"],
                "evidence_ids": [ev["evidence_id"]],
                "source": dict(block.location),
                "source_text": block.text,
                "context": dict(contexts[ev["evidence_id"]]),
            })

    # A table row is a single assertion backed by every cell that contributed to
    # its label/value pair. Keep cell-level evidence rather than citing only column 1.
    for cells in table_rows.values():
        cells.sort(key=lambda pair: int(pair[0].location.get("column", 0)))
        if len(cells) < 2:
            continue
        label = cells[0][0].text.strip()
        value = " | ".join(pair[0].text.strip() for pair in cells[1:]).strip()
        if label and value and not _parse_label_value(label):
            evidence_ids = [pair[1]["evidence_id"] for pair in cells]
            sources = [
                {
                    "evidence_id": pair[1]["evidence_id"],
                    "source": dict(pair[0].location),
                    "source_text": pair[0].text,
                }
                for pair in cells
            ]
            claims.append({
                "field": _normalise_label(label),
                "label": label,
                "value": value,
                "unit": None,
                "status": "requires_confirmation",
                "evidence_id": evidence_ids[0],
                "evidence_ids": evidence_ids,
                "source": dict(cells[0][0].location),
                "source_text": " | ".join(pair[0].text for pair in cells),
                "sources": sources,
                "context": dict(contexts[evidence_ids[0]]),
            })

    _extract_explicit_inline_claims(blocks, contexts, claims)
    diagnostics = detect_conflicts(claims)
    return claims, evidence, [item.as_dict() for item in diagnostics]


def _field_category(field: str) -> str | None:
    key = _normalise_label(field)
    if any(term in key for term in ("depend", "prerequisite", "predecessor", "successor")):
        return "dependencies"
    if any(term in key for term in _RESOURCE_TERMS):
        return "resources"
    if any(term in key for term in _INPUT_TERMS):
        return "inputs"
    if any(term in key for term in _OUTPUT_TERMS):
        return "outputs"
    if key in {"system", "system_id", "catalyst", "model_id"}:
        return "systems"
    if any(term in key for term in _METHOD_TERMS):
        return "method"
    if any(term in key for term in _MODEL_TERMS):
        return "models"
    if any(term in key for term in _COUNT_TERMS):
        return "task_count_claims"
    if any(term in key for term in _CONSTRAINT_TERMS):
        return "scientific_constraints"
    return None


def _ids_from_claims(items: list[dict]) -> list[str]:
    result = []
    for item in items:
        for evidence_id in _claim_evidence_ids(item):
            if evidence_id not in result:
                result.append(evidence_id)
    return result




def _collect_evidence_ids(value: Any) -> list[str]:
    """Collect evidence references recursively from structured manifest values."""
    found: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            evidence_ids = item.get("evidence_ids")
            if isinstance(evidence_ids, list):
                for evidence_id in evidence_ids:
                    if evidence_id and str(evidence_id) not in found:
                        found.append(str(evidence_id))
            evidence_id = item.get("evidence_id")
            if evidence_id and str(evidence_id) not in found:
                found.append(str(evidence_id))
            for key, child in item.items():
                if key not in {"evidence_id", "evidence_ids"}:
                    visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return found


def _structured_value(claim: dict) -> dict:
    return {
        "value": claim.get("value"),
        "label": claim.get("label"),
        "evidence_ids": _claim_evidence_ids(claim),
        "source": dict(claim.get("source") or {}),
        "source_text": claim.get("source_text", ""),
        "status": claim.get("status", "requires_confirmation"),
    }


def _provenance(status: str, evidence_ids: list[str] | None = None,
                raw_values: list[Any] | None = None, **extra: Any) -> dict:
    return {
        "status": status,
        "source_kind": "docx_evidence" if status == "docx_evidence" else status,
        "evidence_ids": list(evidence_ids or []),
        "raw_values": list(raw_values or []),
        **extra,
    }


def _add_field_provenance(target: dict, path: str, records: list[dict]) -> None:
    existing = target.get(path, {})
    evidence_ids = list(existing.get("evidence_ids", []))
    raw_values = list(existing.get("raw_values", []))
    for evidence_id in _ids_from_claims(records):
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    for item in records:
        value = item.get("value")
        if value not in raw_values:
            raw_values.append(value)
    target[path] = _provenance("docx_evidence", evidence_ids, raw_values)


def _heading_sections(blocks: list[ExtractedBlock]) -> list[dict]:
    sections = []
    heading_stack: list[str] = []
    for index, block in enumerate(blocks, start=1):
        style_match = re.fullmatch(r"Heading([1-9])", str(block.style or ""), re.IGNORECASE)
        numbered = _numbered_section(block.text.strip())
        if not style_match and not numbered:
            continue
        level = int(style_match.group(1)) if style_match else numbered[0]
        heading = block.text.strip() if style_match else numbered[1]
        heading_stack = heading_stack[:level - 1]
        heading_stack.append(heading)
        sections.append({
            "heading": heading, "level": level, "path": list(heading_stack),
            "evidence_id": f"docx-block-{index:06d}",
            "source": dict(block.location),
            "heading_source": "word_style" if style_match else "explicit_numbering",
        })
    return sections


def build_project_manifest(blocks: list[ExtractedBlock], *, project_id: str,
                           plan_version: str | None = None) -> dict[str, Any]:
    blocks = list(blocks)
    claims, evidence, diagnostics = extract_claims(blocks)
    sections = _heading_sections(blocks)
    contexts = _build_block_contexts(blocks)
    evidence_by_id = {item["evidence_id"]: item for item in evidence}

    systems_by_id: dict[str, dict] = {}
    models_by_id: dict[str, dict] = {}
    method_claims: dict[str, list[dict]] = {}
    task_count_claims: list[dict] = []
    dependencies: list[dict] = []
    inputs: list[dict] = []
    outputs: list[dict] = []
    resources: dict[str, list[dict]] = {}
    scientific_constraints: list[dict] = []
    unresolved_structured_fields: list[dict] = []
    field_provenance: dict[str, dict] = {}

    for item in evidence:
        text = item.get("text", "")
        markers = list(re.finditer(r"\\b(Cu-20|SnCu-20)\\s*:", text, re.I))
        if len(markers) < 2:
            continue
        for marker_index, marker in enumerate(markers):
            system_id = marker.group(1)
            end = markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
            segment = text[marker.start():end]
            unresolved_structured_fields.append({
                "field": "systems.complete_formula", "status": "unresolved",
                "reason": "The DOCX gives a support motif plus Cu13 and aggregate counts, but no single complete-formula string.",
                "evidence_ids": [item["evidence_id"]], "source": dict(item.get("source") or {}),
                "source_text": segment, "system_id": system_id,
            })

    spin_cells = [item for item in evidence if item.get("source", {}).get("table") == 5
                  and item.get("source", {}).get("row") == 6]
    if spin_cells and any(re.search(r"M\\s*=", item.get("text", ""), re.I) for item in spin_cells):
        unresolved_structured_fields.append({
            "field": "systems.cluster.multiplicities", "status": "unresolved",
            "reason": "Spin multiplicities are listed, but the table headers do not establish safe per-system column ownership.",
            "evidence_ids": [item["evidence_id"] for item in spin_cells],
            "source_text": " | ".join(item.get("text", "") for item in spin_cells),
        })

    # A system identifier in a source heading or explicit System/Catalyst label is
    # itself structured data with its own evidence. It is not supplied by the profile.
    for evidence_id, context in contexts.items():
        system_id = context.get("system_id")
        if system_id:
            record = systems_by_id.setdefault(system_id, {"system_id": system_id, "evidence_ids": []})
            if evidence_id not in record["evidence_ids"]:
                record["evidence_ids"].append(evidence_id)
    for claim in claims:
        system_id = (claim.get("context") or {}).get("system_id")
        if system_id:
            record = systems_by_id.setdefault(system_id, {"system_id": system_id, "evidence_ids": []})
            for evidence_id in _claim_evidence_ids(claim):
                if evidence_id not in record["evidence_ids"]:
                    record["evidence_ids"].append(evidence_id)

    for claim in claims:
        field = claim.get("field")
        if not field:
            continue
        category = _field_category(field)
        record = _structured_value(claim)
        context = claim.get("context") or {}
        system_id = context.get("system_id")

        if category == "method":
            method_claims.setdefault(field, []).append(claim)
            _add_field_provenance(field_provenance, f"method.{field}", [claim])
        elif category == "models":
            if system_id:
                model = models_by_id.setdefault(system_id, {
                    "model_id": system_id, "properties": {}, "evidence_ids": [],
                })
                model["properties"].setdefault(field, []).append(record)
                for evidence_id in _claim_evidence_ids(claim):
                    if evidence_id not in model["evidence_ids"]:
                        model["evidence_ids"].append(evidence_id)
                _add_field_provenance(field_provenance, f"models.{system_id}.{field}", [claim])
            else:
                unresolved_structured_fields.append({
                    "field": f"models.{field}", "status": "unresolved",
                    "reason": "The DOCX contains a model-related value but no unambiguous model/system context.",
                    "evidence_ids": _claim_evidence_ids(claim),
                    "source_text": claim.get("source_text", ""),
                })
        elif category == "systems" and field in {"system", "system_id", "catalyst", "model_id"}:
            value = str(claim.get("value", "")).strip()
            if value:
                system = systems_by_id.setdefault(value, {"system_id": value, "evidence_ids": []})
                for evidence_id in _claim_evidence_ids(claim):
                    if evidence_id not in system["evidence_ids"]:
                        system["evidence_ids"].append(evidence_id)
                _add_field_provenance(field_provenance, f"systems.{value}.system_id", [claim])
        elif category == "task_count_claims":
            task_count_claims.append({
                "work_package": context.get("work_package"),
                **record,
            })
            _add_field_provenance(
                field_provenance,
                f"task_count_claims.{context.get('work_package') or 'unscoped'}.{field}",
                [claim],
            )
        elif category == "dependencies":
            dependent = context.get("work_package")
            prerequisite_match = re.search(r"\bWP\s*\d+\b", str(claim.get("value", "")), re.IGNORECASE)
            if prerequisite_match:
                dependencies.append({
                    "dependent": dependent,
                    "prerequisite": _normalise_wp(prerequisite_match.group(0)),
                    "evidence_ids": _claim_evidence_ids(claim),
                    "source_text": claim.get("source_text", ""),
                })
                _add_field_provenance(field_provenance, f"dependencies.{len(dependencies) - 1}", [claim])
            else:
                unresolved_structured_fields.append({
                    "field": f"dependencies.{field}", "status": "unresolved",
                    "reason": "A dependency-labelled value was found but its referenced work package could not be identified.",
                    "evidence_ids": _claim_evidence_ids(claim),
                    "source_text": claim.get("source_text", ""),
                })
        elif category == "inputs":
            inputs.append(record)
            _add_field_provenance(field_provenance, f"input_outputs.inputs.{field}", [claim])
        elif category == "outputs":
            outputs.append(record)
            _add_field_provenance(field_provenance, f"input_outputs.outputs.{field}", [claim])
        elif category == "resources":
            resources.setdefault(field, []).append(record)
            _add_field_provenance(field_provenance, f"resources.{field}", [claim])
        elif category == "scientific_constraints":
            scientific_constraints.append(record)
            _add_field_provenance(field_provenance, f"scientific_constraints.{field}", [claim])

    # Preserve WP sections and their exact source blocks; prose is not promoted to
    # executable operations or inferred dependencies.
    tasks_by_id: dict[str, dict] = {}
    for evidence_id, source_context in contexts.items():
        work_package = source_context.get("work_package")
        if not work_package:
            continue
        source = evidence_by_id[evidence_id]
        task = tasks_by_id.setdefault(work_package, {
            "work_package": work_package,
            "title": None,
            "content_blocks": [],
            "evidence_ids": [],
        })
        raw_text = source.get("text", "")
        wp_match = _WP_HEADING.match(raw_text.strip()) if raw_text.strip() else None
        if wp_match and wp_match.group("title").strip() and not task["title"]:
            task["title"] = wp_match.group("title").strip()
        task["content_blocks"].append({
            "text": raw_text,
            "evidence_id": evidence_id,
            "source": dict(source.get("source") or {}),
            "block_kind": source.get("block_kind"),
        })
        task["evidence_ids"].append(evidence_id)
    for work_package, task in tasks_by_id.items():
        task["evidence_ids"] = list(dict.fromkeys(task["evidence_ids"]))
        field_provenance[f"tasks.{work_package}"] = _provenance(
            "docx_evidence", task["evidence_ids"],
            [item["text"] for item in task["content_blocks"]],
        )

    # Explicit prose relations are captured as dependencies with both endpoints;
    # unsupported natural-language references remain ordinary evidence/claims.
    for index, block in enumerate(blocks, start=1):
        text = block.text
        evidence_id = f"docx-block-{index:06d}"
        for match in _DEPENDS.finditer(text):
            dependencies.append({
                "dependent": _normalise_wp(match.group("dependent")),
                "prerequisite": _normalise_wp(match.group("prerequisite")),
                "evidence_ids": [evidence_id],
                "source_text": text,
                "relation": "depends_on",
            })
            _add_field_provenance(field_provenance, f"dependencies.{len(dependencies) - 1}", [{
                "evidence_id": evidence_id, "evidence_ids": [evidence_id], "value": text,
            }])
        for match in _ARROW_DEPENDENCY.finditer(text):
            dependencies.append({
                "upstream": _normalise_wp(match.group("upstream")),
                "downstream": _normalise_wp(match.group("downstream")),
                "evidence_ids": [evidence_id],
                "source_text": text,
                "relation": "precedes",
            })
            _add_field_provenance(field_provenance, f"dependencies.{len(dependencies) - 1}", [{
                "evidence_id": evidence_id, "evidence_ids": [evidence_id], "value": text,
            }])

    # Detect domain-specific structured cues that do not have a reliable label/value
    # relation. Their evidence is exposed as unresolved instead of guessed into fields.
    cue_patterns = {
        "method": re.compile(r"\b(CP2K|PBE|D3(?:\(BJ\))?|cut[- ]?off|basis|SCF|smearing|ADDED_MOS|ASE|MACE|vibrations?)\b", re.I),
        "models": re.compile(r"\b(formula|composition|atom count|charge|multiplicity|spin state|donor atoms?|coordination bonds?)\b", re.I),
        "dependencies": re.compile(r"\b(depends on|dependent on|prerequisite|WP\s*\d+\s*(?:->|→)\s*WP\s*\d+)\b", re.I),
        "inputs": re.compile(r"\b(input files?|input data|starting structure)\b", re.I),
        "outputs": re.compile(r"\b(output files?|copy[- ]?ready|report artifact)\b", re.I),
        "resources": re.compile(r"\b(nodes?|CPUs?|cores?|memory|walltime|partition|queue|GPU)\b", re.I),
        "tasks": re.compile(r"\b(orientations?|docking poses?|spin candidates?|isolated[- ]fragment spin|single[- ]point calculations?)\b", re.I),
    }
    for index, block in enumerate(blocks, start=1):
        text = block.text.strip()
        if not text:
            continue
        evidence_id = f"docx-block-{index:06d}"
        context = contexts[evidence_id]
        parsed_field = None
        parsed = _parse_label_value(text)
        if parsed:
            parsed_field = _normalise_label(parsed[0])
        for category, pattern in cue_patterns.items():
            if not pattern.search(text):
                continue
            if parsed_field and _field_category(parsed_field) == category:
                continue
            unresolved_structured_fields.append({
                "field": category,
                "status": "unresolved",
                "reason": "Relevant source text exists, but no reliable field/value structure was recognised.",
                "evidence_ids": [evidence_id],
                "source": dict(block.location),
                "source_text": block.text,
                "work_package": context.get("work_package"),
                "system_id": context.get("system_id"),
            })

    # Aggregate field provenance for every top-level structure, including explicit
    # absent/unresolved states. No profile value is inserted here.
    categories = {
        "sections": sections,
        "systems": list(systems_by_id.values()),
        "models": list(models_by_id.values()),
        "method": method_claims,
        "tasks": list(tasks_by_id.values()),
        "task_count_claims": task_count_claims,
        "dependencies": dependencies,
        "input_outputs": {"inputs": inputs, "outputs": outputs},
        "resources": resources,
        "scientific_constraints": scientific_constraints,
    }
    unresolved_categories = {item["field"].split(".", 1)[0] for item in unresolved_structured_fields}
    for field, value in categories.items():
        if field in field_provenance:
            continue
        if value:
            field_provenance[field] = _provenance("docx_evidence", _collect_evidence_ids(value))
        elif field in unresolved_categories:
            field_provenance[field] = _provenance(
                "unresolved",
                list(dict.fromkeys(
                    eid for item in unresolved_structured_fields
                    if item["field"].split(".", 1)[0] == field
                    for eid in item.get("evidence_ids", [])
                )),
                reasons=[item["reason"] for item in unresolved_structured_fields
                         if item["field"].split(".", 1)[0] == field],
            )
        else:
            field_provenance[field] = _provenance("absent")

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project": {
            "project_id": project_id,
            "plan_version": plan_version,
            "source_format": "docx",
        },
        "sections": sections,
        "systems": list(systems_by_id.values()),
        "models": list(models_by_id.values()),
        "method": {
            field: {
                "values": [item.get("value") for item in items],
                "evidence_ids": _ids_from_claims(items),
                "claims": [_structured_value(item) for item in items],
            }
            for field, items in method_claims.items()
        },
        "tasks": list(tasks_by_id.values()),
        "task_count_claims": task_count_claims,
        "dependencies": dependencies,
        "input_outputs": {"inputs": inputs, "outputs": outputs},
        "resources": resources,
        "scientific_constraints": scientific_constraints,
        "claims": claims,
        "unresolved_definitions": [
            {
                "field": claim["field"],
                "label": claim["label"],
                "value": claim["value"],
                "evidence_id": claim["evidence_id"],
                "evidence_ids": _claim_evidence_ids(claim),
                "source": dict(claim.get("source") or {}),
                "source_text": claim.get("source_text", ""),
            }
            for claim in claims if claim["status"] == "requires_confirmation"
        ],
        "unresolved_structured_fields": unresolved_structured_fields,
        "field_provenance": field_provenance,
        "profile_overlay": {},
        "profile_field_provenance": {},
        "profile_reconciliation": [],
        "evidence": evidence,
        "diagnostics": diagnostics,
        "compilation_status": "BLOCKED" if any(
            item["blocks_execution"] for item in diagnostics
        ) else "NEEDS_REVIEW",
    }
