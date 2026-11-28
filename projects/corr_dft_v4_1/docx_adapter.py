"""CORR DFT v4.1-specific DOCX extraction and reconciliation evidence adapter.

This module is deliberately opt-in: the shared Project Manifest compiler does not
recognise CORR species, CP2K-specific prose, or CORR work-package semantics unless
the v4.1 project compiler passes these hooks explicitly.
"""
from __future__ import annotations

import re
from typing import Any

from pipeline_contracts.plan_compiler.docx_reader import ExtractedBlock
from pipeline_contracts.plan_compiler.manifest import _normalise_field_value


def _append_claim(
    claims: list[dict],
    block: ExtractedBlock,
    index: int,
    context: dict,
    field: str,
    value: Any,
) -> None:
    evidence_id = f"docx-block-{index:06d}"
    for existing in claims:
        existing_context = existing.get("context") or {}
        if (
            existing.get("field") == field
            and evidence_id in (existing.get("evidence_ids") or [existing.get("evidence_id")])
            and str(existing_context.get("system_id") or "") == str(context.get("system_id") or "")
            and str(existing_context.get("work_package") or "") == str(context.get("work_package") or "")
            and _normalise_field_value(existing.get("value", "")) == _normalise_field_value(value)
        ):
            return
    claims.append({
        "field": field,
        "label": field,
        "value": value,
        "unit": None,
        "status": "requires_confirmation",
        "evidence_id": evidence_id,
        "evidence_ids": [evidence_id],
        "source": dict(block.location),
        "source_text": block.text,
        "context": dict(context),
    })


def _corr_scoped_contexts(
    blocks: list[ExtractedBlock], contexts: dict[str, dict],
) -> dict[str, dict]:
    """Apply the CORR v4.1 WP2 gate phrase to its local numbered subsection only."""
    result: dict[str, dict] = {}
    active_path: tuple[str, ...] | None = None
    active_wp: str | None = None
    for index, block in enumerate(blocks, start=1):
        evidence_id = f"docx-block-{index:06d}"
        source_context = contexts[evidence_id]
        path = tuple(source_context.get("section_path") or [])
        if active_path is not None and path != active_path:
            active_wp = None
        active_path = path
        context = dict(source_context)
        if context.get("work_package"):
            active_wp = str(context["work_package"])
        gate = re.search(r"\bWP\s*(\d+)\s*(?:试算门控|gate)", block.text, re.I)
        if gate:
            active_wp = f"WP{int(gate.group(1))}"
        if not context.get("work_package") and active_wp:
            context["work_package"] = active_wp
        result[evidence_id] = context
    return result


def extract_corr_v41_claims(
    blocks: list[ExtractedBlock],
    contexts: dict[str, dict],
    claims: list[dict],
) -> None:
    """Add only CORR v4.1-specific parameter/model/task claims."""
    contexts = _corr_scoped_contexts(blocks, contexts)
    patterns = [
        ("xc", re.compile(r"\bXC_FUNCTIONAL\s+(PBE)\b", re.I), lambda m: m.group(1).upper()),
        ("dispersion", re.compile(r"\bTYPE\s+DFTD3\s*\(\s*BJ\s*\)", re.I), lambda m: "D3(BJ)"),
        ("xc", re.compile(r"Perdew-Burke-Ernzerhof\s*\(PBE\)\s+functional", re.I), lambda m: "PBE"),
        ("dispersion", re.compile(r"DFT-D3\s*\(BJ\)\s+dispersion correction", re.I), lambda m: "D3(BJ)"),
        ("spin_polarized", re.compile(r"spin-polarized\s+DFT", re.I), lambda m: "true"),
        ("cutoff_ry", re.compile(r"\b(?:CUTOFF|density cutoff of)\s*(\d+(?:\.\d+)?)\s*Ry\b", re.I), lambda m: f"{m.group(1)} Ry"),
        ("rel_cutoff_ry", re.compile(r"\b(?:REL_CUTOFF|relative cutoff of)\s*(\d+(?:\.\d+)?)\s*Ry\b", re.I), lambda m: f"{m.group(1)} Ry"),
        ("spin_polarized", re.compile(r"\bUKS\s+\.TRUE\.", re.I), lambda m: "true"),
        ("smearing_temperature_K", re.compile(r"\bELECTRONIC_TEMP\s+(\d+(?:\.\d+)?)\b", re.I), lambda m: f"{m.group(1)} K"),
        ("smearing_temperature_K", re.compile(r"Fermi-Dirac\s+smearing\s*\((\d+(?:\.\d+)?)\s*K\)", re.I), lambda m: f"{m.group(1)} K"),
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
                _append_claim(claims, block, index, context, field, render(match))

        if re.search(r"\bEPS_SCF\b", text, re.I):
            explicit_eps = re.search(r"EPS_SCF\s+([0-9]+(?:\.[0-9]+)?(?:E[-+]?\d+)?)\s*Ha\b", text, re.I)
            if explicit_eps and re.search(r"ENERGY_FORCE|finite displacement|有限位移", text, re.I):
                _append_claim(claims, block, index, context,
                              "eps_scf_local_hessian_force", f"{explicit_eps.group(1)} Ha")

        # The English copy-ready section spells out operation-specific thresholds.
        geometry_scf = re.search(
            r"optimized at the DFT level.{0,900}?SCF threshold\s+10\^(-\d+)\s*Ha",
            text, re.I | re.S,
        )
        hessian_scf = re.search(
            r"CP2K static force evaluations\s*\(SCF threshold tightened to\s+10\^(-\d+)\s*Ha",
            text, re.I | re.S,
        )
        if geometry_scf:
            _append_claim(claims, block, index, context,
                          "eps_scf_geometry_optimization", f"1E{geometry_scf.group(1)} Ha")
        if hessian_scf:
            _append_claim(claims, block, index, context,
                          "eps_scf_local_hessian_force", f"1E{hessian_scf.group(1)} Ha")

        if re.search(r"(?:finite displacement|有限位移|Vibrations)", text, re.I):
            displacement = re.search(r"±\s*(\d+(?:\.\d+)?)\s*Å", text, re.I)
            if displacement:
                _append_claim(claims, block, index, context,
                              "displacement_angstrom", f"{displacement.group(1)} Å")
            if re.search(r"冻结(?:基底|支持体)|frozen support", text, re.I):
                _append_claim(claims, block, index, context,
                              "frozen_support_and_Cu13", "true")

        if (re.search(r"\d+(?:\.\d+)?\s*Å\s*vs\.?\s*\d+(?:\.\d+)?\s*Å", text, re.I)
                or re.search(r"(?:双盒子|cell|box|超胞).{0,100}(?:vs\.?|与|and)", text, re.I | re.S)):
            sizes = list(dict.fromkeys(re.findall(r"(\d+(?:\.\d+)?)\s*Å", text, re.I)))
            if len(sizes) >= 2:
                _append_claim(
                    claims, block, index, context, "cell_sizes_angstrom",
                    [f"{size} Å" for size in sizes[:2]],
                )

        if re.search(r"ΔG1\s*=\s*G\(\*H2CCO\).*?ΔG2\s*=\s*G\(\*HCCOH\)", text, re.I | re.S):
            _append_claim(claims, block, index, context, "reaction_intermediate", "*HCCO")
            _append_claim(claims, block, index, context,
                          "protonation_products", ["*H2CCO", "*HCCOH"])

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
                _append_claim(claims, block, index, scoped_context, "support_motif", motif)
                _append_claim(claims, block, index, scoped_context, "cluster_formula", "Cu13")
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
                    _append_claim(claims, block, index, scoped_context, field, found.group(1))

    # The WP4 count semantics belong to this project's table adapter, not the
    # shared Manifest implementation. The source row label supplies WP ownership.
    for index, block in enumerate(blocks, start=1):
        if block.kind == "table_cell":
            rows.setdefault((block.location.get("table"), block.location.get("row")), []).append((index, block))
    for cells in rows.values():
        cells.sort(key=lambda pair: int(pair[1].location.get("column", 0)))
        if not cells:
            continue
        wp_match = re.search(r"\bWP\s*(\d+)\b", cells[0][1].text, re.I)
        if not wp_match:
            continue
        work_package = f"WP{int(wp_match.group(1))}"
        for index, block in cells[1:]:
            context = dict(contexts[f"docx-block-{index:06d}"])
            context["work_package"] = work_package
            calls = re.search(r"(\d+)\s*次?\s*(?:快速)?单点力调用", block.text)
            if calls:
                _append_claim(claims, block, index, context, "total_force_evaluations", calls.group(1))
            states = re.search(r"(\d+)\s*个吸附态", block.text)
            if states:
                _append_claim(claims, block, index, context, "adsorbed_state_hessians", states.group(1))


def _source_at(item: dict, *, paragraph: int | None = None,
               table: int | None = None, row: int | None = None,
               column: int | None = None) -> bool:
    source = item.get("source") or {}
    return (
        (paragraph is None or source.get("paragraph") == paragraph)
        and (table is None or source.get("table") == table)
        and (row is None or source.get("row") == row)
        and (column is None or source.get("column") == column)
    )


def extract_corr_v41_unresolved_fields(
    blocks: list[ExtractedBlock],
    evidence: list[dict],
    contexts: dict[str, dict],
    claims: list[dict],
) -> list[dict]:
    """Retain CORR v4.1 source cues that are not safe to structure or scope."""
    unresolved: list[dict] = []

    for item in evidence:
        text = item.get("text", "")
        markers = list(re.finditer(r"\b(Cu-20|SnCu-20)\s*:", text, re.I))
        if len(markers) < 2:
            continue
        for marker_index, marker in enumerate(markers):
            system_id = marker.group(1)
            end = markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
            segment = text[marker.start():end]
            unresolved.append({
                "field": "systems.complete_formula",
                "status": "unresolved",
                "reason": "The DOCX gives a support motif plus Cu13 and aggregate counts, but no single complete-formula string.",
                "evidence_ids": [item["evidence_id"]],
                "source": dict(item.get("source") or {}),
                "source_text": segment,
                "system_id": system_id,
            })

    scf_without_unit = [
        item for item in evidence
        if _source_at(item, table=6, row=5, column=2)
        and re.search(r"\bEPS_SCF\b", item.get("text", ""), re.I)
        and not re.search(r"\d+(?:\.\d+)?(?:E[-+]?\d+)?\s*Ha\b", item.get("text", ""), re.I)
    ]
    if scf_without_unit:
        unresolved.append({
            "field": "method.scf_eps_scf_ha",
            "status": "unresolved",
            "reason": "The SCF table cell labels two operation-specific EPS_SCF values but does not state their units in that cell; unit-bearing method prose is reconciled separately.",
            "evidence_ids": [item["evidence_id"] for item in scf_without_unit],
            "source_text": " | ".join(item.get("text", "") for item in scf_without_unit),
        })

    spin_cells = [
        item for item in evidence
        if _source_at(item, table=5, row=6)
    ]
    if spin_cells and any(re.search(r"M\s*=", item.get("text", ""), re.I) for item in spin_cells):
        spin_ids = [item["evidence_id"] for item in spin_cells]
        spin_text = " | ".join(item.get("text", "") for item in spin_cells)
        unresolved.extend([
            {
                "field": "systems.cluster.multiplicities", "status": "unresolved",
                "reason": "Spin multiplicities are listed, but the table headers do not establish safe per-system column ownership.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "systems.support_multiplicities", "status": "unresolved",
                "reason": "Support spin values are present but cannot be assigned to a system without the table header mapping.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "systems.complete_model_multiplicities", "status": "unresolved",
                "reason": "Complete-model spin values are present but cannot be assigned to a system without the table header mapping.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "systems.conditional_complete_model_multiplicity", "status": "unresolved",
                "reason": "A conditional M=5 candidate is mentioned, but its system column cannot be confirmed from the available row evidence.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "tasks.isolated_fragment_spin_candidate_count", "status": "unresolved",
                "reason": "Spin candidates are listed, but the source row does not establish WP1 ownership.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "tasks.isolated_fragment_spin_candidates", "status": "unresolved",
                "reason": "Fragment spin candidates are listed, but the source row does not establish WP1 ownership or a verified system-column mapping.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "tasks.isolated_fragment_spin_candidates.Cu13", "status": "unresolved",
                "reason": "Cu13 multiplicity candidates are listed, but their WP1 task ownership remains unconfirmed.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "tasks.isolated_fragment_spin_candidates.Cu20_support", "status": "unresolved",
                "reason": "Neutral Cu support multiplicities are listed, but the table column-to-system mapping and WP1 ownership are unconfirmed.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "tasks.isolated_fragment_spin_candidates.SnCu20_support", "status": "unresolved",
                "reason": "Sn-containing support multiplicities are listed, but the table column-to-system mapping and WP1 ownership are unconfirmed.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
            {
                "field": "topology_requirements.explicit_spin_candidates", "status": "unresolved",
                "reason": "Fragment and complete-model multiplicities are explicitly listed, but the source row does not provide a verified per-system mapping for the topology requirement.",
                "evidence_ids": spin_ids, "source_text": spin_text,
            },
        ])

    topology_sources = [
        item for item in evidence
        if _source_at(item, paragraph=18)
        or (_source_at(item, table=9, row=2, column=1)
            and "Computational Details:" in item.get("text", ""))
    ]
    if topology_sources:
        topology_ids = [item["evidence_id"] for item in topology_sources]
        topology_text = " | ".join(item.get("text", "") for item in topology_sources)
        for field, reason in (
            ("topology_requirements.explicit_elements",
             "Chemical elements occur in the model descriptions, but no complete atom-indexed element map is supplied."),
            ("topology_requirements.explicit_covalent_bonds_and_orders",
             "The source describes a local motif and selected excluded bonds, but does not provide a complete atom-pair covalent bond/order list."),
            ("topology_requirements.explicit_coordination_bonds",
             "Metal–oxygen coordination is described at motif level, but atom-indexed coordination pairs are absent."),
            ("topology_requirements.explicit_donor_atoms",
             "Phenolic/carboxyl oxygen donors and coordinating water are mentioned, but donor atom IDs are not provided."),
            ("topology_requirements.explicit_formal_charges",
             "Net model charges and oxidation-state descriptions are present, but atom-indexed formal charges are not supplied."),
            ("topology_requirements.explicit_3d_construction_constraints",
             "Initial orientation and pre-relaxation are described, but explicit 3D construction constraints are not supplied."),
        ):
            unresolved.append({
                "field": field, "status": "unresolved", "reason": reason,
                "evidence_ids": topology_ids, "source_text": topology_text,
            })

    reaction_block = next((item for item in evidence if _source_at(item, paragraph=28)), None)
    if reaction_block:
        unresolved.append({
            "field": "scientific_scope.thermodynamic_only", "status": "unresolved",
            "reason": "Thermodynamic CHE branches are explicit, but the source does not establish an exclusive thermodynamics-only scope.",
            "evidence_ids": [reaction_block["evidence_id"]],
            "source": dict(reaction_block.get("source") or {}),
            "source_text": reaction_block.get("text", ""),
        })

    spin_evidence_ids = [item["evidence_id"] for item in spin_cells]
    for item in evidence:
        text = item.get("text", "")
        source = item.get("source") or {}
        if _source_at(item, paragraph=27) and re.search(r"\*HCCO.*4 原子.*\*H2CCO.*5 原子", text, re.S):
            unresolved.append({
                "field": "tasks.adsorbate_atom_counts_per_catalyst", "status": "unresolved",
                "reason": "Adsorbate atom counts are explicit, but this paragraph does not identify a WP or per-catalyst mapping.",
                "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
            })
        if _source_at(item, paragraph=22) and re.search(r"代表性.*SnCu-20", text, re.I):
            unresolved.append({
                "field": "tasks.representative_sncu20_models", "status": "unresolved",
                "reason": "A representative SnCu-20 model is named in the WP2 gate, but the source does not state a numeric model count.",
                "evidence_ids": [item["evidence_id"]], "source": dict(source),
                "source_text": text, "work_package": "WP2",
            })
        if _source_at(item, table=9, row=2, column=1):
            if re.search(r"cluster-support orientations", text, re.I):
                unresolved.extend([
                    {
                        "field": "tasks.support_cluster_docking_orientation_count", "status": "unresolved",
                        "reason": "Initial cluster-support orientations are mentioned, but no numeric orientation count is stated in this source paragraph.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                    {
                        "field": "tasks.orientation_scope", "status": "unresolved",
                        "reason": "Cluster-support orientations are mentioned, but the source does not specify whether a count is per catalyst or across both systems.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                ])
            if re.search(r"3[-–]4 chemically distinct candidate configurations", text, re.I):
                unresolved.extend([
                    {
                        "field": "tasks.retained_structurally_distinct_candidates_per_catalyst", "status": "unresolved",
                        "reason": "The candidate range is explicit, but the paragraph does not assign it to WP1.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                    {
                        "field": "tasks.hcco_candidates_per_catalyst", "status": "unresolved",
                        "reason": "The paragraph discusses pre-relaxed *HCCO adsorption configurations and 3–4 optimized candidates, but does not bind that range to WP3 or define an exact HCCO candidate count.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                ])
            if re.search(r"MACE-MP-0.*?fmax\s*<\s*0\.05\s*eV/Å", text, re.I | re.S):
                unresolved.append({
                    "field": "tasks.mace_fmax_ev_per_angstrom", "status": "unresolved",
                    "reason": "The MACE pre-relaxation threshold is explicit, but the paragraph does not assign it to WP1.",
                    "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                })
            if re.search(r"verifying the spin multiplicities of isolated fragments", text, re.I):
                unresolved.append({
                    "field": "tasks.summary_fragment_single_point_count", "status": "unresolved",
                    "reason": "Isolated-fragment spin verification is described, but this paragraph does not state a WP1 single-point count.",
                    "evidence_ids": [*spin_evidence_ids, item["evidence_id"]],
                    "source": dict(source), "source_text": text,
                })
            if re.search(r"protonation branches", text, re.I):
                unresolved.extend([
                    {
                        "field": "tasks.protonation_products_per_catalyst", "status": "unresolved",
                        "reason": "Two protonation branches are described, but the paragraph does not establish WP3 ownership or per-catalyst count.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                    {
                        "field": "tasks.gas_references", "status": "unresolved",
                        "reason": "H2 and H2CCO appear in the thermodynamic expressions, but the paragraph does not establish WP3 gas-reference field ownership.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                ])
            if re.search(r"SCCS.*?sensitivity checks|basis-set sensitivity checks", text, re.I | re.S):
                unresolved.extend([
                    {
                        "field": "tasks.sccs_single_points", "status": "unresolved",
                        "reason": "SCCS sensitivity is explicitly described on key states, but no WP5 ownership or single-point count is stated.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                    {
                        "field": "tasks.tzv2p_single_points", "status": "unresolved",
                        "reason": "TZV2P basis sensitivity is explicitly described on key states, but no WP5 ownership or single-point count is stated.",
                        "evidence_ids": [item["evidence_id"]], "source": dict(source), "source_text": text,
                    },
                ])
    return unresolved
