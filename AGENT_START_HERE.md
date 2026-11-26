# Agent Start Here — Upstream Skill Remediation

**Current assignment:** Complete the upstream Skill remediation prerequisite. **Do not start building the Computation--pipeline workflow engine.**

This repository is the orchestrator project. It is not a replacement for the existing specialist Skills. Your immediate job is to make the existing reusable capabilities reliable and testable, then prove that the future pipeline can call them through narrow adapters.

## Mandatory task brief — read and execute, not merely follow a link

Before editing any code, read the complete [Agent Execution Prompt — Upstream Skill Remediation v1.0.0](docs/AGENT_EXECUTION_PROMPT_UPSTREAM_REMEDIATION_v1.0.0.md). It is the detailed, self-contained execution instruction and defines the work sequence, per-requirement behavior, tests, stop conditions, PR policy and final report format.

Do not treat this page or the links below as sufficient instructions on their own. The detailed prompt is mandatory.

## Exact work assignment

1. **chem-scitoolkit (public):** Implement CST-1 through CST-7 with backward-compatible APIs and synthetic tests:
   - CST-1: finite/non-periodic CP2K input builder, configurable cell/Poisson/MT, per-KIND basis and pseudopotentials, charge/spin/XC/dispersion/SCF/run/print controls.
   - CST-2: task-aware CP2K output validation; distinguish normal termination, truncation, SCF, GEO_OPT and ENERGY_FORCE success.
   - CST-3: separate true density-basin Bader analysis from approximate calibrated Hirshfeld estimates; preserve atom mapping and charge accounting.
   - CST-4: normalized CP2K PDOS parser route, preserving spin, atom, KIND, orbital, units and broadening metadata.
   - CST-5: cube-grid/atom-map compatibility, density-difference checks and defensible vacuum-potential plateau validation.
   - CST-6: thin ASE vibration/thermochemistry wrapper; reuse ASE algorithms.
   - CST-7: configurable publication figure profiles; preserve existing defaults.

2. **Data_analysis (private):** Implement DA-1 through DA-3:
   - DA-1: content-aware DFT artifact formats for CP2K outputs, PDOS, cube grids, ASE structures/trajectories and force/displacement records.
   - DA-2: register the selected reader/parser route and deterministic DFT normalization/validation operations. Do not implement a second CP2K parser.
   - DA-3: link inputs/outputs, SHA256, structure/model identity, CP2K/parser/operation versions, upstream job reference, parameters, warnings and QC evidence.
   - Note: the audit calls provenance DA-4 in one place; the governing remediation task and tracker call it DA-3. Use **DA-3** and include every provenance criterion from the audit.

3. **BeiLong_HPC and UCAS_hpc (both private):** Perform read-only/reuse-first audits and document how their existing tools map to the normalized pipeline adapter methods. Do not redesign, merge, expose or modify cluster-specific settings. No SSH, SCP, Slurm submission or real cluster preflight.

4. **External tools:** Verify versions, licenses, platform support, selected APIs and runtime availability. Update the existing docs/EXTERNAL_TOOL_SELECTION.md. Prefer established libraries; do not introduce AiiDA, atomate2, jobflow or another workflow server.

5. **Cross-repository integration:** Add only sanitized adapter documentation and synthetic/mock contract tests. Do not build the DAG, task engine, production project plugin, model builder or report engine in this prerequisite.

6. **Evidence and PRs:** Update the remediation tracker and STATUS.md. Use dedicated branches and separate review-ready PRs for changed repositories. Keep all PRs open and unmerged.

## Required order of work

1. Inspect working-tree state and preserve existing local changes.
2. Refresh all four upstream repositories; record current default branches and HEAD SHAs. Re-audit any source that changed since the historical audit.
3. Read the architecture, source audit, detailed remediation task and external-tool policy.
4. Implement chem-scitoolkit CST tasks and tests.
5. Implement Data_analysis DA tasks and tests.
6. Audit the two HPC Skills and write sanitized adapter mappings.
7. Verify external tools and run synthetic/mock cross-repository tests.
8. Review final diffs for API breaks, unrelated changes, secrets, private HPC settings and project-specific science data.
9. Open separate PRs, update the tracker/status, and submit the final evidence report.

## Hard boundaries

- One visible coordinating Agent; no invisible subagents or hidden workers.
- No production DFT, remote HPC, Slurm, SSH or SCP tasks.
- No changes to the frozen v4.1 chemistry or computation protocol.
- No v4.1 structures, results, chemical rules or project thresholds in generic Skills.
- No private hostnames, credentials, usernames, paths or cluster configuration in the public repository.
- Preserve public APIs; changes must be additive or use an explicit deprecation path.
- No duplicate CP2K parser, Bader engine, vibration engine, plotting engine, artifact database, HPC ledger or workflow server.
- Never work on upstream default branches; do not reset, clean, force-push or overwrite owner work.
- Do not merge PRs, enable auto-merge, publish packages or start Phase 1 of the pipeline engine.

## Completion condition

The prerequisite is ready for owner review only when CST-1…CST-7 and DA-1…DA-3 have code/test evidence or are explicitly blocked with concrete evidence; both HPC adapter mappings and mock contracts are documented; external tool versions/licenses are recorded; all changed-repository PRs are open and unmerged; and STATUS.md truthfully states that the pipeline engine has not started.

No production DFT/HPC job may be submitted. Passing software tests does not constitute scientific validation of the v4.1 project.

## Governing documents — read in this order

1. [TASK_PLAN_v1.0.0.md](TASK_PLAN_v1.0.0.md)
2. [ARCHITECTURE_OWNERSHIP.md](docs/ARCHITECTURE_OWNERSHIP.md)
3. [EXISTING_SKILL_CAPABILITY_AUDIT.md](docs/EXISTING_SKILL_CAPABILITY_AUDIT.md)
4. [UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md](docs/UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)
5. [EXTERNAL_TOOL_SELECTION.md](docs/EXTERNAL_TOOL_SELECTION.md)
6. [UPSTREAM_REMEDIATION_STATUS.md](docs/UPSTREAM_REMEDIATION_STATUS.md)
7. [STATUS.md](STATUS.md)

**Start by executing the detailed Agent Execution Prompt. Do not skip the baseline refresh or begin the pipeline engine.**
