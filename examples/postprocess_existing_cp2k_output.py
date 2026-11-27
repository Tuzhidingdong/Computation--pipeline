"""Post-process one registered CP2K output with the real Data_analysis APIs.

Set DATA_ANALYSIS_PROJECT_ROOT and CP2K_OUTPUT_ARTIFACT_ID before running.
The Data_analysis source providing artifact_store + DFT APIs, and optional
chem-scitoolkit runtime dependencies, must already be available in PYTHONPATH.
This example does not submit or execute a CP2K/HPC calculation.
"""
from __future__ import annotations

import os
from pathlib import Path

from pipeline_contracts import (
    PipelineRunner,
    PipelineTaskManifest,
    RealCSTAdapter,
    RealDataAnalysisAdapter,
    TaskStatus,
)


def main() -> int:
    project_root = Path(os.environ["DATA_ANALYSIS_PROJECT_ROOT"]).expanduser().resolve()
    artifact_id = os.environ["CP2K_OUTPUT_ARTIFACT_ID"]
    run_type = os.environ.get("CP2K_RUN_TYPE", "ENERGY")

    data_analysis = RealDataAnalysisAdapter(project_root)
    cst = RealCSTAdapter()
    runner = PipelineRunner(
        data_analysis_adapter=data_analysis,
        cst_adapter=cst,
    )

    task = PipelineTaskManifest(
        task_id="CP2K-POSTPROCESS-001",
        project_root=project_root,
        input_artifact_ids=(artifact_id,),
        operation="dft.artifact.read",
        parameters={
            "reader_id": "cp2k-output-tools",
            "timeout_seconds": 120,
        },
        input_artifact_formats={
            artifact_id: "cp2k_output",
        },
        # Optional validation. The runner resolves the Artifact ID through
        # Data_analysis and passes the resulting local file URI to CST.
        # required=False means a missing optional CST dependency produces a
        # warning and allows Data_analysis post-processing to continue.
        cst_validation={
            "operation": "cp2k.validate_output",
            "parameters": {"run_type": run_type},
            "required": False,
        },
        metadata={
            "question": "Extract and preserve structured data from an existing CP2K output",
            "source": "existing_cp2k_output",
        },
    )

    result = runner.run(task)

    print(f"Task: {result.task_id}")
    print(f"Status: {result.status.value}")
    print(f"Analysis Run: {result.analysis_run_id or 'not created'}")
    print("Output Artifacts:", [item.artifact_id for item in result.output_artifacts])
    print(
        "Evidence Package:",
        (result.evidence_package or {}).get("evidence_package_id", "not created"),
    )
    print(f"Scientific QC: {result.qc_status}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if result.error:
        print(f"ERROR: {result.error}")

    return 0 if result.status in {TaskStatus.SUCCEEDED, TaskStatus.WARNING} else 1


if __name__ == "__main__":
    raise SystemExit(main())
