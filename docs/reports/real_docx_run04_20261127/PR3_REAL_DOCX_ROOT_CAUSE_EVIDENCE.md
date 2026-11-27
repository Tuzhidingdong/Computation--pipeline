# PR #3 run_04 冲突与结构化映射根因取证

只读取 `run_04_pr3_head_c0fe` 已生成的 Manifest、checkout 源码和原文件；未重新运行编译器，未修改任何源码、Manifest、DOCX 或环境。
完整机器可读证据见 `PR3_CONFLICT_CLAIMS_DETAIL.json`、`PR3_PROFILE_SOURCE_BINDING_DETAIL.csv`、`PR3_PARAGRAPH_STYLE_INVENTORY.csv`、`PR3_ADDED_MOS_TRACE.json`。

---

## 1. 三条 `PLAN_FIELD_CONFLICT` 完整取证

Manifest 中 `PLAN_FIELD_CONFLICT` 共 **3** 条。三条均 `severity=error`、`blocks_execution=true`；
**diagnostics 中没有 `scope` 字段**（既不携带 system_id 也不携带 work_package），取证时按“无 scope”记录。

### 1.1 `charge`
- `evidence_ids`: `docx-block-000079`, `docx-block-000080`
- 位置与原文：
  - `000079` @ `word/document.xml` table 5 row 6 column 2：
    `CHARGE = 0；先校验孤立中性 Cu13（M=2, 4, 6）与中性基底（2×Cu²⁺, M=1, 3）自旋初态，再对比完整奇数电子体系 M=2 与 M=4 锁定基态。`
  - `000080` @ table 5 row 6 column 3：
    `CHARGE = 0；孤立中性基底（1×Cu²⁺ d⁹ + 闭壳层 Sn⁴⁺ d¹⁰, M=2）与 Cu13 组合后，对比完整偶数电子体系 M=1 与 M=3（必要时 M=5）锁定基态。`
- 两个 value group：
  - `normalised_value = "0;先校验孤立中性 cu13(m=2,4,6)与中性基底(2×cu2+,m=1,3)自旋初态,再对比完整奇数电子体系 m=2 与 m=4 锁定基态。"`；`raw_values=[上列 000079 全文]`
  - `normalised_value = "0;孤立中性基底(1×cu2+d9+闭壳层 sn4+d10,m=2)与 cu13 组合后,对比完整偶数电子体系 m=1 与 m=3(必要时 m=5)锁定基态。"`；`raw_values=[上列 000080 全文]`
- 两条 claim 均 `field="charge"`、`label="CHARGE"`、`unit=null`、`status=requires_confirmation`、`context.system_id=null`、`context.work_package=null`。

### 1.2 `ase_vibrations_cp2k`
- `evidence_ids`: `docx-block-000113`（paragraph 27）、`000050`、`000051`、`000052`（table 4 row 4）
- 两个 group 的 `normalised_value` 分别为段落 27 的局部振动实现全文、表 4 的 Sub-Hessian 单元格全文；`raw_values` 为对应原文；`evidence` 记录含原始 `source_text` 与位置。
- 相关 claim 共 2 条带 `field=ase_vibrations_cp2k`，另有 `wp4_ase_sub_hessian_che` 1 条（未触发该冲突）。

### 1.3 `copy_ready_english_text`
- `evidence_ids`: `docx-block-000154`（table 9 row 1 col 1）、`000158`（table 10 row 1 col 1）
- `normalised_value`：
  - `computational details(frozen baseline v4.1)`
  - `neutral & scope-bounded results report template(frozen v4.1)`
- 两条 claim 均 `field=copy_ready_english_text`，原文分别是两个模板标题。

### 相关 claim 总量
按 charge/CHARGE/ase_vibrations/copyready/copy_ready/english_text/sub_hessian/energy_force/mode_selective 等标签与字段检索，共 **35** 条相关 claim；字段分布：
`None:26`、`7080_charge:1`、`charge:2`、`ase_vibrations_cp2k:2`、`copy_ready_english_text:2`、`"":1`、`wp4_ase_sub_hessian_che:1`。
每条完整 claim（含 field/label/value/unit/evidence_id/evidence_ids/context/source/source_text/sources）已保存在 `PR3_CONFLICT_CLAIMS_DETAIL.json`。

---

## 2. CHARGE 两个已知 claim 都是 0，为什么仍然冲突

**不是还有第三个 claim 参与**。带 `field="charge"` 的 claim 只有 `000079`、`000080` 两条；
另有一条含 CHARGE 字样的 claim `docx-block-000062`，其字段是 `7080_charge`，状态 `requires_confirmation`，
出现在 `unresolved_structured_fields`，**未参与 charge 冲突**。

根因（源码级，只读）：

1. `pipeline_contracts/plan_compiler/manifest.py:17`
   `_LABEL_VALUE = re.compile(r"^\s*(?P<label>[^:：=]{2,100})\s*[:：=]\s*(?P<value>.+?)\s*$")`
   对 `CHARGE = 0；先校验……` 按第一个 `=` 切分，label=`CHARGE`，value=`0；先校验……`——**整句说明都被当作 value**，而不是仅数值 `0`。
2. `manifest.py:217-233` `_parse_label_value()` 使用该正则；`manifest.py:85-90` `_normalise_label()` 把 label 规范成 `charge`。
3. `manifest.py:93-106` `_normalise_field_value()` 只做 NFKC、折叠空白、规范运算符两侧空格和“数字+单位”间隔；它**保留数字、单位、标点和整句文字**（注释写明 “Normalise presentation only; preserve numbers, units, punctuation and operators”）。
4. `manifest.py:152-208` `detect_conflicts()` 以 `(field, system_id, work_package)` 分组，再按 `_normalise_field_value(value)` 分 value group；`len(value_groups)>1` 即产生 `PLAN_FIELD_CONFLICT`。
5. 两处 `0` 后面的解释文字不同 → 两个不同 normalised value → 冲突。诊断新增的 `conflicting_values` 已把这一点显示出来：两个 `normalised_value` 都以 `0;` 开头，但后半句不同。

结论：**数值相同、解释文字不同导致的误报**；不是 DOCX 中出现了不同的 charge 值。交 Agent B，未修改代码。

---

## 3. Profile 对照（`profile_reconciliation`）

完整 104 行已写入 `PR3_PROFILE_SOURCE_BINDING_DETAIL.csv`（列：profile_field / profile_value / docx_status / reconciliation_status / docx_values / evidence_ids / unresolved_docx_sources / task_requested）。实测分布：
- `status`: `profile_only` 98、`needs_review` 6
- `docx_status`: `absent` 98、`unresolved` 6
- 所有条目 `docx_evidence_ids=[]`（无一条 Profile 字段被绑定 DOCX evidence ID）

任务指定项的实际取值（全部 `docx_status=absent`，`evidence_ids=[]`）：
- `systems.Cu-20.complete_formula=Cu15C28H20O20`、`complete_atom_count=83`、`explicit_valence_electrons=417`、`charge=0`
- `systems.SnCu-20.complete_formula=Cu14SnC28H20O21`、`complete_atom_count=84`、`explicit_valence_electrons=426`、`charge=0`
- `method.xc=PBE`、`method.dispersion=D3(BJ)`、`method.cutoff_ry=500`、`method.rel_cutoff_ry=60`
- `method.spin_polarized=true`、`method.smearing_temperature_K=300`、`method.sccs_dielectric=78.4`、`method.basis_sensitivity=TZV2P`
- `method.periodicity=NONE`、`method.poisson_solver=MT`、`method.cell_sizes_angstrom=[30,34]`
- `tasks.WP4.total_force_evaluations=174`
- `tasks.WP1.support_cluster_docking_orientation_count=15`、`orientation_scope=null`、`isolated_fragment_spin_candidate_count=6`、`summary_fragment_single_point_count=4`
- `tasks.WP2` / `WP3` / `WP5` 的数量与参数均在 CSV 中逐行保留

**`tasks.WP1.support_cluster_docking_orientation_count=15`**：`docx_status=absent`、`evidence_ids=[]`、`status=profile_only`；未伪造 DOCX evidence ID。
Profile 来源为 `projects/corr_dft_v4_1/project_profile.json`，其 `description` 自述为从 `TASK_PLAN_v1.0.0.md` 转录且待 DOCX 证据核对。

另需注意：run_04 的顶层 `systems=[]`、`tasks=[]`，`method` 改为 10 个 DOCX 派生键（`ase`, `cp2k`, `cell`, `ase_vibrations_cp2k`, `fig_c_che`, `4_che`, `5_hessian`, `cp2k_2024_quickstep_gpw`, `scf`, `wp4_ase_sub_hessian_che`）；run_03 中那 16 个扁平 method 值现在只存在于 `profile_overlay.values.method`。

---

## 4. 45 个 paragraph evidence block 与 `sections=[]`

完整清单见 `PR3_PARAGRAPH_STYLE_INVENTORY.csv`（45 行：evidence_id / paragraph_index / style / list_info / text）。
实测 style 分布：
- `None`（Normal）：**35**
- `ListBullet`：**10**
- `Heading1`–`Heading9`：**0**（不存在任何 Heading 样式）

WP1–WP5 的段落/表格位置（基于 evidence 文本）：
- WP1：段落无；表格 6、7
- WP2：段落 21；表格 7
- WP3：段落无；表格 3、7
- WP4：段落无；表格 7
- WP5：段落无；表格 7

`sections=[]` 的事实原因：所有章节标题（如 `一、研究的科学问题…`、`五、两阶段门控执行计划…`）在 DOCX 中都是普通正文段落（style `None`），没有任何 Heading1–9 样式；解析器未从纯文本编号推导章节层级，因此 `sections` 为空。原文仍完整保留在 paragraph evidence block 中。

---

## 5. `ADDED_MOS 80` 追踪

完整结果见 `PR3_ADDED_MOS_TRACE.json`。

- 原始 evidence：`docx-block-000103`（table 6 row 5 col 2）包含 `ADDED_MOS 80`；同 SCF 行的 `000102`（label 单元格）与 `000104`（说明单元格）共同构成 SCF 原文。
- 真实 claim：`field=null`（claim 自身无 field），`label="SCF 收敛策略（明确区分路线）"`，`value` 为整段 SCF 文字，其中包含 `ADDED_MOS 80`；evidence_ids 为 `000102/000103/000104`；status=`requires_confirmation`。
- `field_provenance` 路径为 `method.scf`，`status=docx_evidence`，含同一组 evidence_ids 与 raw_value。
- 顶层 `method` 的 10 个键中**没有** `added_mos`；Profile 的 method 中也没有 `added_mos`。
- 为什么没有独立字段：`manifest.py:217-233` 仅在 label-value 或“机器式隐式键”（含 `_` 或全大写）形式下产生字段；真实 DOCX 的 `ADDED_MOS 80` 嵌在标签为 `SCF 收敛策略（明确区分路线）` 的多行单元格里，被按 `：` 切成 SCF 的 value。`manifest.py:36-42` 虽把 `added_mos` 列入 `_METHOD_TERMS`，但没有从单元格正文中二次抽取。
- 对照：`tests/test_plan_compiler.py:228-253` 用的是合成段落 `ADDED_MOS 80`，能被隐式键规则抽成 `method.added_mos`；真实 DOCX 不存在这种独立段落。因此合成测试通过不代表真实文档能抽出该字段。

---

## 6. 本轮结论与边界

- 三条 `PLAN_FIELD_CONFLICT` 均有真实 evidence 与原始 claim；`charge` 是数值相同、说明文字不同造成的误报，另两条同理（同类描述不同文本）。
- 所有 Profile 字段均保持 `profile_only` / `docx_status=absent`，未自行改状态；15 个 orientations 无 DOCX evidence。
- `sections=[]` 与 `method.added_mos` 缺失均有源码级与原文级解释。
- 未修改代码、Manifest、DOCX；未重新运行编译器；未调用科学决策接口；未运行 CP2K/HPC/Slurm。

交 Agent B 修复。
