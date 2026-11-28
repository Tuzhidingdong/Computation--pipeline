# Agent B — run_04 原始证据驱动的 PR #3 修复报告

更新日期：2026-11-28  
仓库：Tuzhidingdong/Computation--pipeline  
PR：[#3](https://github.com/Tuzhidingdong/Computation--pipeline/pull/3)  
用户指定基线 HEAD：243aa65b45b9446216bd96c468252a8bc7b0a91b  
本报告所依据的最终代码/测试/状态 CSV HEAD：d66570408fb3682bfc36c029bc9c5e645657bcfd

## 1. 证据来源与验证边界

从独立诊断分支 diagnostics/pr3-real-docx-run04-evidence-20261127 读取了五份 run_04 报告：

- PR3_REAL_DOCX_ROOT_CAUSE_EVIDENCE.md
- PR3_CONFLICT_CLAIMS_DETAIL.json
- PR3_PROFILE_SOURCE_BINDING_DETAIL.csv
- PR3_PARAGRAPH_STYLE_INVENTORY.csv
- PR3_ADDED_MOS_TRACE.json

关键判断以报告中的原始文本、evidence ID、XML paragraph/table/row/column 位置为依据。没有再等待本地 Windows 路径，也没有用 Profile 值代替 DOCX 证据。

验证边界：诊断分支提供了 run_04 已提取的原始证据片段及位置，但没有包含 Frozen DOCX 二进制文件或完整 160-block 提取包。因此新增回归使用报告中的真实原文片段、原始 evidence ID 和真实源位置构造 ExtractedBlock，直接测试 build_project_manifest() 与 v4.1 Profile reconciliation。这不是把原始 .docx 重新交给 read_frozen_docx() 的完整端到端文件测试。报告不把两种验证混为一谈。

## 2. 三项历史冲突的最终分类

### 2.1 charge — FALSE_CONFLICT，已修复

真实来源：
- docx-block-000079：word/document.xml，table 5，row 6，column 2
- docx-block-000080：word/document.xml，table 5，row 6，column 3

两格数值部分均为 CHARGE = 0；分号后的自旋说明分别描述 Cu-20 与 SnCu-20 的候选自旋，不是 charge 值的一部分。

修复：将 CHARGE 的数值标量与分号后的解释文字分离；数值 0 参与比较，解释原文保存在 value_explanation，原始 source_text 和 evidence ID 不丢弃。两条真实 claim 不再形成冲突。另加 CHARGE=0 对 CHARGE=1 的 blocking regression，确保真实数值差异仍然阻塞。

### 2.2 ase_vibrations_cp2k — SUMMARY_AND_DETAIL_CONSISTENT，不是冲突

真实来源：
- 表格摘要：docx-block-000050、000051、000052，table 4，row 4，columns 1–3
- 段落详细说明：docx-block-000113，paragraph 27

表格行描述冻结基底与 Cu13 的局部 Sub-Hessian，并明确 ASE Vibrations、吸附质有限位移 ±0.01 Å、CP2K ENERGY_FORCE、波函数复用、EPS_SCF 1.0E-8 Ha 和 Python Hessian 组装。段落 27 进一步说明不使用 MODE_SELECTIVE、吸附质原子数、6 个吸附态与 174 次力调用，以及冻结基底/团簇的局部振动近似。两者是摘要与详细实现的层级关系，关键实现参数相符，没有互斥参数。

修复：保留表格行的三个 cell evidence 和段落 evidence；数值字段（位移、SCF 精度等）分别从原文提取，不把摘要/详细说明当作单值字段的互斥取值。新增同一参数真正不同仍然 blocking 的回归。

### 2.3 copy_ready_english_text — DISTINCT_OUTPUT_ARTIFACTS，不是冲突

真实来源：
- docx-block-000154：table 9，row 1，column 1，Computational Details (Frozen Baseline v4.1)
- docx-block-000158：table 10，row 1，column 1，Neutral & Scope-Bounded Results Report Template (Frozen v4.1)

它们是两个不同输出模板，不是同一输出槽位的两个候选文本。输出类型按多个 artifact 处理，不进行单值互斥冲突判定；两条 claim 与原始源位置都保留。

## 3. Profile 104 条记录的最终状态

机器可读逐行结果：
docs/reports/real_docx_run04_20261127/PR3_PROFILE_RECONCILIATION_AFTER_FIX.csv

104 条状态总数：

| 最终状态 | 数量 | 含义 |
|---|---:|---|
| consistent | 39 | 有明确 DOCX 原文及证据 ID，Profile 值与 DOCX 值一致 |
| needs_review | 44 | 原文有相关内容，但 system/WP 归属、字段粒度、计数、单位或原子级映射尚不足以确认 |
| profile_only | 21 | 对该 Profile 字段未找到相应 DOCX 内容；未制造 DOCX evidence |

与 run_04 原始 CSV 的旧状态逐项比较：

| 旧状态 → 新状态 | 条数 |
|---|---:|
| profile_only → consistent | 33 |
| profile_only → needs_review | 44 |
| profile_only → profile_only | 21 |
| needs_review → consistent | 6 |

### 3.1 consistent 的 39 条

- 系统模型（12）：Cu-20 与 SnCu-20 的 support motif、support atom count、complete atom count、valence electron count、net charge，以及 Cu-20 的 Cu13 cluster formula/atom count；SnCu-20 的对应字段也有独立证据。
- 方法参数（20）：CP2K Quickstep/GPW、PBE、D3(BJ)、500 Ry、60 Ry、spin-polarized、300 K、PERIODIC NONE、MT、30/34 Å 两盒子、force threshold、带单位的两种 SCF threshold、局部位移、冻结支持体与 Cu13、CHE 温度/电位、SCCS dielectric、TZV2P。
- 任务参数（4）：WP2 两盒子尺寸；WP4 的 6 个吸附态 Hessian 和 174 次快速单点力调用。
- 科学反应标识（3）：*HCCO 反应中间体及 *H2CCO、*HCCOH 两条质子化产物，由 CHE 方程原文直接支持。

每一条都在 CSV 中保存实际 evidence ID；没有给 Profile 值虚构 DOCX evidence ID。

### 3.2 needs_review 的 44 条

主要包括：

- Cu-20 / SnCu-20 的完整元素式：DOCX 明确给出 support motif、Cu13、总原子数和价电子数，但没有一个可直接绑定的 complete elemental formula 字符串。
- 两个体系的 cluster/support/complete-model multiplicities：table 5 row 6 的自旋候选确实存在，但列与 system 的完整归属和 Profile 各列表映射仍需确认；没有擅自分配。
- WP1：orientation 数值和 scope、3–4 候选数、MACE fmax < 0.05 eV/Å、孤立片段自旋候选、summary single-point count。原文有相关描述，但不能据此确认全部 Profile 计数或 WP1 归属。
- WP2：SnCu-20 代表性模型被提及，但原句没有直接给出 Profile 所要求的独立数值计数。
- WP3：HCCO 候选数、每催化剂产物数、H2/H2CCO gas-reference 与 WP3 的字段归属。
- WP4：4/5/5 吸附质原子数在 paragraph 27 有原文，但该段不直接提供 Profile 所要求的每催化剂/WP4 归属。
- WP5：SCCS 与 TZV2P sensitivity checks 确实被提及，但没有明确给出 Profile 中的 6/4 个 single-point 数量。
- thermodynamic_only：原文明确给出 CHE 热力学分支，但没有明确断言整个范围“仅”限于 thermodynamics。
- topology：元素、键级、配位键、donor、formal charge、自旋和 3D 约束有相关化学描述，但缺少完整 atom-indexed topology，故标为 needs_review 而不是伪造完整结构。

### 3.3 profile_only 的 21 条

包括 schema/project metadata、WP5 可选替代 Sn 配位模型的最大数量、未在 DOCX 中找到的五项 prohibited-scope 声明、两组由 Profile/规划层记录的 blocker 字段，以及 DOCX 未提供的 atom IDs / “formula alone is insufficient” 要求。

WP1 orientation 的处理特别说明：DOCX 确实提到 cluster-support orientations，但没有给出 Profile 的 15 个数量或 per catalyst / across both systems 范围。因此这两项是 needs_review，不是把 15 当成已被 DOCX 证实，也不是错误地标为 profile_only。

## 4. ADDED_MOS 80 的真实 table/cell 提取

run_04 trace 的原始链：

| Evidence ID | 真实位置 | 内容 |
|---|---|---|
| docx-block-000102 | table 6，row 5，col 1 | SCF 收敛策略标签 |
| docx-block-000103 | table 6，row 5，col 2 | 主路线设置，含 ADDED_MOS 80 |
| docx-block-000104 | table 6，row 5，col 3 | 不混写 OT 与 Broyden mixing 的纠偏说明 |

修复后，解析器从真实表格单元格 000103 提取独立 added_mos = 80 claim，并保留源位置 table=6,row=5,column=2。原始 SCF 行级 claim 仍然保留 000102/000103/000104 的完整证据链。不是通过独立段落的合成 ADDED_MOS 80 测试冒充真实表格提取。

## 5. 章节、WP 与 scope

- run_04 paragraph inventory：45 段；35 个 Normal、10 个 ListBullet、Heading1–9 为 0。
- 从真实编号标题识别出 18 个 section evidence：000003/004/009/035/036/040/060/061/085/088/089/112/115/141/147/148/153/157。
- 普通 1. ... ListBullet 项不提升为 Heading；回归中明确包含 docx-block-000144。
- WP2 只在原文“WP2 试算门控”处建立 scope，并关联其双盒子验证项。
- WP4 仅在 table 7 row 5 的首格明确写有 WP4 后，建立该行 WP4 task；保留该行 000132–000135 的 cell evidence。
- table 5 的自旋候选未被猜测性分配到系统；WP1/WP3/WP5 中存在原文但缺少明确 WP/system 映射的字段均保留为 needs_review。
- inline Cu-20: / SnCu-20: 标记用于 block 155 中有明确标签的系统字段，不将系统范围扩散到相邻无关段落。

## 6. 新旧 Manifest 的实质差异

依据 run_04 原始 root-cause 报告的旧 Manifest 摘要，与本轮真实 evidence-block 回归生成的 Manifest 结构作定向比较：

| 部分 | 旧 run_04 | 修复后证据回归 |
|---|---|---|
| sections | 空 | 18 个有证据 ID 的编号章节 |
| systems / models | 顶层 systems 为空，模型属性未结构化 | block 155 明确标识 Cu-20 / SnCu-20，已提取有证据的模型属性；完整元素式仍 unresolved |
| method | 10 个以大段文本命名的键，缺少 added_mos | 明确参数字段可绑定原文；added_mos=80 从 table 6/cell 2 提取 |
| tasks | 顶层 tasks 为空 | WP2 gate 与 WP4 表格行产生 evidence-backed task blocks；无可靠 WP scope 的数量不被强行放入任务 |
| Profile reconciliation | 98 profile_only、6 needs_review，全部没有 DOCX evidence ID | 39 consistent、44 needs_review、21 profile_only，按字段保存真实来源 ID |
| 诊断 | 三项历史 false-positive blocking conflicts | 三项具体误报不再触发；同字段真实不同值仍阻塞 |

边界：这是针对 run_04 已发布原始证据块的结构差异，不宣称已在完整 Frozen DOCX 二进制上执行全量编译并生成两个完整 JSON Manifest 的逐节点 diff。完整 .docx 未包含在诊断分支；选定证据块的真实原文与 source location 已进入本轮回归。

## 7. 回归、CI 与交付

- 新增 tests/test_real_docx_run04_regressions.py：真实 CHARGE 分隔、两类描述/输出分类、同字段真实差异阻塞、Normal-style 编号标题、ListBullet 不误识别、真实 table cell ADDED_MOS 80、Profile 104 项证据状态、单位等价性与缺失单位检查。
- GitHub Actions run #517 / #518 均在最终 CSV 对照提交 d66570408fb3682bfc36c029bc9c5e645657bcfd 通过。
- run #518：128 tests total，126 passed，2 optional upstream integration tests skipped，0 failures / 0 errors；python -m compileall -q pipeline_contracts tests examples passed。
- PR #3 当前保持 Draft、open、unmerged；base SHA 未变。
- 本轮未修改 project_profile.json 的科学值，未再次开发 P0 GBK stdout 修复。
- 未调用 resolve-v41-planning；未选择 WP1 科学决策；未创建原子图/键连接/配位数据；未提交 CP2K、HPC、Slurm 或生产 DFT。
- 未修改 Agent C / PR #4 分支。
