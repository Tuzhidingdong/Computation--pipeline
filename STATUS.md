# Development Status — coordination-dft-publication-pipeline

Governing objective: TASK_PLAN_v1.0.0.md remains unchanged and authoritative. This status separates software contract evidence from real DOCX/model/science verification.

## Current development branch

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/plan-compiler-v41-model-plugin-20261127
- Base: 5e6e26fdf94efbac54182f819f4879c1aafb1d4d
- Latest development HEAD: tracked by the branch ref; no main/PR #1/PR #2 changes.
- Existing PR #1 and PR #2 remain Open / Draft / unmerged.
- No upstream Skill repository was modified.
- No HPC, Slurm, CP2K production calculation or real DFT job was started.

## New plan compiler and model lifecycle

| Capability | Status | Evidence / limitation |
|---|---|---|
| DOCX package parsing | IMPLEMENTED — synthetic DOCX CI-tested | Standard-library extraction of document body paragraphs, heading hierarchy, numbering IDs/levels, table cells and source locations; two-column table rows are promoted to labelled claims. |
| Evidence-backed claims | IMPLEMENTED — synthetic DOCX CI-tested | Labelled values remain unconfirmed claims; numeric/unit mentions remain source-linked evidence. |
| Conflict diagnostics | IMPLEMENTED — synthetic DOCX CI-tested | Conflicting values for the same normalized label are preserved and block execution. |
| Versioned Project Manifest | IMPLEMENTED — schema added | Generic schema v1.0.0; actual Frozen DOCX has not yet been supplied/located for real-input validation. |
| v4.1 profile | IMPLEMENTED | Project-specific profile carries system formulas, atom counts, electron counts, frozen method and WP task quantities from the governing plan. |
| v4.1 planning ambiguity checks | IMPLEMENTED — CI-tested | Blocks unresolved 15-orientation scope and six detailed fragment-spin candidates versus four-item summary mismatch. |
| CalculationPlan conversion | IMPLEMENTED — API added | Requires confirmed Manifest and registered/approved model Artifact ID plus SHA-256. Existing CalculationPlan validation is not weakened and no fake structure path is introduced. |
| Explicit model graph contract | IMPLEMENTED — unit-tested | Requires atom IDs, elements, coordinates, bond type/order, fragments, expected count/charge/multiplicity/candidate count and source evidence. |
| Candidate generation | PARTIAL — orchestration CI-tested | Project pipeline runs deterministic rigid transforms over an explicit supplied graph and enforces exact candidate count, global candidate IDs, donor mapping and recorded seed. It does not infer missing topology or create the real Cu/Sn support graph from formulas. |
| ASE structure output | IMPLEMENTED — dependency-gated | Production writer requires ASE and emits non-periodic extxyz. CI uses an explicitly test-only writer for contract tests. |
| RDKit topology validation | PARTIAL — optional and explicit | Declared organic fragments are checked when RDKit is installed and formal charges are supplied; no complete v4.1 graph has been validated. |
| Model validation | PARTIAL — API implemented | Checks composition, formula, atom count, pseudopotential valence electron count, spin parity, periodicity, overlaps, donor/bond mapping, coordination ranges and readback. No real candidate run because source graph/coordinates are unavailable. |
| Artifact registration | IMPLEMENTED — adapter bridge and CI fake | Registers structure, topology, metadata and validation report through Data_analysis `register_derived_artifact`, then re-resolves and re-hashes every file; format IDs are explicit. Not yet exercised against Agent A's live source checkout. |
| Model review package | PARTIAL — orchestration CI-tested | Produces structured candidate review index and blocks approval unless an injected real renderer creates a preview for every candidate. No real preview has been produced. |
| Approval freeze | IMPLEMENTED — orchestration CI-tested | Requires explicit approval, Data_analysis-verified ArtifactRef, passing report and matching SHA-256; approval record is write-once and integrity-checked. |
| Project lifecycle DAG | IMPLEMENTED — CI-tested | Pre-model stages persisted in the existing WorkflowStore database; stage order enforced; approved model is handed to existing CalculationPlan workflow. |

## Known v4.1 blockers preserved by the project profile

1. WP1's 15 docking orientations are not explicitly scoped as per catalyst or across both systems. No task count is inferred.
2. The explicit isolated-fragment spin list enumerates six candidates (Cu13 M=2/4/6; Cu-20 support M=1/3; SnCu-20 support M=2), while the WP1 summary states four fragment single points. No spin candidate is silently dropped.
3. The actual Frozen v4.1 DOCX source file and its location were not present in this repository or identifiable in the available prior project context.
4. The atom/bond graph, donor atom assignments, formal charges, and reproducible 3D construction constraints for the support/ligand/cluster assemblies are not present as executable source data. The project formulas are not enough to infer these.
5. No real candidate structure, preview, or model approval has been generated. These are hard blockers, not passing results.

## CI verification

Latest successful Actions run observed on this branch:
- 96 tests passed, 2 optional upstream integration tests skipped.
- `python -m compileall -q pipeline_contracts tests examples` passed.
- This evidence is software-only; the suite uses synthetic DOCX and test-only structure writers. It does not establish actual v4.1 chemistry or a real Artifact Registry integration.

## Next required source inputs

To complete real v4.1 compiler/model validation:
- Provide the exact Frozen v4.1 calculation-plan DOCX (upload it or provide its accessible repository path).
- Provide the frozen atom/bond/donor topology and 3D construction constraints if they are not embedded in that DOCX or its linked project files.
- Resolve the WP1 orientation scope and six-versus-four fragment single-point discrepancy explicitly. The compiler will not choose on the user's behalf.

No production HPC calculation is authorized or performed.
