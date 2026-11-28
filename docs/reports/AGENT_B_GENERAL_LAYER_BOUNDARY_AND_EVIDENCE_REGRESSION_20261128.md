# Agent B — PR #3 通用层边界与证据回归补强报告

更新日期：2026-11-28  
仓库：Tuzhidingdong/Computation--pipeline  
PR #3：https://github.com/Tuzhidingdong/Computation--pipeline/pull/3  
分支：agent-b/plan-compiler-v41-model-plugin-20261127  
本轮基线：530e56f3b77027ffb9203e26f6422f21df336e1a  
最终实现与回归测试 HEAD：5666a0c98a0f6bb4d660af29de12ea32966285a2  
PR Base SHA：5e6e26fdf94efbac54182f819f4879c1aafb1d4d

## 1. 最终状态

- PR #3 仍为 Draft / open / unmerged。
- Base SHA 未改变；未修改 main、PR #1、PR #2、PR #4。
- 未修改 project_profile.json 中任何科学值。
- 未调用 resolve-v41-planning；没有选择 WP1 orientation 或 fragment spin 决策；没有创建原子图、键连接或配位拓扑；没有运行 CP2K、HPC、Slurm 或生产 DFT。
- Frozen DOCX 二进制端到端验收仍未执行。本轮 run_04 回归仍属于基于已发布真实 evidence blocks 的回归，不把它宣称为原始 DOCX 二进制验收。

## 2. 文件变更与原因

| 文件 | 变更 | 原因 |
|---|---|---|
| pipeline_contracts/plan_compiler/manifest.py | 删除 CORR 专属 inline 提取与 unresolved-field 逻辑；保留 CHARGE 标量/解释分离；提供显式 adapter hooks；重做通用 conflict grouping；限制编号标题识别 | 通用层不再内置 CORR 体系、参数、化学式和 WP4 语义 |
| pipeline_contracts/plan_compiler/compiler.py | compile_docx() 可显式接收 claim enricher 与 unresolved-field extractor | 为项目适配器提供可复用的显式扩展点，不按 project_id 在通用层切换行为 |
| projects/corr_dft_v4_1/docx_adapter.py | 新增 CORR v4.1 DOCX adapter，承载 CP2K/EPS_SCF、Cu-20/SnCu-20/Cu13、CHE、HCCO 反应、WP2 gate、WP4 力调用及项目特定 needs-review 规则 | 把项目解析语义放回项目命名空间 |
| projects/corr_dft_v4_1/plan_compiler.py | compile_v41_docx() 显式传入 extract_corr_v41_claims 与 extract_corr_v41_unresolved_fields | 只有 CORR v4.1 项目入口调用专属适配逻辑 |
| tests/test_real_docx_run04_regressions.py | 新增通用层隔离、冲突、输出 artifact、章节边界、全 104 条 CSV 对照和 evidence ID 完整性断言；补入 run_04 原始 block 62 | 防止通用层回归，并让 run_04 证据结果受到全量自动测试保护 |
| .github/workflows/contract-tests.yml | 保留 unittest，新增 pytest 安装和全量 pytest step，最后执行 compileall | CI 真正执行用户要求的 pytest 全量验证 |

## 3. 通用 Manifest 与 CORR v4.1 adapter 职责

### 通用层

pipeline_contracts/plan_compiler/manifest.py 负责可复用的：
- DOCX block 与 source evidence 关联；
- claim 规范字段解析、table-row evidence 关联；
- 标准 heading style 与有明确编号的普通段落识别；
- 通用 system/WP scope 的结构传递；
- field-level conflict 判定；
- provenance/evidence 聚合。

通用层不再包含 Cu-20、SnCu-20、Cu13、HCCO/H2CCO/HCCOH、CHE 公式、CP2K 专属 EPS_SCF prose 解析、CORR v4.1 的“单点力调用/吸附态”任务语义，也不识别 CORR 专属 WP2 gate 文字。

pipeline_contracts/plan_compiler/compiler.py 只暴露可选 adapter callback。它不根据 project_id 或化学体系名称自行启用特定解析行为。

### CORR v4.1 项目层

projects/corr_dft_v4_1/docx_adapter.py 负责上述项目专属字段和不充分证据状态。

projects/corr_dft_v4_1/plan_compiler.py::compile_v41_docx() 显式传入 adapter callbacks。普通 compile_docx(..., project_id="unrelated-project") 不会因此抽取 CORR 专属字段。 新增对照测试也使用 project_id="corr_dft_v4_1" 但不传 adapter；该输出与 unrelated-project 的通用 Manifest（规范化 project_id 后）必须完全相同，防止 project_id 本身隐式触发项目解析。

### CHARGE 修复

_charge_value_and_explanation() 保留在通用层，因为“数值与后续解释分离”是通用 claim 解析能力，不依赖 CORR 项目。

CHARGE 原始 source_text、原 evidence ID、source location 和解释文字继续保留；只有数值标量参与冲突比较。真实 CHARGE=0 与 CHARGE=1 仍是 blocking conflict。

## 4. 冲突识别边界

通用冲突组不再把 label 作为分组键，也不再跳过整个 outputs 类别。默认规则是：同一规范字段、同一 system/WP scope、不同规范化值即产生 blocking conflict，不因 label 文案不同而豁免。对长文本同样如此。

唯一允许的非互斥例外必须显式标记为同一 coexistence_group，并且恰好是一条 summary 与一条 detail。CORR adapter 只对 run_04 已被原文审定的 ASE Vibrations 表格摘要/段落详细说明这一对 claim 设置标记；通用层不根据 label 自动推断二者可以共存。相同 label 的重复 detail、同一参数的不同标量、未标记的不同长文本均继续冲突。

Output claims 不再被整体排除。输出产物有 artifact identity 时，按 artifact identity 分组：
- 不同产物：独立，不互相误报；
- 同一产物：不同内容仍触发 blocking conflict。

run_04 的 Computational Details 和 Neutral & Scope-Bounded Results Report Template 是两个不同 artifact。新增测试同时验证不同 artifact 不冲突，以及同一 artifact 的互斥正文产生冲突。

## 5. 章节识别边界

- 保留 run_04 的 18 个明确编号章节识别结果。
- Normal style 且无 Word list_info 的明确编号标题可以识别。
- Heading1–Heading9 样式标题仍被识别。
- ListBullet、ListNumber 和带 Word list_info 的普通列表项不会仅因以 1.1 开头而被提升为标题。
- 普通正文中提到 1.1 不会被识别为章节。
- 定向测试包含普通 Normal 1.1 标题、带 Word list_info 的 1.1 列表、ListBullet 1.1、普通正文，以及完整 Heading1–9 样式集合。

## 6. Profile CSV 104 条全量回归

定向测试从仓库读取：
docs/reports/real_docx_run04_20261127/PR3_PROFILE_RECONCILIATION_AFTER_FIX.csv

自动校验：
- 程序 reconciliation 共 104 条，字段唯一数 104；
- CSV 共 104 行，profile_field 唯一数 104；
- 状态严格等于 consistent=39、needs_review=44、profile_only=21；
- 每一行逐项比较 field、status、docx_status、docx_evidence_ids；
- 每个 consistent 项必须是 docx_evidence 且至少有一个 evidence ID；
- 每个 needs_review 项必须有 unresolved source text 和 evidence IDs；
- 每个 profile_only 项必须是 absent、没有 DOCX evidence IDs、没有 DOCX values、没有 unresolved source text；
- 所有 reconciliation evidence IDs 必须存在于 Manifest evidence 集合；
- 对 Manifest 其余结构（claims、tasks、systems、models、method、unresolved_structured_fields、diagnostics、provenance 等）递归检查 evidence_id/evidence_ids，全部必须能在 evidence 集合中解析；
- WP1 orientation、fragment spin、WP3、WP5 和 topology 字段保持 needs_review，不会为了减少待审字段数而升级；
- Profile 的 15 个 orientation 数值未被写入 DOCX claims。

run_04 原文证据 block 62（paragraph 18）补入回归夹具，确保 topology 的 source IDs 与原始 CSV 完全对应；spin 相关 needs-review 分别保留表格行完整证据或只引用数值单元格，按字段原始 CSV 逐项一致。

## 7. 测试与 CI

代码与回归测试 GitHub Actions run #549：
https://github.com/Tuzhidingdong/Computation--pipeline/actions/runs/46092520597

最终结果：
- python -m unittest discover -s tests -v：133 tests，131 passed，2 skipped，0 failures。
- python -m pytest -q：131 passed，2 skipped，108 subtests passed。
- python -m compileall -q pipeline_contracts tests examples：通过。
- 新增的 run_04 定向测试全部通过，包括 adapter opt-in、真实 table-cell ADDED_MOS、18 章节与 Heading1–9/ListBullet 边界、三项原始误报分类、不同 label 同字段冲突、同 artifact 冲突，以及 104 CSV 全行一致性和证据引用完整性。

两个 skipped 均为需要 owner-approved upstream checkout/source tree 的可选集成测试；没有因此把它们计为通过。

## 8. 最终交付边界

- 最终代码 HEAD：c36b66def19038f0f15578a1222d5ec3e096cafe
- PR #3：Draft / open / unmerged。
- project_profile.json 未修改。
- Frozen DOCX 二进制端到端 read_frozen_docx() 验收未执行。本轮验证属于 run_04 原始 evidence-block regression + 全量自动化回归，不代表完整 Frozen DOCX 二进制验收。
