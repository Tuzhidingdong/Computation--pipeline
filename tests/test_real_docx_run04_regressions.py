from __future__ import annotations

import unittest
import csv
import json
from collections import Counter
from pathlib import Path

from pipeline_contracts.plan_compiler import ExtractedBlock, build_project_manifest, detect_conflicts
from projects.corr_dft_v4_1.plan_compiler import _compare_profile_value, _profile_provenance
from projects.corr_dft_v4_1.docx_adapter import extract_corr_v41_claims, extract_corr_v41_unresolved_fields
from projects.corr_dft_v4_1.plan_rules import load_v41_profile


def _run04_blocks() -> list[ExtractedBlock]:
    # Preserve the exact run_04 evidence-block indices so claim/evidence references
    # can be asserted against the published diagnostic bundle.
    blocks = [
        ExtractedBlock("paragraph", "", {"part": "word/document.xml", "evidence_block": i})
        for i in range(1, 160)
    ]

    def put(index: int, text: str, *, kind: str = "paragraph", location: dict | None = None,
            style: str | None = None, list_info: dict | None = None) -> None:
        blocks[index - 1] = ExtractedBlock(
            kind, text,
            location or {"part": "word/document.xml", "evidence_block": index},
            style, list_info,
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

    put(36, "2.1 先基态试算、后批量吸附的冻结执行路线",
        location={"part": "word/document.xml", "paragraph": 10})
    put(40, "2.2 开源工具链分工与技术使用边界",
        location={"part": "word/document.xml", "paragraph": 14})
    put(60, "三、70–71 原子基底建模、奇偶电子数与自旋规范（Modeling）",
        location={"part": "word/document.xml", "paragraph": 16})
    put(61, "3.1 四没食子酸双核配位局域结构（70–71 基底原子）",
        location={"part": "word/document.xml", "paragraph": 17})
    put(62, "为精准匹配 70–80 个基底原子 的规模并合理表征单宁酸的局域金属配位微环境，本方案构建电中性（CHARGE = 0）的四没食子酸双核配位局域结构（Four-gallate dinuclear coordination motif），在配位口袋上方负载同一二十面体 Cu13 团簇（注：该局域模型由四个没食子酸单体通过酚羟基/羧酸氧原子与金属中心配位形成，不包含单体间的 depside 酯键，也不代表天然单宁酸的完整高分子网络）：",
        location={"part": "word/document.xml", "paragraph": 18})
    put(85, "3.2 非周期超胞与 MT 电子密度尾部校验（30.0 Å vs. 34.0 Å）",
        location={"part": "word/document.xml", "paragraph": 20})
    put(88, "四、计算方法与核心参数规范（Parameters）",
        location={"part": "word/document.xml", "paragraph": 23})
    put(89, "4.1 CP2K 电子结构、SCF 路线与几何优化参数（v4.1 锁定版本）",
        location={"part": "word/document.xml", "paragraph": 24})
    put(112, "4.2 ASE 有限位移 Sub-Hessian 与 CHE 热力学近似声明",
        location={"part": "word/document.xml", "paragraph": 26})
    put(115, "五、两阶段门控执行计划（Two-Stage Gate-Controlled Task Plan）",
        location={"part": "word/document.xml", "paragraph": 29})
    put(141, "六、基线冻结状态确认与结果分析判据（Frozen Baseline & Analysis）",
        location={"part": "word/document.xml", "paragraph": 31})
    put(147, "七、可视化规范、计算方法撰写与无预设英文报告模板",
        location={"part": "word/document.xml", "paragraph": 36})
    put(148, "7.1 科研可视化与图表规范",
        location={"part": "word/document.xml", "paragraph": 37})
    put(153, "7.2 论文《Computational Details》英文撰写模板（v4.1 基线冻结版）",
        location={"part": "word/document.xml", "paragraph": 42})
    put(157, "7.3 论文《Results and Discussion》无预设英文结果报告模板（v4.1 基线冻结版）",
        location={"part": "word/document.xml", "paragraph": 44})

    put(144, "1. 局域结构自洽与 EXAFS 键长 trend 互验：对比优化后 Cu-20 与 SnCu-20 基底平均 Cu–O 键长。",
        location={"part": "word/document.xml", "paragraph": 33}, style="ListBullet")

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
        location={"part": "word/document.xml", "paragraph": 22}, style="ListBullet")
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
    put(155, "Computational Details:\nAll spin-polarized density functional theory (DFT) calculations were performed using the Quickstep module of the CP2K package within the Gaussian and plane waves (GPW) framework. The Perdew-Burke-Ernzerhof (PBE) functional combined with Grimme's DFT-D3(BJ) dispersion correction was employed to describe exchange-correlation and van der Waals interactions. Core electrons were represented by Goedecker-Teter-Hutter (GTH) pseudopotentials explicitly matched to double-zeta valence polarized molecularly optimized basis sets: GTH-PBE-q11 / DZVP-MOLOPT-SR-GTH-q11 for Cu, GTH-PBE-q14 / DZVP-MOLOPT-SR-GTH-q14 for Sn (explicitly treating the 4d semicore electrons), and GTH-PBE-q4/q6/q1 / DZVP-MOLOPT-GTH for C, O, and H, with a plane-wave density cutoff of 500 Ry and a relative cutoff of 60 Ry. To construct computationally tractable, charge-neutral local models representative of the tannic-acid-derived metal-coordination environment, four-gallate dinuclear coordination motifs chelating two Cu2+ centers (Cu-20: [Cu2(C7H5O5)4]0 + Cu13, 70 support atoms + 13 cluster atoms = 83 atoms, 417 valence electrons, net charge 0) and a Sn(IV)-containing oxygen-coordinated polyphenol environment bridging Cu2+ with Sn4+ accompanied by charge-compensating ligand deprotonation and a coordinating H2O molecule (SnCu-20: [CuSn(C7H5O5)2(C7H4O5)2(H2O)]0 + Cu13, 71 support atoms + 13 cluster atoms = 84 atoms, 426 valence electrons, net charge 0, without Cu-Sn alloying or discrete oxide phases) were built to match the local Cu-O bond distances derived from EXAFS fitting. An identical icosahedral Cu13 cluster was anchored on both supports; theoretical Cu-Cu interatomic distances were compared with EXAFS bond-length trends while noting that ensemble-averaged experimental coordination numbers are not directly equivalent to those of an isolated finite cluster. All models were centered in a 30.0 × 30.0 × 30.0 Å3 cubic cell with non-periodic boundary conditions enforced in both the cell and Poisson solver (PERIODIC NONE, Martyna-Tuckerman solver), verified against a 34.0 × 34.0 × 34.0 Å3 cell to ensure full electron-density tail decay.\n\nInitial cluster-support orientations and *HCCO adsorption configurations (including representative top and cluster-edge sites) were pre-relaxed using the Atomic Simulation Environment (ASE) coupled with the MACE-MP-0 machine learning interatomic potential (fmax < 0.05 eV/Å) solely as a structure generator without relying on MACE energy rankings to eliminate distinct coordination topologies or adsorption sites. For each system, 3-4 chemically distinct candidate configurations were subsequently optimized at the DFT level using matrix diagonalization with Fermi-Dirac smearing (300 K) and Broyden density mixing (force threshold < 0.01 eV/Å, SCF threshold 10^-6 Ha) after verifying the spin multiplicities of isolated fragments and odd/even-electron full complexes (doublet/quartet for Cu-20 and singlet/triplet for SnCu-20). Thermodynamic reaction free energies (ΔG = ΔE_DFT + ΔE_ZPE - TΔS) for the competing single-(H+/e-) protonation branches (*HCCO + H+ + e- → *H2CCO vs. *HCCO + H+ + e- → *HCCOH) were evaluated via the computational hydrogen electrode (CHE) model at U = 0 V vs. RHE and T = 298.15 K, noting that electrode potential and pH terms cancel identically in the relative selectivity difference (ΔΔG = ΔG_*H2CCO - ΔG_*HCCOH). Zero-point energy and entropic corrections for adsorbed intermediates were obtained via partial Hessian vibrational analyses implemented through ASE finite displacements (±0.01 Å) interfaced with CP2K static force evaluations (SCF threshold tightened to 10^-8 Ha, keeping the 70/71-atom support and Cu13 cluster fixed under the local vibrational approximation). Ketene desorption (*H2CCO → H2CCO(g) + *) was evaluated separately while neglecting vibrational free-energy changes of the bare catalyst framework. Electrostatic implicit solvation sensitivity checks (SCCS with ε = 78.4) and basis-set sensitivity checks (TZV2P-MOLOPT-GTH) were carried out on key states. Charge density differences (Δρ = ρ_total - ρ_Cu13 - ρ_support, evaluated on identical grids, cells, and basis sets with neutral fragment states), Bader charges, and vacuum-aligned projected density of states (PDOS) were processed using Multiwfn 3.8.", kind="table_cell",
        location={"part": "word/document.xml", "table": 9, "row": 2, "column": 1})
    put(158, "Copy-Ready English Text: Neutral & Scope-Bounded Results Report Template (Frozen v4.1)",
        kind="table_cell",
        location={"part": "word/document.xml", "table": 10, "row": 1, "column": 1})
    return blocks



def _corr_manifest(blocks: list[ExtractedBlock] | None = None) -> dict:
    return build_project_manifest(
        blocks or _run04_blocks(),
        project_id="corr_dft_v4_1",
        claim_enricher=extract_corr_v41_claims,
        unresolved_fields_extractor=extract_corr_v41_unresolved_fields,
    )


class RealDocxRun04RegressionTests(unittest.TestCase):
    def test_real_charge_cells_split_scalar_from_explanation_without_conflict(self):
        manifest = _corr_manifest()
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
        manifest = _corr_manifest()
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

    def test_same_field_same_scope_different_labels_and_scalar_values_still_blocks(self):
        diagnostics = detect_conflicts([
            {"field": "canonical_parameter", "label": "Primary value", "value": "0.01",
             "context": {"system_id": "model-a", "work_package": "WP2"},
             "evidence_id": "ev-label-a"},
            {"field": "canonical_parameter", "label": "Alternative setting", "value": "0.02",
             "context": {"system_id": "model-a", "work_package": "WP2"},
             "evidence_id": "ev-label-b"},
        ])
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "PLAN_FIELD_CONFLICT")
        self.assertTrue(diagnostics[0].blocks_execution)
        self.assertEqual(list(diagnostics[0].evidence_ids), ["ev-label-a", "ev-label-b"])

    def test_distinct_output_artifacts_coexist_but_same_artifact_contents_conflict(self):
        different_artifacts = [
            {"field": "output_document", "label": "Output", "artifact_identity": "method-section",
             "value": "First output content", "evidence_id": "ev-output-a"},
            {"field": "output_document", "label": "Output", "artifact_identity": "results-template",
             "value": "Second output content", "evidence_id": "ev-output-b"},
        ]
        self.assertEqual(detect_conflicts(different_artifacts), [])

        same_artifact = [
            {"field": "output_document", "label": "Output", "artifact_identity": "method-section",
             "value": "Approved method section content A", "evidence_id": "ev-output-c"},
            {"field": "output_document", "label": "Output", "artifact_identity": "method-section",
             "value": "Mutually exclusive method section content B", "evidence_id": "ev-output-d"},
        ]
        diagnostics = detect_conflicts(same_artifact)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].code, "PLAN_FIELD_CONFLICT")
        self.assertTrue(diagnostics[0].blocks_execution)

    def test_same_field_long_prose_with_different_labels_still_blocks_by_default(self):
        diagnostics = detect_conflicts([
            {"field": "canonical_method", "label": "First description",
             "value": "The system uses the PBE exchange correlation functional.",
             "evidence_id": "ev-prose-a"},
            {"field": "canonical_method", "label": "Second description",
             "value": "The system uses the BLYP exchange correlation functional.",
             "evidence_id": "ev-prose-b"},
        ])
        self.assertEqual(len(diagnostics), 1)
        self.assertTrue(diagnostics[0].blocks_execution)

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
        manifest = _corr_manifest()
        headings = [s for s in manifest["sections"]]
        self.assertTrue(any(s["heading"].startswith("研究的科学问题") and s["heading_source"] == "explicit_numbering"
                            for s in headings))
        self.assertTrue(any(s["heading"].startswith("实验背景") and s["level"] == 2
                            for s in headings))
        self.assertEqual(len(headings), 18)
        self.assertFalse(any(s["heading"].startswith("30.0 Å") for s in headings))
        self.assertFalse(any("1. 局域结构" in s["heading"] for s in headings))
        wp4 = next(t for t in manifest["tasks"] if t["work_package"] == "WP4")
        self.assertEqual(set(wp4["evidence_ids"]),
                         {"docx-block-000132", "docx-block-000133", "docx-block-000134", "docx-block-000135"})
        self.assertEqual({c["work_package"] for c in manifest["task_count_claims"]}, {"WP4"})

    def test_heading_recognition_respects_word_styles_and_list_metadata(self):
        blocks = [
            ExtractedBlock("paragraph", "1.1 Normal style numbered heading",
                           {"paragraph": 1}),
            ExtractedBlock("paragraph", "1.1 Numbered list item",
                           {"paragraph": 2}, style="ListNumber",
                           list_info={"num_id": "9", "level": "1"}),
            ExtractedBlock("paragraph", "1.1 List metadata without list style",
                           {"paragraph": 3}, list_info={"num_id": "10", "level": "1"}),
            ExtractedBlock("paragraph", "1.1 Bullet list item",
                           {"paragraph": 4}, style="ListBullet"),
            ExtractedBlock("paragraph", "Ordinary prose mentioning section 1.1",
                           {"paragraph": 5}),
        ]
        blocks.extend(
            ExtractedBlock("paragraph", f"Heading level {level}",
                           {"paragraph": 5 + level}, style=f"Heading{level}")
            for level in range(1, 10)
        )
        manifest = build_project_manifest(blocks, project_id="generic")
        headings = manifest["sections"]
        self.assertEqual(
            [(item["heading"], item["heading_source"]) for item in headings],
            [("Normal style numbered heading", "explicit_numbering")]
            + [(f"Heading level {level}", "word_style") for level in range(1, 10)],
        )

    def test_corr_v41_extraction_is_opt_in_and_not_part_of_generic_manifest(self):
        blocks = _run04_blocks()
        generic = build_project_manifest(blocks, project_id="unrelated-project")
        generic_added_mos = [
            claim for claim in generic["claims"]
            if claim.get("field") == "added_mos" and "docx-block-000103" in claim.get("evidence_ids", [])
        ]
        self.assertEqual(generic_added_mos, [])
        self.assertFalse(any(claim.get("field") == "reaction_intermediate" for claim in generic["claims"]))
        self.assertFalse(any(claim.get("field") == "support_motif" for claim in generic["claims"]))
        self.assertFalse(any(
            item.get("field") == "tasks.WP4.total_force_evaluations"
            for item in generic["unresolved_structured_fields"]
        ))

        adapted = _corr_manifest(blocks)
        added = [claim for claim in adapted["claims"] if claim.get("field") == "added_mos"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["value"], "80")
        self.assertEqual(added[0]["evidence_ids"], ["docx-block-000103"])

    def test_added_mos_is_extracted_from_real_table_cell_and_keeps_all_cell_evidence(self):
        manifest = _corr_manifest()
        added = [c for c in manifest["claims"] if c.get("field") == "added_mos"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["value"], "80")
        self.assertEqual(added[0]["evidence_ids"], ["docx-block-000103"])
        scf = [c for c in manifest["claims"] if c.get("field") == "scf"]
        self.assertTrue(any("ADDED_MOS 80" in c["source_text"] for c in scf))
        self.assertEqual(added[0]["source"], {
            "part": "word/document.xml", "table": 6, "row": 5, "column": 2
        })

    def test_profile_104_reconciliation_matches_all_csv_rows_and_evidence(self):
        manifest = _corr_manifest()
        profile = load_v41_profile()
        _field_provenance, reconciliation = _profile_provenance(manifest, profile)

        self.assertEqual(len(reconciliation), 104)
        by_field = {item["field"]: item for item in reconciliation}
        self.assertEqual(len(by_field), 104)

        csv_path = (
            Path(__file__).resolve().parents[1]
            / "docs/reports/real_docx_run04_20261127/PR3_PROFILE_RECONCILIATION_AFTER_FIX.csv"
        )
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        self.assertEqual(len(csv_rows), 104)
        self.assertEqual(len({row["profile_field"] for row in csv_rows}), 104)

        expected_counts = Counter(row["new_reconciliation_status"] for row in csv_rows)
        self.assertEqual(expected_counts, {
            "consistent": 39,
            "needs_review": 44,
            "profile_only": 21,
        })
        actual_counts = Counter(item["status"] for item in reconciliation)
        self.assertEqual(actual_counts, expected_counts)

        evidence_ids = {item["evidence_id"] for item in manifest["evidence"]}
        self.assertTrue(evidence_ids)
        def collect_ids(value):
            found = []
            if isinstance(value, dict):
                if value.get("evidence_id"):
                    found.append(value["evidence_id"])
                if isinstance(value.get("evidence_ids"), list):
                    found.extend(value["evidence_ids"])
                for child in value.values():
                    found.extend(collect_ids(child))
            elif isinstance(value, list):
                for child in value:
                    found.extend(collect_ids(child))
            return found

        all_referenced_ids = set(collect_ids({
            key: value for key, value in manifest.items() if key != "evidence"
        }))
        self.assertTrue(all_referenced_ids)
        self.assertTrue(all_referenced_ids.issubset(evidence_ids))
        for row in csv_rows:
            field = row["profile_field"]
            self.assertIn(field, by_field)
            actual = by_field[field]
            csv_evidence_ids = (
                [item for item in row["new_evidence_ids"].split(";") if item]
            )
            with self.subTest(field=field):
                self.assertEqual(actual["field"], field)
                self.assertEqual(actual["status"], row["new_reconciliation_status"])
                self.assertEqual(actual["docx_status"], row["new_docx_status"])
                self.assertEqual(actual["docx_evidence_ids"], csv_evidence_ids)

                if actual["status"] == "consistent":
                    self.assertEqual(actual["docx_status"], "docx_evidence")
                    self.assertTrue(actual["docx_evidence_ids"])
                    self.assertTrue(set(actual["docx_evidence_ids"]).issubset(evidence_ids))
                elif actual["status"] == "needs_review":
                    self.assertEqual(actual["docx_status"], "unresolved")
                    self.assertTrue(actual["docx_evidence_ids"])
                    self.assertTrue(set(actual["docx_evidence_ids"]).issubset(evidence_ids))
                    self.assertTrue(actual["unresolved_docx_sources"])
                else:
                    self.assertEqual(actual["status"], "profile_only")
                    self.assertEqual(actual["docx_status"], "absent")
                    self.assertEqual(actual["docx_evidence_ids"], [])
                    self.assertEqual(actual["docx_values"], [])
                    self.assertEqual(actual["unresolved_docx_sources"], [])

        geometry_eps = by_field["method.scf_eps_scf_ha.geometry_optimization"]
        force_eps = by_field["method.scf_eps_scf_ha.local_hessian_force"]
        self.assertEqual(set(geometry_eps["docx_evidence_ids"]),
                         {"docx-block-000155", "docx-block-000103"})
        self.assertIn("docx-block-000155", force_eps["docx_evidence_ids"])
        self.assertIn("docx-block-000052", force_eps["docx_evidence_ids"])
        self.assertTrue(any(
            item["field"] == "method.scf_eps_scf_ha"
            and "docx-block-000103" in item["evidence_ids"]
            for item in manifest["unresolved_structured_fields"]
        ))

        # Uncertain orientation and spin scope remain review-only; never infer the Profile's 15.
        for field in (
            "tasks.WP1.support_cluster_docking_orientation_count",
            "tasks.WP1.orientation_scope",
            "systems.Cu-20.cluster.multiplicities[0]",
            "systems.SnCu-20.support_multiplicities[0]",
            "tasks.WP3.protonation_products_per_catalyst",
            "tasks.WP5.sccs_single_points",
            "topology_requirements.explicit_coordination_bonds",
        ):
            self.assertEqual(by_field[field]["status"], "needs_review")
        self.assertFalse(any(c.get("value") == 15 for c in manifest["claims"]))


if __name__ == "__main__":
    unittest.main()
