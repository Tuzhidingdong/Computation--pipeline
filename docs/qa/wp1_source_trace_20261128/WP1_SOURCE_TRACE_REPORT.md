# WP1 科学决策阻断原始证据溯源审查报告

审查对象：`WP1_ORIENTATION_SCOPE_UNRESOLVED`、`WP1_FRAGMENT_SPIN_COUNT_MISMATCH`
角色：Tester / 溯源审查；未修改任何源码、DOCX、Profile、Manifest 或科学参数；未调用 `resolve-v41-planning`，未确认 Evidence Review，未批准模型，未运行任何计算。

## 0. 版本基准

| 资料 | SHA-256 |
|---|---|
| Frozen DOCX | `eaa40442835c533833d5328745b07517237ed1df08b7f78fb2fd137b7cff3ef6` |
| TASK_PLAN_v1.0.0.md（PR #6 checkout，`54a8a942`） | `9fe0acbc78023098997036ad264a89622c579feb3852c058845beff70dc4bbb1` |
| Project Profile | `c4f069ba50d1629d16da8322f976347fd46c154bc3fca541471994b509e6cd96` |
| DOCX Compilation Manifest | `89cc15f4e1dcebc5bb336073b509d0fb0cd1eecb91368b2089d956c472d896fa` |
| 历史记录 `AGENT_B_FROZEN_DOCX_PROVENANCE_FIX_20261127.md` | `d8f71124850c2637bff8a2af557e545d9a57b63e281298fdecbe4954a4122331` |

`TASK_PLAN_v1.0.0.md` 另有 `publish_repo` 中的副本 SHA `5590f757…900f32`，差异仅来自本地 `core.autocrlf` 行尾设置，**不是科学版本差异**，不作为权威依据。

---

## 1. 主对照表

关键词：DOCX 位置按 `table T row R col C` / `paragraph N`；TASK_PLAN 位置按 `L<n>`。

| 问题 | Frozen DOCX 原文及位置 | TASK_PLAN 原文及位置 | Profile 当前值 | 历史来源 | 分类 | 结论 |
|---|---|---|---|---|---|---|
| 15 个方向的原始定义 | **NOT_FOUND**。DOCX 中“15”仅出现于 `Cu15`（table 5 row 3 col 2）、几何跨度 `14.5–15.0 Å`（paragraph 21）等，无 15 个 docking orientations 的表述；table 7 row 2 col 2 仅写“ASE+MACE 预筛多种停靠方位” | `L192`: “pre-screen the v4.1-configured set of 15 support/cluster docking orientations” | `support_cluster_docking_orientation_count=15` | Profile 自述转录自 TASK_PLAN | `C. SOURCE_UNDERSPECIFIED` | 15 来自 TASK_PLAN，不来自 Frozen DOCX；仅数量，无范围 |
| 15 是每个催化剂还是两体系合计 | DOCX `table 7 row 2 col 2`: “ASE+MACE 预筛多种停靠方位（不单凭 MACE 淘汰拓扑），按化学合理性保留 3–4 个差异化候选送 CP2K…全弛豫”；`table 7 row 2 col 3`: “2 × (3~4) = 6~8 个基态候选全弛豫” — 仅说明保留量按催化剂计，未说明 15 的范围 | `L192`: “The manifest must explicitly state whether ‘15 orientations’ applies per catalyst or across both systems before calculating the task count; do not infer this from prose.” | `orientation_scope=null`，候选值 `per_catalyst` / `across_both_systems` | 历史报告：“WP1_ORIENTATION_SCOPE_UNRESOLVED: per_catalyst vs across_both_systems…choices … have not been selected” | `C. SOURCE_UNDERSPECIFIED` | **无法由已有资料唯一确定**；TASK_PLAN 明令不得从措辞推断 |
| Cu-20 / SnCu-20 是否分别有独立搜索任务 | DOCX `table 7 row 2 col 3`: “2 × (3~4) = 6~8 个基态候选全弛豫 + 自旋对比” → 两个模型各保留候选；`table 7 row 2 col 2` 分别列出 Cu-20 与 SnCu-20 | `L192`: “retain 3–4 structurally distinct candidates … for each catalyst”; `L437`: “DFT-relax the selected 3–4 structurally distinct candidates per catalyst” | `retained_structurally_distinct_candidates_per_catalyst={min:3,max:4}` | 同上 | `A. SOURCE_ALREADY_RESOLVES` | **保留候选按催化剂分别执行**已明确；未明确的是初始 15 的范围 |
| 初始结构生成、筛选与保留数量 | DOCX `table 7 row 2 col 2` item 3: “ASE+MACE 预筛多种停靠方位…按化学合理性保留 3–4 个差异化候选”；`paragraph 11`: Stage 1 完成两个基态模型试算与门控 | `L435`: “Generate the configured finite set of docking-orientation candidates”; `L436`: “Use ML pre-screening only within its documented validity range; retain chemically distinct candidates”; `L437`: 同上 | 3–4 per catalyst；`mace_fmax_ev_per_angstrom=0.05` | 无额外决策记录 | `A. SOURCE_ALREADY_RESOLVES` | 生成→预筛→保留 3–4→DFT 全弛豫链路明确 |
| MACE 参数对应阶段 | DOCX `table 4 row 2 col 3`: “仅用于快速消除空间位阻并生成预优化结构（fmax < 0.05 eV/Å）…不直接采信 MACE 能量排序…不得单独作为淘汰拓扑依据” | `L192`: “MACE is a geometry pre-screen only, with the configured `fmax < 0.05 eV/Å`, and cannot be the sole basis for discarding a chemically distinct topology.” | `mace_fmax_ev_per_angstrom=0.05` | 无 | `A. SOURCE_ALREADY_RESOLVES` | 仅几何预筛/预优化，不是能量排序或最终 DFT |
| 15 初始方向与 3–4 最终候选的筛选关系 | DOCX 只给出“多种方向 → 保留 3–4/催化剂”，无 15 | `L192` 同一句同时出现 15 与 3–4，并要求先声明 scope 再计算任务数量 | 两者并存，`orientation_scope=null` | 无 | `C. SOURCE_UNDERSPECIFIED` | 筛选关系因 scope 未定而无法唯一推得任务数 |
| 文献 / DOI 依据 | **NOT_FOUND**（DOCX 全文无 DOI、参考文献条目或外部方法引用） | **NOT_FOUND**（TASK_PLAN 无 DOI；`references/` 目录在 checkout 中不存在） | 无引用字段 | 历史报告亦未给出文献 | `NOT_FOUND` | 无外部文献可直接消除 scope 歧义 |
| `Cu13:M2` 定义与来源 | DOCX `table 5 row 6 col 2`: “孤立中性 Cu13（M=2, 4, 6）” | `L193`: “isolated Cu13 M=2/4/6” | `Cu13=[2,4,6]` | 无额外决策 | `A. SOURCE_ALREADY_RESOLVES` | 孤立中性 Cu13 团簇，M=2/4/6 三个候选 |
| `Cu20_support:M1` / `M3` | DOCX `table 5 row 6 col 2`: “中性基底（2×Cu²⁺, M=1, 3）” | `L193`: “Cu-20 support M=1/3” | `[1,3]` | 无 | `A. SOURCE_ALREADY_RESOLVES` | 70 原子 `[Cu2(C7H5O5)4]^0`，含 2×Cu²⁺ d⁹ |
| `SnCu20_support:M2` | DOCX `table 5 row 6 col 3`: “孤立中性基底（1×Cu²⁺ d⁹ + 闭壳层 Sn⁴⁺ d¹⁰, M=2）” | `L193`: “SnCu-20 support M=2” | `[2]` | 无 | `A. SOURCE_ALREADY_RESOLVES` | 71 原子含 Sn(IV) 配位基底，Cu²⁺ d⁹ + Sn⁴⁺ d¹⁰ |
| 六个候选是否全部执行 single-point | DOCX `table 5 row 6 col 2/3` 列出 5+1=6 个孤立碎片候选；`table 7 row 2 col 2` item 2：“校验孤立 Cu13 与中性双核基底自旋初态” | `L204`: “the explicitly listed isolated-fragment spin candidates … enumerate six candidate single-point checks … The implementation must preserve the stated spin candidates and report the reconciled count; it must not silently omit candidates to match an approximate total.”; `L928`: “Every configured spin candidate is accounted for” | `isolated_fragment_spin_candidate_count=6` | 历史报告保留两项阻断、未选择 | `A. SOURCE_ALREADY_RESOLVES` | **是，六个全部要求执行/记账**；TASK_PLAN 明令不得为凑总数删候选 |
| 汇总数字 4 的来源与版本 | DOCX `table 7 row 2 col 3`: “碎片自旋校验（4 单点）” — 汇总行 | `L204`: “one WP1 summary line reports four fragment single points”; `L206`: “Do not trust a hand-written aggregate count if the underlying task list disagrees.” | `summary_fragment_single_point_count=4` | 无其他决策记录 | `E. NOT_A_SCIENTIFIC_DECISION` | “4”是近似手写汇总，不是授权删减两个候选的依据；属统计/转录问题 |
| 备用/对照/不执行的候选 | DOCX `table 5 row 6 col 3`: “必要时 M=5” 仅针对**完整 SnCu-20 体系** | `L193`: “complete SnCu-20 M=1/3 (M=5 only when the configured diagnostic condition requires it)” | `conditional_complete_model_multiplicity=5` | 无 | `A. SOURCE_ALREADY_RESOLVES` | M=5 是条件性完整模型候选，**不在六个孤立碎片候选中**；六个中无“备用/不执行”标记 |
| 重复/漏统计/跨阶段 | DOCX `table 3 row 7 col 3`: 完整体系 Cu-20 M=2/4、SnCu-20 M=1/3 属后续阶段；`table 5 row 6 col 2/3` 为孤立碎片 | `L193` 将 isolated 与 complete 分开列出；`L438` 为完整多重度比较阶段 | 两者分字段存储 | 无 | `A. SOURCE_ALREADY_RESOLVES` | 未发现六个候选重复；完整模型候选属另一阶段，不应混入 6/4 记账 |
| single-point 的具体用途 | DOCX `table 7 row 2 col 2` item 2 + `table 5 row 6 col 2/3`：校验孤立碎片自旋初态，随后对比完整体系锁定基态 | `L434`: “Validate isolated fragment electron counts and spin candidates”; `L438`: 完整多重度比较 | WP1 任务定义 | 无 | `A. SOURCE_ALREADY_RESOLVES` | 用途是自旋初态/电子奇偶校验，不是结构优化或能量结论 |
| Manifest / Profile reconciliation 状态 | DOCX/TASK_PLAN 明确支持 3–4、M=2/4/6、M=1/3、M=2 等文本 | `L192/193/204` 明确 | `profile_reconciliation` 将这些 WP1 字段标为 `docx_status=absent`、`evidence_ids=[]`、`profile_only` | run_04 取证报告已记录该现象 | `D. PIPELINE_INTERPRETATION_ISSUE` / `E. NOT_A_SCIENTIFIC_DECISION` | 字段级 reconciliation 未把原文绑定到结构化值；**不是 DOCX 缺证据**，也不是需要用户决定的科学问题 |

---

## 2. 最终判定（逐题）

### 2.1 docking orientation scope 能否由已有资料唯一确定？
**不能。** DOCX 没有 15 个方向的数量与范围；TASK_PLAN L192 明确要求 Manifest 声明 scope 且“do not infer this from prose”。历史记录确认两个选项均未被选择。**分类 `C. SOURCE_UNDERSPECIFIED`**，属于真实缺失的科学定义，需要负责人或原始设计记录补足，不是程序误判。

### 2.2 六个 spin candidates 与四个 single points 的关系能否唯一确定？
**能。** TASK_PLAN L204 明确：六个候选枚举六次 candidate single-point checks，汇总“四”是近似值；实现必须保留全部六个并报告对账后的数量，不得静默删减。L206 进一步禁止信任与任务定义冲突的手写汇总。**分类 `A. SOURCE_ALREADY_RESOLVES`**（科学问题已解决）+ `E. NOT_A_SCIENTIFIC_DECISION`（4-vs-6 是统计/转录问题）。当前 blocker 仍要求 owner confirmation，属于保守策略门，不是科学歧义。

### 2.3 哪些只是 Profile 或 Pipeline 的错误？
- `summary_fragment_single_point_count=4` 被当作可执行任务数：与 TASK_PLAN L204/L206 冲突，属统计转录问题（`E`）。
- `profile_reconciliation` 把有 DOCX 原文支持的 WP1 字段标成 `docx_status=absent` / `profile_only`：属字段级来源绑定/规范化限制（`D`/`E`）。
- 两个 WP1 blocker 本身是**正确保留**的策略门，不是程序缺陷；其中 spin 项背后的科学问题已由 TASK_PLAN 解决，orientation 项仍缺定义。

### 2.4 哪些确实需要科学判断？
只有 orientation scope（15 per catalyst vs across both systems）。TASK_PLAN 明令不得推断；Frozen DOCX 无对应原文；无历史决策记录；无 DOI/参考文献。需交由负责人/文献研究确定，Local Agent 未提出选择项。

### 2.5 哪些未解决问题值得进一步文献研究？
1. v4.1 中 “15 support/cluster docking orientations” 的原始设计定义：是每个催化剂 15 个、还是两个体系共 15 个？需要项目设计记录或所引用方法的原始说明。
2. 若存在外部方法依据，需要其文献/DOI 以核对 orientation-set 基数与采样范围。当前 DOCX 与 TASK_PLAN 均为 `NOT_FOUND`，不得用网络单篇文章替代项目原始设计。

以上问题已整理为 `UNRESOLVED_SCIENTIFIC_QUESTIONS.json`，交 ChatGPT 做文献检索与证据比较；本 Agent 未选择任何值。

## 3. 证据文件

- `ORIENTATION_SCOPE_EVIDENCE.json`
- `SPIN_CANDIDATE_EVIDENCE.json`
- `SOURCE_VERSION_AND_AUTHORITY.json`
- `UNRESOLVED_SCIENTIFIC_QUESTIONS.json`
- 提取脚本/中间证据：`extracted/docx_blocks.json`、`extracted/key_quotes.txt`、`extracted/manifest_wp1.json`

本轮未修改任何源文件；未生成 ModelSpec/CalculationPlan；未执行任何计算或 HPC 操作。
