# Agent Start Here — Upstream Skill Remediation

The next authorized task is **upstream Skill gap remediation**, not implementation of the Computation--pipeline engine.

Read these documents in order:

1. [TASK_PLAN_v1.0.0.md](TASK_PLAN_v1.0.0.md)
2. [ARCHITECTURE_OWNERSHIP.md](docs/ARCHITECTURE_OWNERSHIP.md)
3. [EXISTING_SKILL_CAPABILITY_AUDIT.md](docs/EXISTING_SKILL_CAPABILITY_AUDIT.md)
4. [UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md](docs/UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)
5. [EXTERNAL_TOOL_SELECTION.md](docs/EXTERNAL_TOOL_SELECTION.md)
6. [UPSTREAM_REMEDIATION_STATUS.md](docs/UPSTREAM_REMEDIATION_STATUS.md)

Execute the remediation task in its specified order. First refresh the upstream repositories and confirm the audit against current source. Then make only the authorized, backward-compatible improvements to chem-scitoolkit and Data_analysis. Audit BeiLong_HPC and UCAS_hpc for adapter compatibility; do not rewrite their existing cluster operations unless a concrete blocker is demonstrated.

Use dedicated branches and separate PRs. Do not merge. Do not submit production DFT or HPC jobs. Do not change the frozen v4.1 science protocol. Keep project-specific chemistry out of generic Skills and private cluster settings out of this public repository.

Update `docs/UPSTREAM_REMEDIATION_STATUS.md` and `STATUS.md` with verifiable evidence. Report repository, branch, commit SHA, PR URL, changed files, exact tests/results, unresolved validation, and confirmation that no production DFT/HPC work was submitted.

**Do not begin Phase 1 of the new Computation--pipeline engine until this prerequisite is complete and the owner has reviewed the required upstream PRs.**
