# External Computational Skills — Design and License Audit

**Audit date:** 2026-11-28. Revisions are pinned below. The review inspected repository metadata, root licensing and named files. This document records architecture observations only; it does not copy source code or entire Skill text.

## Snapshot and license

| Repository | Default branch and inspected commit | License finding | Reuse position |
|---|---|---|---|
| [jianzushen/Computational-chemistry-skill](https://github.com/jianzushen/Computational-chemistry-skill) | `main` `4ea66ea8633e4a65d5b9041928b363b0375bb81b` | **MIT**; root LICENSE and GitHub metadata agree | MIT reuse is generally permitted subject to notice/attribution terms. This PR only records abstract design ideas. |
| [JCLiuGroup/AI-Computational-Chemist](https://github.com/JCLiuGroup/AI-Computational-Chemist) | `main` `e27b555ecfee3a7b66472c19c93b01ad0a1ccae1` | **CC BY-NC 4.0** explicitly stated in actual root LICENSE; GitHub metadata says `NOASSERTION` | Non-commercial restriction applies to the collection. No code, Skill prose or knowledge text copied. Obtain specific legal review/permission before reuse in a commercial/uncertain context. |
| [jinzhezenggroup/computational-chemistry-agent-skills](https://github.com/jinzhezenggroup/computational-chemistry-agent-skills) | `master` `8ab83a96292bb4d13ba7e4a2b015015f0332e8cc` | **LGPL-3.0** root LICENSE/metadata | Any later code reuse needs LGPL obligations and distribution/linking review. An individual Skill may declare a different license; check exact file and origin. |
| [aimat-lab/agent-skills](https://github.com/aimat-lab/agent-skills) | `master` `255436690891676f755d26e9f50cea368ea664fb` | No root LICENSE file found in inspected tree; GitHub license metadata is null | No reuse license established. Do not copy code or text without explicit permission. |

This is a technical license audit, not legal advice. A file's frontmatter license does not automatically override all repository files or third-party dependencies.

## A. Computational-chemistry-skill

**Files inspected:** `SKILL.md`; `references/stage-1-plan-schema.md`; `references/stage-1-evidence-and-methods.md`; `references/stage-1-workflow.md`; `references/global-project-control-workflow.md`; `references/stage-2-step-1-surface-workflow.md`; `references/stage-2-step-2-interface-workflow.md`; `references/stage-2-step-3-formal-workflow.md`; `references/stage-2-result-return-workflow.md`.

**Useful architecture:** staged research intake before later surface/interface/formal computation; a versioned machine-readable JSON plan is authoritative while Markdown/HTML are projections; task IDs map to questions, systems, controls, evidence, observables, outputs and dependencies; source checksums and change-intent records protect historical decisions; method choice is question/system/observable/evidence driven; major interface choices and result acceptance have explicit review gates; resource estimates are not fabricated.

**Candidate interfaces to adapt:** ScientificIntent/ResearchPlan; immutable plan revisions; evidence chain and field locators; DAG nodes with stable IDs; explicit assumptions and decision change records; model/interface gates.

**Do not import:** its project-specific scoring weights, policies, sample parameters or state files. Pipeline already has WorkflowStore; do not add a parallel control store.

**License:** MIT verified at repository root. This PR contains no copied code or Skill passages.

## B. AI-Computational-Chemist

**Files inspected:** `procedures/literature-to-calculation/SKILL.md`; `procedures/research-orchestrator/SKILL.md`; `procedures/research-orchestrator/references/model-structure-review.md`; `tools/cp2k/references/neb-dimer.md`; `tools/cp2k/references/sccs-solvation.md`; `tools/cp2k/SKILL.md`; `knowledge/electronic-structure.md`; `knowledge/periodic-dft-modeling.md`; root `LICENSE`.

**Useful architecture:** literature-derived calculation target captures document locator, claim, system/method fingerprint, required inputs, expected output and comparison convention; a research orchestrator acts as control-plane protocol rather than scheduler; readiness derives from dependencies, approvals, leases and artifacts; `completed`, `validated` and `accepted` are distinct; model producer cannot self-approve and an independent critic issues the gate; NEB requires converged endpoints, stable atom order and matched method, image-level QC and separate TS/frequency confirmation; SCCS is distinguished from explicit solvent-specific interactions and requires a matched thermodynamic cycle.

**Candidate interfaces to adapt:** EvidenceRef, DecisionRecord, dependency readiness, producer/critic separation, task-specific Skill routing, NEB endpoint/QC contract, explicit solvation model provenance.

**Do not import:** its `.research` store, scripts, knowledge prose or CP2K example values. The Pipeline retains WorkflowStore, WorkflowController and Data_analysis ownership.

**License:** actual LICENSE explicitly says CC BY-NC 4.0 although GitHub metadata reports NOASSERTION. Abstract ideas only are recorded here.

## C. computational-chemistry-agent-skills

**Files inspected:** `data-processing/packmol-generate-mixture/SKILL.md`; `atomistic-workflows/ase/ase-workflows/neb/SKILL.md`; `atomistic-workflows/ase/ase-workflows/relax/SKILL.md`; `quantum-chemistry/dft-cp2k/SKILL.md`; related task-skill directory structure and root `LICENSE`.

**Useful architecture:** operation-scoped skills routed by a thin engine router; Packmol inputs explicitly require molecule structures, counts, density or fixed box, tolerance and output path; packed XYZ is only initial coordinates, not topology or equilibrated solvent; NEB skill requires initial/final states, backend, image count and convergence policy; the CP2K router separates static, relax, MD and electronic-analysis operations and refuses missing prerequisites.

**Candidate interfaces to adapt:** per-operation plugin and JSON contracts; explicit input prerequisites; packing as a preparation task separate from equilibration; NEB backend binding and returned assumptions.

**Do not import:** Packmol tolerances/counts, NEB spring/image examples, CP2K parameter values or cluster resources as defaults. The inspected ASE NEB subskill header declares MIT while the root repository license is LGPL-3.0; any later reuse requires exact per-file origin/license review.

**License:** repository root LGPL-3.0. No code or Skill text copied.

## D. aimat-lab/agent-skills

**Files inspected:** `autoslurm/SKILL.md`; `kit-ki-toolbox/SKILL.md`; `md-multiatoms/SKILL.md`; `xtb/SKILL.md`; root README and tree.

**Useful architecture:** environment discovery is machine-specific; avoid assumptions about available queue configs or packages; dry-run and resource packing are inspectable before submit; retry/concurrency should be bounded; router and backend details are separated. These are valuable resource/preflight and adapter integration ideas, not a complete scientific planning schema.

**Candidate interfaces to adapt:** versioned environment/capability discovery, dry-run preflight, resource policy provenance, bounded recovery and concurrency.

**Do not import:** AutoSlurm configuration or cluster-specific commands; Pipeline already owns its HPC runtime adapters and must not add a second scheduler.

**License:** no root LICENSE file and no license metadata found in the inspected snapshot. Do not reuse source or Skill text without permission.

## Cross-repository comparison

| Design concern | Main design reference | Pipeline adaptation |
|---|---|---|
| Scientific intent / Research Plan | Computational-chemistry-skill stage-1 plan; AICC literature-to-calculation | Typed objects with page/section/figure/table and SHA evidence |
| DAG, readiness, approvals | AICC research-orchestrator | Derived ready/blocked state using existing lifecycle/workflow records |
| Structure audit | AICC model-structure-review; local CORR model plugin | Separate candidate producer and reviewer, no self-approval |
| Method and software capability | Computational-chemistry-skill evidence-and-methods | Engine/version/operation/license matrix with writer/parser/QC proof |
| Explicit solvent | agent-skills Packmol preparation | Dedicated packing recipe and validation, separate equilibration |
| Implicit solvent | AICC CP2K SCCS | Versioned method parameters, boundary conditions and energy-cycle QC |
| NEB/Dimer/TS | AICC CP2K path guide; agent-skills ASE NEB | Endpoint hashes/mapping, path artifact, per-image QC, separate TS verification |
| Engine and Skill routing | AICC CP2K router; operation-scoped skills | Generic plugin registry plus existing WorkflowAdapter |
| Resource / HPC | aimat-lab AutoSlurm; existing Pipeline HPC runtime | Environment discovery, resource provenance/uncertainty, no new scheduler |

## Future borrowing rules

1. Prefer independently written interfaces based on general principles.
2. Record URL, inspected commit, exact path and license for every reference.
3. Do not paste third-party Skills, scripts or long passages into this repository.
4. Verify exact file, root license, dependencies and distribution context before code reuse.
5. Do not turn external examples into default scientific parameters.
6. Treat missing license as no reuse permission until explicit authorization is obtained.
