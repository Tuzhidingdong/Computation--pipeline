# Coordination DFT Publication Pipeline

An independent, reusable Skill and deterministic workflow engine for coordinating atomistic model review, CP2K DFT calculations on HPC systems, reproducible numerical analysis, publication-quality figures, transferable visualization data, and manuscript-ready computational reports.

## Project status

The governing development baseline is [`TASK_PLAN_v1.0.0.md`](TASK_PLAN_v1.0.0.md). Execution progress belongs in [`STATUS.md`](STATUS.md).

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

## Development

Implementation must follow the phases and acceptance criteria in `TASK_PLAN_v1.0.0.md`. Do not treat the presence of a script as proof that its scientific function is validated.
