from __future__ import annotations

import unittest
import json
from collections import Counter

from pipeline_contracts.plan_compiler import ExtractedBlock, build_project_manifest, detect_conflicts
from projects.corr_dft_v4_1.plan_compiler import _compare_profile_value, _profile_provenance
from projects.corr_dft_v4_1.plan_rules import load_v41_profile


def _run04_blocks() -> list[ExtractedBlock]:
    # Preserve the exact run_04 evidence-block indices so claim/evidence references
    # can be asserted against the published diagnostic bundle.
    blocks = [
        ExtractedBlock("paragraph", "", {"part": "word/document.xml", "evidence_block": i})
        for i in range(1, 160)
    ]

    def put(index: int, text: str, *, kind: str = "paragraph", location: dict | None = None,
            style: str | None = None) -> None:
        blocks[index - 1] = ExtractedBlock(
            kind, text,
            location or {"part": "word/document.xml", "evidence_block": index},
            style,
        )

    # Real paragraph heading markers: these are Normal-style paragraphs, not Heading styles.
    put(3, "一、研究的科学问题与严谨因果边界（Scientific Problem & Scope）",
        location={"part": "word/document.xml", "paragraph": 2})
    put(4, "1.1 实验背景与理论模型定位",
        location={"part": "word/document.xml", "paragraph": 3})
    put(9, "1.2 因果边界与七项核心科学纠偏（v4.1 基线冻结规范）",
        location={"part": "word/document.xml", "paragraph": 7})
    put(35, "二、两阶段门控实现逻辑与开源工具链（Implementation Logic）",
        location={"part": "word/document.xml", "paragraph": 9})

    # Real table 4 row 4: one row assertion with three independent cell sources.
    put(50, "ASE Vibrations\n+ CP2K 力接口", kind="table_cell",
        location={"part": "word/document.xml", "table": 4, "row": 4, "column": 1})
    put(51, "冻结基底与 Cu13 的\n局部 Sub-Hessian 计算", kind="table_cell",
        location={"part": "word/document.xml", "table": 4, "row": 4, "column": 2})
    put(52, "由 ASE Vibrations 仅对吸附质原子（4–5 原子）施加 ±0.01 Å 有限位移，调用 CP2K RUN_TYPE ENERGY_FORCE（复用基态 .wfn，EPS_SCF 1.0E-8 Ha）并在 Python 中组装子空间 Hessian。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 4, "row": 4, "column": 3})

    # Real table 5 row 6: the two CHARGE cells contain the same scalar and
    # different explanatory spin text. The first column is the row label.
    put(78, "总电荷与奇/偶电子\n自旋基态确认流程", kind="table_cell",
        location={"part": "word/document.xml", "table": 5, "row": 6, "column": 1})
    put(79, "CHARGE = 0；先校验孤立中性 Cu13（M=2, 4, 6）与中性基底（2×Cu²⁺, M=1, 3）自旋初态，再对比完整奇数电子体系 M=2 与 M=4 锁定基态。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 5, "row": 6, "column": 2})
    put(80, "CHARGE = 0；孤立中性基底（1×Cu²⁺ d⁹ + 闭壳层 Sn⁴⁺ d¹⁰, M=2）与 Cu13 组合后，对比完整偶数电子体系 M=1 与 M=3（必要时 M=5）锁定基态。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 5, "row": 6, "column": 3})

    # Real SCF table 6 row 5. ADDED_MOS is in column 2, not a standalone paragraph.
    put(102, "SCF 收敛策略\n（明确区分路线）", kind="table_cell",
        location={"part": "word/document.xml", "table": 6, "row": 5, "column": 1})
    put(103, "【优先测试主路线（标准金属对角化）】：\n  UKS .TRUE.\n  &DIAGONALIZATION (STANDARD)\n  &SMEAR / METHOD FERMI_DIRAC / ELECTRONIC_TEMP 300\n  &MIXING / METHOD BROYDEN_MIXING / ALPHA 0.2\n  ADDED_MOS 80\n  EPS_SCF 1.0E-6 (优化/静态) | 1.0E-8 (力计算)",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 6, "row": 5, "column": 2})
    put(104, "纠偏修正：不将 OT 与 Broyden mixing 混写。优先采用传统对角化 + Fermi–Dirac 展宽 + Broyden 密度混合 + ADDED_MOS 路线；若需测试直接有限温度 OT，须严格按对应 CP2K 版本文档单独配置并在 WP1 试算中验证。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 6, "row": 5, "column": 3})

    put(86, "83–84 原子复合体的最大几何跨度（含范德华半径）约为 14.5–15.0 Å。为满足 CP2K Martyna-Tuckerman（MT）非周期泊松求解器对完整电子密度空间跨度（L > 2 D_max，含弥散尾部）的收敛要求，默认立方超胞设定为 30.0 Å × 30.0 Å × 30.0 Å，并在 WP2 试算门控中执行如下低成本验证：",
        location={"part": "word/document.xml", "paragraph": 21})
    put(87, "30.0 Å vs. 34.0 Å 双盒子静态单点校验：选取优化后的代表性完整催化剂模型（SnCu-20，84 原子），分别在 30.0³ Å³ 与 34.0³ Å³ 立方盒子（均开启 &CENTER_COORDINATES 与双重 PERIODIC NONE）下运行静态单点计算，检查电子密度在盒子边界处是否衰减至 < 10⁻⁶ e/Bohr³，且两盒子总能差 < 1–2 meV。",
        location={"part": "word/document.xml", "paragraph": 22})
    put(113, "局部振动频率实现方式（ASE Vibrations + CP2K 力接口）：不使用 CP2K MODE_SELECTIVE，而是在高精度优化收敛构型上，利用 Python ASE 的 ase.vibrations.Vibrations 模块仅指定吸附质原子（*HCCO 为 4 原子，*H2CCO 与 *HCCOH 各为 5 原子）施加 ±0.01 Å 有限位移，每次调用 CP2K RUN_TYPE ENERGY_FORCE（复用基态 .wfn 波函数，EPS_SCF 1.0E-8 Ha），由 ASE 组装子空间 Hessian 并求解谐振频率。6 个吸附态合计需 2 × (25 + 31 + 31) = 174 次快速单点力调用。方法学上明确声明：此为冻结基底与 Cu13 条件下的局部振动近似，不包含吸附质与基底/团簇全部振动自由度的耦合。",
        location={"part": "word/document.xml", "paragraph": 27})
    put(114, "严格分离的 CHE 自由能与脱附近似公式（U = 0 V vs. RHE，T = 298.15 K）：ΔG1 = G(*H2CCO) − G(*HCCO) − 1/2 G(H2(g))；ΔG2 = G(*HCCOH) − G(*HCCO) − 1/2 G(H2(g))。",
        location={"part": "word/document.xml", "paragraph": 28})

    # WP4 table row: its first cell explicitly identifies WP4; column 3 gives 174.
    put(132, "【第二阶段：批量生产】\nWP4\nASE 有限位移\nSub-Hessian 与 CHE", kind="table_cell",
        location={"part": "word/document.xml", "table": 7, "row": 5, "column": 1})
    put(133, "1. 在代表性吸附态上对比 EPS_SCF = 1.0E-7 与 1.0E-8 Ha 的频率收敛性；\n2. 运行 ASE Vibrations + CP2K ENERGY_FORCE（冻结 70/71 原子基底与 Cu13，仅位移吸附质），提取 ZPE 与 TS_vib；\n3. 严格按公式计算 ΔG1、ΔG2、ΔΔG 与忽略基底振动变化的 ΔG_des。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 7, "row": 5, "column": 2})
    put(134, "6 个吸附态有限位移局部频率（共 174 次快速单点力调用，复用参考波函数）+ 2 个气相频率。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 7, "row": 5, "column": 3})
    put(135, "所有吸附质局部 Hessian 振动模式无虚频；明确采用冻结基底条件下的局部振动近似；输出完整热力学自由能总表。",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 7, "row": 5, "column": 4})

    put(154, "Copy-Ready English Text: Computational Details (Frozen Baseline v4.1)",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 9, "row": 1, "column": 1})
    put(155, (
        "Computational Details: All spin-polarized density functional theory (DFT) calculations were performed using "
        "the Quickstep module of the CP2K package within the Gaussian and plane waves (GPW) framework. The "
        "Perdew-Burke-Ernzerhof (PBE) functional combined with Grimme's DFT-D3(BJ) dispersion correction was "
        "employed. The plane-wave density cutoff of 500 Ry and a relative cutoff of 60 Ry were used. "
        "Cu-20: [Cu2(C7H5O5)4]0 + Cu13, 70 support atoms + 13 cluster atoms = 83 atoms, "
        "417 valence electrons, net charge 0. "
        "SnCu-20: [CuSn(C7H5O5)2(C7H4O5)2(H2O)]0 + Cu13, 71 support atoms + 13 cluster atoms = 84 atoms, "
        "426 valence electrons, net charge 0. "
        "All models were centered in a 30.0 × 30.0 × 30.0 Å3 cubic cell with non-periodic boundary conditions "
        "in both the cell and Poisson solver (PERIODIC NONE, Martyna-Tuckerman solver), verified against a "
        "34.0 × 34.0 × 34.0 Å3 cell. "
        "Initial configurations were optimized using Fermi-Dirac smearing (300 K). "
        "For each system, 3-4 chemically distinct candidate configurations were subsequently optimized. "
        "Competing single-(H+/e-) protonation branches (*HCCO + H+ + e- → *H2CCO vs. *HCCO + H+ + e- → *HCCOH) "
        "were evaluated at U = 0 V vs. RHE and T = 298.15 K. "
        "Electrostatic implicit solvation sensitivity checks (SCCS with ε = 78.4) and basis-set sensitivity checks "
        "(TZV2P-MOLOPT-GTH) were carried out on key states. "
        "Force threshold < 0.01 eV/Å; EPS_SCF 1.0E-6 Ha for optimization and 1.0E-8 Ha for force calculations."
    ), kind="table_cell",
        location={"part": "word/document.xml", "table": 9, "row": 2, "column": 1})
    put(158, "Copy-Ready English Text: Neutral & Scope-Bounded Results Report Template (Frozen v4.1)",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 10, "row": 1, "column": 1})
    return blocks


class RealDocxRun04RegressionTests(unittest.TestCase):
    def test_real_charge_cells_split_scalar_from_explanation_without_conflict(self):
        manifest = build_project_manifest(_run04_blocks(), project_id="corr_dft_v4_1")
        charge = [c for c in manifest["claims"] if c.get("field") == "charge"
                  and c.get("evidence_id") in {"docx-block-000079", "docx-block-000080"}]
        self.assertEqual([c["value"] for c in charge], ["0", "0"])
        self.assertTrue(all(c.get("value_explanation") for c in charge))
        self.assertEqual([c["evidence_id"] for c in charge],
                         ["docx-block-000079", "docx-block-000080"])
        self.assertFalse(any(d["code"] == "PLAN_FIELD_CONFLICT" and d["field"] == "charge"
                             for d in manifest["diagnostics"]))

    def test_same_scalar_field_with_different_real_values_still_blocks(self):
        claims = [
            {"field": "charge", "label": "CHARGE", "value": "0",
             "context": {"system_id": "Cu-20"}, "evidence_id": "ev-a"},
            {"field": "charge", "label": "CHARGE", "value": "1",
             "context": {"system_id": "Cu-20"}, "evidence_id": "ev-b"},
        ]
        diagnostics = detect_conflicts(claims)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "PLAN_FIELD_CONFLICT")
        self.assertTrue(diagnostics[0].blocks_execution)

    def test_ase_description_granularity_and_copy_ready_outputs_are_not_conflicts(self):
        manifest = build_project_manifest(_run04_blocks(), project_id="corr_dft_v4_1")
        self.assertFalse(any(d["code"] == "PLAN_FIELD_CONFLICT"
                             and d["field"] in {"ase_vibrations_cp2k", "copy_ready_english_text"}
                             for d in manifest["diagnostics"]))
        ase_claims = [c for c in manifest["claims"] if c.get("field") == "ase_vibrations_cp2k"]
        output_claims = [c for c in manifest["claims"] if c.get("field") == "copy_ready_english_text"]
        self.assertEqual({c["evidence_id"] for c in ase_claims},
                         {"docx-block-000113", "docx-block-000050"})
        self.assertEqual({c["evidence_id"] for c in output_claims},
                         {"docx-block-000154", "docx-block-000158"})
        self.assertEqual(len(output_claims), 2)

    def test_numeric_profile_unit_suffix_requires_explicit_docx_unit(self):
        self.assertEqual(
            _compare_profile_value(1.0e-6, "1.0E-6", "method.scf_eps_scf_ha.geometry_optimization"),
            "needs_review",
        )
        self.assertEqual(
            _compare_profile_value(1.0e-6, "1.0E-6 Ha", "method.scf_eps_scf_ha.geometry_optimization"),
            "consistent",
        )

    def test_numeric_formatting_normalizes_but_physical_units_do_not_merge(self):
        equivalent = detect_conflicts([
            {"field": "cutoff_ry", "label": "CUTOFF", "value": "500.0 Ry", "evidence_id": "ev-a"},
            {"field": "cutoff_ry", "label": "CUTOFF", "value": "500 Ry", "evidence_id": "ev-b"},
        ])
        self.assertEqual(equivalent, [])
        different_units = detect_conflicts([
            {"field": "cutoff", "label": "CUTOFF", "value": "500 Ry", "evidence_id": "ev-a"},
            {"field": "cutoff", "label": "CUTOFF", "value": "500 Ha", "evidence_id": "ev-b"},
        ])
        self.assertEqual(len(different_units), 1)
        self.assertTrue(different_units[0].blocks_execution)

    def test_ase_same_label_with_different_parameter_values_still_blocks(self):
        diagnostics = detect_conflicts([
            {"field": "ase_vibrations_cp2k", "label": "ASE Vibrations + CP2K",
             "value": "finite displacement ±0.01 Å", "evidence_id": "ev-a"},
            {"field": "ase_vibrations_cp2k", "label": "ASE Vibrations + CP2K",
             "value": "finite displacement ±0.02 Å", "evidence_id": "ev-b"},
        ])
        self.assertEqual(len(diagnostics), 1)
        self.assertTrue(diagnostics[0].blocks_execution)

    def test_numbered_normal_style_sections_and_real_wp4_table_scope_are_preserved(self):
        manifest = build_project_manifest(_run04_blocks(), project_id="corr_dft_v4_1")
        headings = [s for s in manifest["sections"]]
        self.assertTrue(any(s["heading"].startswith("研究的科学问题") and s["heading_source"] == "explicit_numbering"
                            for s in headings))
        self.assertTrue(any(s["heading"].startswith("实验背景") and s["level"] == 2
                            for s in headings))
        self.assertFalse(any("1. 局域结构" in s["heading"] for s in headings))
        wp4 = next(t for t in manifest["tasks"] if t["work_package"] == "WP4")
        self.assertEqual(set(wp4["evidence_ids"]),
                         {"docx-block-000132", "docx-block-000133", "docx-block-000134", "docx-block-000135"})
        self.assertEqual({c["work_package"] for c in manifest["task_count_claims"]}, {"WP4"})

    def test_added_mos_is_extracted_from_real_table_cell_and_keeps_all_cell_evidence(self):
        manifest = build_project_manifest(_run04_blocks(), project_id="corr_dft_v4_1")
        added = [c for c in manifest["claims"] if c.get("field") == "added_mos"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["value"], "80")
        self.assertEqual(added[0]["evidence_ids"], ["docx-block-000103"])
        scf = [c for c in manifest["claims"] if c.get("field") == "scf"]
        self.assertTrue(any("ADDED_MOS 80" in c["source_text"] for c in scf))
        self.assertEqual(added[0]["source"], {
            "part": "word/document.xml", "table": 6, "row": 5, "column": 2
        })

    def test_profile_104_reconciliation_uses_explicit_real_source_evidence(self):
        manifest = build_project_manifest(_run04_blocks(), project_id="corr_dft_v4_1")
        profile = load_v41_profile()
        _field_provenance, reconciliation = _profile_provenance(manifest, profile)
        by_field = {item["field"]: item for item in reconciliation}
        print("RUN04_PROFILE_STATUS_COUNTS=" + json.dumps(dict(Counter(item["status"] for item in reconciliation)), ensure_ascii=False))
        print("RUN04_PROFILE_STATUS_ROWS=" + json.dumps(
            [{"field": item["field"], "status": item["status"], "docx_status": item["docx_status"],
              "evidence_ids": item["docx_evidence_ids"]} for item in reconciliation],
            ensure_ascii=False,
        ))

        consistent_fields = [
            "systems.Cu-20.support_atom_count",
            "systems.Cu-20.complete_atom_count",
            "systems.Cu-20.explicit_valence_electrons",
            "systems.Cu-20.charge",
            "systems.Cu-20.cluster.formula",
            "systems.Cu-20.cluster.atom_count",
            "systems.Cu-20.support_motif",
            "systems.SnCu-20.support_atom_count",
            "systems.SnCu-20.complete_atom_count",
            "systems.SnCu-20.explicit_valence_electrons",
            "systems.SnCu-20.charge",
                        "systems.SnCu-20.support_motif",
            "method.xc", "method.dispersion", "method.cutoff_ry",
            "method.rel_cutoff_ry", "method.spin_polarized",
            "method.smearing_temperature_K", "method.periodicity",
            "method.poisson_solver", "method.cell_sizes_angstrom[0]", "method.cell_sizes_angstrom[1]",
            "method.force_threshold_ev_per_angstrom", "method.sccs_dielectric",
            "method.basis_sensitivity", "method.engine",
            "method.che.temperature_K", "method.che.potential_v_vs_rhe",
            "method.local_hessian.displacement_angstrom",
            "method.local_hessian.frozen_support_and_Cu13",
            "tasks.WP2.cell_sizes_angstrom[0]", "tasks.WP2.cell_sizes_angstrom[1]",
            "tasks.WP4.total_force_evaluations",
            "tasks.WP4.adsorbed_state_hessians",
        ]
        for field in consistent_fields:
            with self.subTest(field=field):
                self.assertEqual(by_field[field]["status"], "consistent")
                self.assertTrue(by_field[field]["docx_evidence_ids"])

        review_fields = [
            "systems.Cu-20.complete_formula",
            "systems.SnCu-20.complete_formula",
            "systems.Cu-20.cluster.multiplicities[0]",
            "systems.SnCu-20.support_multiplicities[0]",
            "tasks.WP1.isolated_fragment_spin_candidate_count",
            "tasks.WP1.isolated_fragment_spin_candidates.Cu13[0]",
            "tasks.WP1.isolated_fragment_spin_candidates.Cu20_support[0]",
            "tasks.WP1.isolated_fragment_spin_candidates.SnCu20_support[0]",
            "tasks.WP1.retained_structurally_distinct_candidates_per_catalyst.min",
            "tasks.WP2.representative_sncu20_models",
            "tasks.WP3.protonation_products_per_catalyst",
            "tasks.WP3.gas_references[0]",
            "tasks.WP4.adsorbate_atom_counts_per_catalyst[0]",
        ]
        for field in review_fields:
            with self.subTest(field=field):
                self.assertEqual(by_field[field]["status"], "needs_review")
                self.assertTrue(by_field[field]["docx_evidence_ids"])

        geometry_eps = by_field["method.scf_eps_scf_ha.geometry_optimization"]
        force_eps = by_field["method.scf_eps_scf_ha.local_hessian_force"]
        self.assertIn("docx-block-000103", geometry_eps["docx_evidence_ids"])
        self.assertIn("docx-block-000155", geometry_eps["docx_evidence_ids"])
        self.assertIn("docx-block-000103", force_eps["docx_evidence_ids"])
        self.assertIn("docx-block-000052", force_eps["docx_evidence_ids"])

        orientation = by_field["tasks.WP1.support_cluster_docking_orientation_count"]
        self.assertEqual(orientation["status"], "profile_only")
        self.assertEqual(orientation["docx_evidence_ids"], [])

        # The Profile remains isolated; no Profile-only value is inserted into DOCX claims.
        self.assertFalse(any(c.get("value") == 15 for c in manifest["claims"]))


if __name__ == "__main__":
    unittest.main()
