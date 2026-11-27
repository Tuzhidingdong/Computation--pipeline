# Agent Start Here — Calculation-plan Workflow Engine

**Current assignment:** Build the computation-plan-driven workflow engine in this repository. The earlier prerequisite-only instruction is superseded. Do not wait for another upstream remediation phase before implementing the Pipeline-owned DAG, persistence, interpreter, CLI and Mock execution.

The governing scope remains TASK_PLAN_v1.0.0.md. Preserve its scientific scope and frozen project protocols. This file changes execution priority only; it does not amend the governing plan.

## Current phase

Implement the first CP2K workflow MVP:
1. User-supplied versioned CalculationPlan (JSON; YAML when PyYAML is available).
2. Deterministic validation and task-graph compilation.
3. Persistent Workflow Run and task/attempt/event records in SQLite.
4. GEO_OPT execution through an injected execution adapter.
5. Structured CST convergence gate.
6. Dynamic ENERGY task creation only after GEO_OPT passes.
7. Existing Data_analysis adapter for output registration, Analysis Run and Evidence.
8. CLI: plan, validate, run, status, resume, report.
9. Mock end-to-end and recovery tests.

Post-processing is a node in the workflow, not the workflow engine itself.

## Required boundaries

- One visible coordinating Agent; no hidden LLM workers.
- Continue on agent-b/pipeline-mock-contracts-20261127 and existing PR #1.
- Do not modify main, open another PR, merge, or enable auto-merge.
- Only modify Computation--pipeline. Treat chem-scitoolkit, Data_analysis, BeiLong_HPC and UCAS_hpc as read-only.
- Do not submit real DFT/AIMD/Slurm/HPC jobs during this phase.
- Reuse existing adapters, Artifact, Provenance and Evidence interfaces. Do not create a second Artifact Store, CP2K parser, Slurm system or HPC ledger.
- Do not guess missing scientific parameters or alter authorized scientific settings.
- Do not generate arbitrary Python from a CalculationPlan.
- Report unavailable when a required upstream callable interface does not exist; do not invent an API.

## Implementation sequence

1. Extend CalculationPlan and deterministic operation registry only as required by the CP2K MVP.
2. Compile a stable DAG and add dynamic expansion based on structured QC.
3. Persist run/task/attempt/job references in SQLite; implement resume without duplicate submission.
4. Bind existing CST, HPC and Data_analysis interfaces. If an upstream Skill lacks a callable interface, record the exact gap and keep that backend unavailable.
5. Add CLI and concise reports.
6. Run unit/Mock E2E tests and update STATUS.md with implementation versus real-science validation clearly separated.

Do not treat a successful Mock run, Slurm COMPLETED, or parser success as scientific validation.
