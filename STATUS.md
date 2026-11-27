# Development Status — Computation--pipeline v4.1 integration

This status distinguishes software contracts from real-source, chemistry, Artifact and HPC evidence.

## Current branch and protection

- Repository: Tuzhidingdong/Computation--pipeline
- Branch: agent-b/plan-compiler-v41-model-plugin-20261127
- Development base: 5e6e26fdf94efbac54182f819f4879c1aafb1d4d
- PR #3 remains Draft and unmerged.
- main, PR #1, PR #2 and all upstream Skill repositories remain untouched.
- No HPC/Slurm submission or production CP2K/DFT execution was performed.

## Real Frozen DOCX source

The exact owner-side source already exists at:

`F:\cp2k practical\hyy\CORR_DFT_Computational_Plan_v4.1_Frozen.docx`

A prior local run under `F:\cp2k practical\hyy\pipeline_real_test_20261127_01\` extracted 45 body paragraphs and 10 tables and produced `plan_extracted.md`, `plan_parameters.json`, `source_manifest.json` and the complete extracted text. This PR's new compiler has not yet been run against that exact file. The source DOCX is not copied into the repository.

## Implemented software contracts and their current limits

| Capability | Current status | Boundary |
|---|---|---|
| Generic DOCX reader | Implemented; synthetic DOCX CI-tested | Extracts body paragraphs, heading levels, numbering metadata, table cells and source coordinates. It has not yet been validated against the owner-side Frozen DOCX in this branch. |
| Evidence-backed Manifest | Implemented; synthetic DOCX CI-tested | Preserves source blocks and labelled claims, keeps unconfirmed claims unresolved, and blocks conflicting labelled values. File-level source SHA/provenance still needs to be added. |
| v4.1 project profile | Implemented as a project-specific reference profile | Contains system/method/task values maintained in the repo. The compiler currently overlays this profile; it does not yet reconcile every profile field to exact evidence from the Frozen DOCX. |
| Known WP1 ambiguity controls | Implemented; CI-tested | Requires an explicit orientation scope. Spin-count mismatch now permits either owner-confirmed retention of all six named candidates or explicit selection of four named candidates; it no longer silently fixes one scientific interpretation. |
| CalculationPlan conversion | Partial | Existing CalculationPlan validation is preserved. Current CLI requires a separate CalculationPlan JSON; the full DOCX/Manifest-to-CalculationPlan compiler is not yet implemented. |
| v4.1 explicit model spec | Implemented as a strict input contract | Requires explicit atom IDs, elements, positions, bonds, donor IDs, expected composition/count/charge/spin and per-bond distance windows. These requirements do not create the missing chemistry graph. |
| Candidate builder | Partial — transform-only | Performs deterministic rigid transforms over a complete, externally supplied atom graph and coordinates. It does not yet construct Cu-20, SnCu-20, SnCu-20 support, Cu13 or their chemistry from project sources. |
| ASE writer | Implemented, dependency-gated | Production path writes non-periodic extxyz with persistent atom IDs. Current CI uses test-only writers; no production ASE model output has been validated. |
| RDKit / molSimplify / MACE | Not yet integrated in the production builder | `toolchain_report()` reports installed package versions only. It does not invoke RDKit sanitization, molSimplify coordination construction, or MACE pre-screening. |
| Model validator | Improved contract; not real-model validated | Checks composition, count, charge, pseudopotential electron count, spin parity, atom identity/order, coordinate mapping, explicit covalent/coordination distance windows, donor mapping, overlaps and structure readback. No real v4.1 graph has passed it. |
| Artifact registration | Adapter bridge only; fake API CI-tested | Registers structure/topology/metadata/report via the Data_analysis API and resolves/re-hashes registered files. Live Agent A checkout integration is untested. |
| Model review | Partial | Requires a preview for every candidate before review is ready. The renderer is injected; no production 3D renderer or real preview has been demonstrated. |
| Approval freeze and CalculationPlan handoff | Contract implemented; fake/in-memory CI-tested | Pins Artifact ID and SHA and blocks handoff if approved bytes differ. Live Data_analysis Artifact registration/approval has not been verified. |
| Project lifecycle | Implemented; SQLite contract CI-tested | Reuses WorkflowStore for persisted stages. Real run recovery and live end-to-end integration remain unverified. |

## v4.1 planning facts and unresolved decisions

- Current project profile records Cu-20 as 83 atoms / 417 explicit valence electrons and SnCu-20 as 84 atoms / 426 explicit valence electrons. These values must still be reconciled with the exact Frozen DOCX during the branch's real-input test.
- The 15 docking orientations are not explicitly scoped as per catalyst or across both systems.
- The detailed isolated-fragment spin list has six candidates (Cu13 M=2/4/6; Cu-20 support M=1/3; SnCu-20 support M=2), while the summary states four. The code now requires an explicit owner decision and preserves the exact selected candidate IDs.
- The atom/bond/donor graph, formal charges and reproducible 3D construction constraints for all complete support/ligand/cluster assemblies are not yet available as executable model input. Formulas alone are insufficient.

## CI evidence

- Successful Actions run #387 tested PR merge commit `0bb46db`, which included branch commit `a2d6ec44abc633b56261a4d50f455c2a280ffe03`.
- Result: 98 tests passed, 2 optional upstream integration tests skipped; `compileall` passed.
- Two additional path-safety / finite-transform tests were committed after that run and still require a fresh CI result.
- All current CI evidence is software/contract evidence. It is not a real Frozen DOCX parse, a real v4.1 chemistry build, live Artifact registration, or HPC calculation.

## Next validation gates

1. Run this branch's compiler against the existing owner-side Frozen DOCX and compare evidence, manifest claims and profile fields against the previously extracted 45 paragraphs / 10 tables.
2. Resolve WP1 orientation scope and six-versus-four fragment spin discrepancy with the owner; do not guess.
3. Identify source-backed atom/bond/donor topology and construction constraints for actual model assembly. If they are not available, preserve the blocker rather than manufacture a structure.
4. Complete production model construction, ASE/RDKit/appropriate geometry-tool integration, real preview generation and Data_analysis registration.
5. Verify the live approved-model-to-CalculationPlan handoff. Only after this review can the local Agent proceed to the explicitly authorized real-environment preflight; no HPC submission is currently authorized.

No production HPC calculation is authorized or performed.
