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

The Pipeline-side contract and Mock adapters are documented in [`docs/SKILLS_ADAPTER_CONTRACT_V0.1.md`](docs/SKILLS_ADAPTER_CONTRACT_V0.1.md). Optional real adapters bind the Agent A Data_analysis and chem-scitoolkit APIs without copying upstream code. Data_analysis remains the Artifact/Analysis Run/Evidence owner; the DFT reader adapter resolves source Artifact IDs through the official Data_analysis resolver, persists JSON-compatible reader results under `data/derived/`, registers them with `register_derived_artifact()`, then creates an Analysis Run that references the registered output before normalization and Evidence packaging.

- `RealDataAnalysisAdapter`: DFT reader discovery/read, operation discovery/dispatch, project-backed Analysis Run creation, normalized-result packaging and DFT Evidence Package.
- `RealCSTAdapter`: finite CP2K builder, task-aware output validation, charge/PDOS/Cube/vacuum/ASE helpers and figure-profile functions.
- `MockCSTAdapter`, `MockDataAnalysisAdapter` and `MockHpcAdapter` remain available and unchanged for contract tests.

Real Data_analysis use requires a registered source Artifact, its SHA-256 and the DA project root. `resolve_artifact_path()` and `register_derived_artifact()` own input resolution, custody checks and derived registration; Pipeline never reads DA registry files. Explicit local URI support is a compatibility fallback only when no official/injected resolver exists and remains subject to input-hash and DA provenance verification. Non-JSON-serializable results or registration failures remain visible as warnings with no invented output Artifact. Scientific QC stays `not_assessed`. Optional live source tests require explicitly supplied `DATA_ANALYSIS_SOURCE_ROOT` and/or `CHEM_SCI_TOOLKIT_SOURCE_ROOT`; public CI does not check out private source branches.

Run the standard-library test suite with:

```bash
python -m unittest discover -s tests -v
python -m compileall -q pipeline_contracts tests
```

## Development

Implementation must follow the phases and acceptance criteria in `TASK_PLAN_v1.0.0.md`. Do not treat the presence of a script as proof that its scientific function is validated.

## Minimal Pipeline MVP — existing CP2K output post-processing

The first synchronous coordinator is available as a Python API. It runs one linear task:

\`\`\`text
input Artifact IDs
    → optional CST validation
    → Data_analysis Reader
    → derived JSON Artifact
    → Analysis Run / Provenance
    → Evidence Package
    → PipelineTaskResult
\`\`\`

It does not submit CP2K, AIMD, Slurm or HPC jobs. The runner requires explicit adapter injection; it never silently falls back to Mock adapters.

### Real Data_analysis example

See [examples/postprocess_existing_cp2k_output.py](examples/postprocess_existing_cp2k_output.py). The example reads an already registered CP2K output Artifact by ID, optionally calls RealCSTAdapter output validation, and returns the Analysis Run ID, derived Artifact ID and Evidence Package ID.

The environment must already expose the owner-approved Data_analysis source/API and any selected Reader/CST dependencies; Pipeline does not install the private upstream branch automatically. For PowerShell:

\`\`\`powershell
$env:DATA_ANALYSIS_PROJECT_ROOT = "E:\Data_analysis_Project"
$env:CP2K_OUTPUT_ARTIFACT_ID = "ART-..."
$env:CP2K_RUN_TYPE = "ENERGY"
python examples/postprocess_existing_cp2k_output.py
\`\`\`

The example uses only the Artifact ID; resolve_artifact_path(project_root, artifact_id) resolves the registered input. Input SHA-256 and format metadata are optional manifest fields. The real Data_analysis resolver and Analysis Run creator verify the registered Artifact and SHA-256.

### Python API

\`\`\`python
from pathlib import Path
from pipeline_contracts import (
    PipelineRunner, PipelineTaskManifest,
    RealCSTAdapter, RealDataAnalysisAdapter,
)

project_root = Path(r"E:\Data_analysis_Project")
artifact_id = "ART-CP2K-OUTPUT"

runner = PipelineRunner(
    data_analysis_adapter=RealDataAnalysisAdapter(project_root),
    cst_adapter=RealCSTAdapter(),
)
task = PipelineTaskManifest(
    task_id="CP2K-POSTPROCESS-001",
    project_root=project_root,
    input_artifact_ids=(artifact_id,),
    operation="dft.artifact.read",
    parameters={"reader_id": "cp2k-output-tools"},
    input_artifact_formats={artifact_id: "cp2k_output"},
    cst_validation={
        "operation": "cp2k.validate_output",
        "parameters": {"run_type": "ENERGY"},
        "required": False,
    },
)
result = runner.run(task)
print(result.status, result.analysis_run_id)
print([item.artifact_id for item in result.output_artifacts])
print((result.evidence_package or {}).get("evidence_package_id"))
\`\`\`

When optional CST dependencies are unavailable, the runner records a warning and continues to Data_analysis. A required CST stage that is unavailable stops the workflow. A failed Reader or failed derived registration never returns a successful task result.

### Mock end-to-end example

Inject MockCSTAdapter() and MockDataAnalysisAdapter() to exercise the same orchestration and reference chain without reading project data or generating scientific values. Mock Analysis Run / Evidence objects are marked execution_mode="mock" and qc_status="not_evaluated".

