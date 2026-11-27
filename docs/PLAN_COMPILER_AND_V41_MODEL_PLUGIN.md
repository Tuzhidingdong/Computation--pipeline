# Plan Compiler and v4.1 Model Plugin — interface design

## Ownership and existing interface mapping

| Capability | Existing owner/interface | New Pipeline responsibility |
|---|---|---|
| CalculationPlan | `pipeline_contracts.calculation_plan.CalculationPlan` | Convert only a confirmed Manifest after model approval |
| DAG persistence | `WorkflowStore` in `pipeline_contracts.workflow` | Persist project intake/model stages in the existing workflow control ledger |
| Artifact custody | Data_analysis Artifact Registry via `RealDataAnalysisAdapter` | Register/resolve generated structure files through the existing owner API |
| Chemistry operations | `RealCSTAdapter` and Agent A's chem-scitoolkit interfaces | Optional adapter binding; no copied chemistry algorithm |
| DOCX parsing | New `pipeline_contracts.plan_compiler` | Preserve paragraph/table order and source locations |

## Compiler lifecycle

`Frozen DOCX -> Extracted Blocks -> Evidence-backed Claims -> Project Manifest -> human confirmation -> approved Model Artifact -> CalculationPlan`.

DOCX parsing uses Python's standard library and preserves paragraph indices, table/row/cell coordinates, styles and numbering metadata. Labelled values are retained as claims requiring confirmation; unit-bearing numeric mentions are retained as evidence and are not silently promoted into authoritative parameters. Conflicting values for the same normalized label are both preserved and produce a blocking diagnostic.

The generic extractor deliberately does not infer a complete chemistry graph or select between ambiguous scientific statements. The Manifest is a versioned evidence container. Project-specific interpretation is an explicit v4.1 plugin responsibility.

## Pre-model CalculationPlan handling

The existing CalculationPlan remains unchanged and continues to require a real structure path or Artifact ID. The pre-model lifecycle is a project workflow stage, not a fake calculation structure. After model approval, the formal CalculationPlan must reference a Data_analysis Artifact ID and the exact SHA-256. No placeholder path is allowed.

## v4.1 model plugin boundary

The plugin consumes a versioned, evidence-linked explicit atom/bond graph and build specification. It must not synthesize missing atom connectivity, donor identities, formal charges, spin states, pseudopotential valence definitions or docking constraints from formula alone. Candidate generation must be deterministic and retain chemically distinct candidates.

Every output candidate is a complete model package: structure file, topology JSON, metadata, validation report and SHA-256. Registration is delegated to the existing Data_analysis Artifact Registry adapter. Approval records pin candidate ID, Artifact ID and file SHA-256; any changed bytes invalidate the approval.

## Scientific blocker

The checked-in v4.1 task plan records target compositions and electron counts, but the model builder still needs the frozen DOCX and explicit atom/bond/donor graph plus reproducible 3D construction constraints. These inputs are not fabricated by this implementation. Real v4.1 candidate construction and scientific validation remain blocked until those source definitions are supplied and parsed.


## Public execution APIs

- `pipeline_contracts.plan_compiler.compile_docx()` and `projects.corr_dft_v4_1.compile_v41_docx()` compile DOCX evidence into a versioned Manifest.
- `confirm_manifest_claims()` records owner confirmation against evidence IDs without editing source text.
- `confirm_v41_resolutions()` / CLI `resolve-v41-planning` require an explicit owner decision for both known WP1 ambiguities.
- CLI commands: `compile-docx`, `compile-v41-docx`, `confirm-manifest`, `resolve-v41-planning`, and `compile-calculation-plan`.
- `model_plugin.generate_validate_review()` runs the project lifecycle through candidate generation, validation, Data_analysis Artifact registration and review. It stops at `AWAITING_APPROVAL`; `approve_candidate()` creates the immutable approval record.
- `ProjectLifecycle.create_calculation_run()` verifies the frozen record and hands the approved Artifact ID/SHA into the existing `WorkflowController`.

## Dependencies and implementation boundary

`requirements-model-plugin.txt` declares ASE for production structure I/O and RDKit for organic-fragment topology sanitization. `toolchain_report()` records exact installed package versions at runtime. The current builder does not yet call molSimplify or MACE; they are not falsely reported as active integrations. Candidate geometry is presently deterministic rigid transformation of a complete explicit graph, not automatic metal-cluster topology inference or conformer generation.

## Verification boundary

CI tests use synthetic DOCX packages and test-only structure/Artifact adapters. They verify parser contracts, blocking diagnostics, lifecycle state transitions, hash pinning, registration calls and the approval gate. They do not prove real v4.1 candidate geometry, actual CP2K pseudopotential electron counts, live Data_analysis registration, or HPC readiness. Those require the real Frozen DOCX, explicit v4.1 graph/construction inputs, and Agent A's live Artifact API.
