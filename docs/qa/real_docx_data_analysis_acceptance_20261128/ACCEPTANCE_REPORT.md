# 真实 Frozen DOCX + Data_analysis 集成验收报告

## A. 最终结论

**`BLOCKED_BEFORE_MODEL_APPROVAL`**

真实 Frozen DOCX 已被 Pipeline 实际读取并编译，Manifest/Evidence 已生成；但两个 WP1 科学决策阻断原样保留，Evidence Review 未获用户确认，且本机不存在权威 Data_analysis 项目配置与已登记结构 Artifact ID/SHA。链路停在 `PLAN_COMPILE=BLOCKED` / `EVIDENCE_REVIEW=PENDING`，未到达 `MODEL_APPROVAL=AWAITING_APPROVAL`。未伪造该状态。

## B. 真实输入确认

| 输入 | 身份 | 核验 |
|---|---|---|
| Frozen DOCX | `CORR_DFT_Computational_Plan_v4.1_Frozen.docx`，330696 bytes | SHA-256 `eaa40442835c533833d5328745b07517237ed1df08b7f78fb2fd137b7cff3ef6`；原始二进制 DOCX（非提取文本/fixture）；QA 副本 SHA 一致 |
| Project Profile | 仓库内 `projects/corr_dft_v4_1/project_profile.json`，project_id `corr_dft_v4_1` | SHA-256 `c4f069ba50d1629d16da8322f976347fd46c154bc3fca541471994b509e6cd96`；Compiler=`corr_dft_v4_1`；**无 `structure_artifact` 字段、无 backend、无 `scientific_planning` 配置** |
| Data_analysis | 公开 API 可从已验收源码 SHA `489ac0da2999e002add50d8181d8cb92274c7d05` 导入 | `load_data_analysis_api()` OK，10 个接口全部 callable；**无实际项目根目录、无已登记 Artifact ID/SHA** → `NEEDS_OWNER_SELECTION` |

代码基线：分支 `agent-b/scientific-planning-architecture-20261128`，checkout HEAD `54a8a942773fbbb31421181ae23b04e11e6a3f2f`，detached，工作区 clean；Python 3.12.4。

## C. 阶段结果

| 阶段 | 结果 | 真实证据 | 阻塞原因 |
|---|---|---|---|
| DOCX 编译 | `BLOCKED` | `project start` exit=2；`DOCX_INGEST=COMPLETED`；源 SHA 与 QA 副本一致；Manifest SHA `89cc15f4e1dcebc5bb336073b509d0fb0cd1eecb91368b2089d956c472d896fa` | 两个 WP1 阻断未解决 |
| Manifest/Evidence | `BLOCKED`（产物已生成） | Manifest 保留 claims/evidence/locator；45 段正文、10 表格；诊断 `WP1_ORIENTATION_SCOPE_UNRESOLVED`、`WP1_FRAGMENT_SPIN_COUNT_MISMATCH` 原样保留 | 未调用 `resolve-v41-planning`，未确认证据 |
| Data_analysis API | `BLOCKED`（API 可用） | 真实 `load_data_analysis_api()` OK；10 接口 callable；模块路径来自 `489ac0` 源码 | 无用户配置的项目根/Artifact |
| Artifact ID/SHA | `NEEDS_OWNER_SELECTION` | Profile 无 `structure_artifact`；全盘无 `runtime.local.json`、无注册表 Artifact | 无法唯一确定权威 Artifact |
| ASE 结构读取 | `NOT_RUN` | 无真实 Artifact 路径可解析 | 上游阻塞 |
| 七类 Planning 对象 | `BLOCKED` | `project plan` exit=2，`planning_status=BLOCKED`，Bundle SHA `8de065ebdb6f9fd523f83c0fc1d55cb3b82862a4d51696aed82b4bda0aa04aa4`；七个对象文件均存在且 status=`BLOCKED` | 181 个 missing items（130 `UNCONFIRMED_MANIFEST_DEFINITION`、2 `EVIDENCE_REVIEW_INCOMPLETE`、WP1 两项等） |
| 模型候选 | `NOT_RUN` | 无 `model_candidates/`、无 approval 目录；`MODEL_GENERATE=PENDING` | Evidence Review 未完成，结构 Artifact 缺失 |
| 模型审批门 | `NOT_RUN` | `MODEL_APPROVAL=PENDING`，未达 `AWAITING_APPROVAL` | 未调用批准接口，未伪造状态 |

未生成模型预览图/结构核验图（无候选），对应交付项标记 `NOT_RUN`，原因如上。

## D. 最终状态核查

- `MODEL_APPROVAL`：`PENDING`（**未到达** `AWAITING_APPROVAL`）
- CalculationPlan 是否创建：**否**（`project_plan_stdout.calculation_plan_created=false`）
- Workflow Run 是否创建：**否**（QA DB `workflow_runs` 计数 0）
- 是否调用任何真实计算程序：**否**；未启动 CP2K
- 是否访问 HPC：**否**；未 SSH/SCP、未提交 Slurm
- 是否对 Data_analysis 进行写操作：**否**（未传 API 给 plan，未注册任何 Artifact）
- 是否调用 `approve_model()` / `project approve`：**否**
- 是否调用 `resolve-v41-planning`：**否**
- 是否确认证据（evidence review）：**否**

## E. 发现的问题

### 问题 1：WP1 科学决策阻断（数据层，非代码缺陷）
- 事实：Manifest/Profile 中 `WP1_ORIENTATION_SCOPE_UNRESOLVED`（15 个 orientations 范围未定）与 `WP1_FRAGMENT_SPIN_COUNT_MISMATCH`（详细 6 候选 vs 汇总 4）均 `blocks_execution=true`。
- 复现：`python -m pipeline_contracts.cli project start <真实 DOCX> --project-id corr_dft_v4_1 --compiler corr_dft_v4_1 --plan-version v4.1 --state-db <QA db> --output-root <QA root>`。
- 输入身份：DOCX SHA `eaa4044…315aec8`，Profile SHA `c4f069ba…9e6cd96`。
- 来源：`projects/corr_dft_v4_1/project_profile.json` 的 `known_blockers`。
- 证据：`DOCX_COMPILATION_DIAGNOSTICS.json`、`project_start_stdout.txt`。
- 影响：全局路线图停在 Stage 1 门控；需负责人决定，Agent 不得代选。

### 问题 2：缺少权威 Data_analysis 项目配置与结构 Artifact（输入层阻塞）
- 事实：Profile 无 `structure_artifact`、无 backend、无 Data_analysis 项目根；本机无 `runtime.local.json`、无 Artifact 注册记录。
- 复现：检查 Profile 字段 + 全盘搜索 `runtime.local.json` / registry + 调用 `load_data_analysis_api()` 后可导入但无 Artifact 可解析。
- API：`data_analysis.artifact_store.resolve_artifact_path()`（存在但未获真实 ID 调用）；`planning_orchestrator._resolve_structure()` 要求 `structure_artifact.artifact_id` + 64 位 SHA（源码 `planning_orchestrator.py:56-107`）。
- 证据：`DATA_ANALYSIS_ARTIFACT_DIAGNOSTICS.json`、`SOURCE_IDENTITY.json`。
- 影响：无法进入真实 Artifact 身份验证、ASE 结构读取与模型候选阶段；结果 `NEEDS_OWNER_SELECTION`。

### 问题 3：Planning 因未确认证据产生 181 个 missing items（流程状态，非计算失败）
- 事实：`project plan` 在未做 Evidence Review 时产生 181 项缺失，其中 130 项 `UNCONFIRMED_MANIFEST_DEFINITION`、2 项 `EVIDENCE_REVIEW_INCOMPLETE`；七类对象全部 `BLOCKED`。
- 复现：`python -m pipeline_contracts.cli project plan <run_id> --state-db <QA db> --output-root <QA root> --project-profile <profile>`（未传 integration factory）。
- 源码位置：`planning_orchestrator.py:477-484`（`EVIDENCE_REVIEW_INCOMPLETE`）。
- 证据：`PLANNING_ACCEPTANCE_DIAGNOSTICS.json`、`project_plan_stdout.txt`。
- 影响：不得通过手工确认或伪造证据绕过；需用户授权证据确认。

### 问题 4：`project report` 在阻断态抛异常（程序问题，轻微）
- 事实：`project report` exit=1，stderr `RuntimeError: RESULT_DELIVERY is blocked until WORKFLOW_EXECUTION completes`；报告文件仍写出。
- 源码位置：`project_pipeline.py:881`、`project_lifecycle.py:117`。
- 证据：`project_report_stderr.txt`、`final_project_report.json`。
- 影响：不影响核心验收结论；交 Developer 处理。

## F. GitHub 交付

见下方最终汇报 F 节（分支、commit、链接）。本轮不创建代码修复提交、不修改任何 PR、不运行计算。
