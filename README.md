- **Detailed Agent execution prompt:** [Upstream remediation task instructions](docs/AGENT_EXECUTION_PROMPT_UPSTREAM_REMEDIATION_v1.0.0.md)

# Coordination DFT Publication Pipeline

An independent, reusable Skill and deterministic workflow engine for coordinating atomistic model review, CP2K DFT calculations on HPC systems, reproducible numerical analysis, publication-quality figures, transferable visualization data, and manuscript-ready computational reports.

## Project status

The governing development baseline is [`TASK_PLAN_v1.0.0.md`](TASK_PLAN_v1.0.0.md). Execution progress belongs in [`STATUS.md`](STATUS.md).

Architecture ownership is defined in [`docs/ARCHITECTURE_OWNERSHIP.md`](docs/ARCHITECTURE_OWNERSHIP.md). The current source-level findings are in [`docs/EXISTING_SKILL_CAPABILITY_AUDIT.md`](docs/EXISTING_SKILL_CAPABILITY_AUDIT.md). Before building the workflow engine, the Agent must follow [`docs/UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md`](docs/UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md) and track progress in [`docs/UPSTREAM_REMEDIATION_STATUS.md`](docs/UPSTREAM_REMEDIATION_STATUS.md). External tool choices are recorded in [`docs/EXTERNAL_TOOL_SELECTION.md`](docs/EXTERNAL_TOOL_SELECTION.md).

The first validation workflow is a user-frozen CO-reduction ketene-selectivity protocol (v4.1). Its chemistry and numerical settings must remain in a separate validation-project configuration; they are not generic defaults of this Skill.

## Design principles

- Reuse the user's existing `chem-scitoolkit`, `BeiLong_HPC`, `UCAS_hpc`, and `Data_analysis` Skills through audited interfaces.
- Present one complete model-review package before production calculations.
- Freeze approved models by SHA256.
- Use deterministic scripts for calculations, numerical analysis, QC, and plotting.
- Orchestrate HPC jobs through existing backends with bounded submission, provenance, and recovery.
- Do not silently change scientific methods or thresholds.
- Deliver publication figures together with transferable data and regeneration scripts.
- Generate manuscript text only from validated execution records and results.

## Planned user-facing deliverables

1. Article-ready Computational Details.
2. Publication-ready figures and their transferable data/scripts.
3. Article-ready Results and Discussion.
4. Supplementary numerical tables, QC reports, and provenance package.

## Agent handoff

Start with [`AGENT_START_HERE.md`](AGENT_START_HERE.md). The current prerequisite is to remediate the scoped gaps in the existing Skills and produce reviewable upstream PRs before beginning the workflow engine.

## Parallel adapter preparation

The Pipeline-side contract and Mock adapters are documented in [`docs/SKILLS_ADAPTER_CONTRACT_V0.1.md`](docs/SKILLS_ADAPTER_CONTRACT_V0.1.md). Optional real adapter classes now bind the exact Agent A Data_analysis and chem-scitoolkit branch APIs inspected on 2026-11-27. The real modules are imported lazily; no private branch is installed or added as a mandatory dependency. Data_analysis remains the Artifact/Analysis Run/Evidence owner, and the current no-derived-Artifact limitation is represented as a partial Analysis Run and Pipeline warning rather than a fabricated output reference.

- `RealDataAnalysisAdapter`: DFT reader discovery/read, operation discovery/dispatch, project-backed Analysis Run creation, normalized-result packaging and DFT Evidence Package.
- `RealCSTAdapter`: finite CP2K builder, task-aware output validation, charge/PDOS/Cube/vacuum/ASE helpers and figure-profile functions.
- `MockCSTAdapter`, `MockDataAnalysisAdapter` and `MockHpcAdapter` remain available and unchanged for contract tests.

Real Data_analysis use requires a registered DA Artifact, a matching SHA-256, a local Artifact URI or an injected owner-provided resolver, and the DA project root. No Pipeline Artifact Store or direct DA registry parsing is introduced. Optional live source tests require explicitly supplied `DATA_ANALYSIS_SOURCE_ROOT` and/or `CHEM_SCI_TOOLKIT_SOURCE_ROOT`; public CI does not check out private source branches.

Run the standard-library test suite with:

```bash
python -m unittest discover -s tests -v
python -m compileall -q pipeline_contracts tests
```

## Development

Implementation must follow the phases and acceptance criteria in `TASK_PLAN_v1.0.0.md`. Do not treat the presence of a script as proof that its scientific function is validated.
