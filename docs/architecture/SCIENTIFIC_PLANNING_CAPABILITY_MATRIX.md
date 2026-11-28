# Scientific Planning Capability Matrix

**Snapshot:** Computation--pipeline at PR #5 Head `23e664acaae01ee55f77e252bfa6eb838bd35db1`  
**Rule:** A Pipeline capability is implemented only when this repository has the applicable contract, planning, adapter/writer, parser, Artifact lineage and QC. Lower-level software support alone is not counted.

## Status vocabulary

- **IMPLEMENTED (narrow):** Pipeline code executes and validates the stated limited operation.
- **DATA / FIELD ONLY:** a field, keyword, extracted term or sample value exists but there is no complete planner/algorithm.
- **PROJECT-SCOPED:** implemented only in a named Project Plugin.
- **PARTIAL INTEGRATION:** some bridge or sub-step exists; it is not a complete end-to-end operation.
- **UNDERLYING SOFTWARE ONLY:** CP2K/ASE/Packmol or an external Skill describes support, but Pipeline does not have the whole path.
- **NOT PRESENT:** no concrete implementation was found in inspected paths.

## 1. Seven planning objects

| Object | Existing evidence | Current classification | Missing |
|---|---|---|---|
| ScientificIntent | Manifest claims, source blocks/locators, conflict and unresolved-definition diagnostics | DATA / FIELD ONLY | Intent object, exact objective/observable mapping, explicit scope decision and version/hash |
| ResearchPlan | Manifest dependency hints, task/claim extraction | DATA / FIELD ONLY | Work-package compiler, acyclic research DAG, evidence chain, alternatives, decision policies and minimum questions |
| ModelRecipe | CORR ModelSpec has explicit atoms/bonds/fragments/expected structure/build constraints/evidence | PROJECT-SCOPED | Generic recipe contract + plugin registry and other system-class implementations |
| MethodPlan | CalculationPlan validates a CP2K method mapping; Manifest classifies method terms | PARTIAL INTEGRATION | Evidence-driven method choice, parameter-level decision provenance, engine/version capability and license matrix |
| ExecutionPlan | CalculationPlan tasks/resources and WorkflowController dependencies | PARTIAL INTEGRATION | General task graph compilation, operation/plugin versions, resource provenance, full preflight and backend compatibility |
| QCPlan | Workflow completion/exit/artifact/convergence gates; CORR topology validator | PARTIAL / PROJECT-SCOPED | Independent per-task QC contracts with six distinct acceptance levels |
| Frozen CalculationPlan | Dataclass validation and SHA; WorkflowStore persists plan hash/JSON; PR #5 verifies exact Plan on resume | IMPLEMENTED (narrow) | Generalized plan compiler and versioned projections for other engines/task types; upstream object references |

## 2. Existing generic and project-specific modules

| Area | Existing implementation | Boundary |
|---|---|---|
| Frozen source intake | `plan_compiler.docx_reader`, `compile_docx` | Generic source adapter, not complete semantic research planner |
| Evidence/claim extraction | `plan_compiler.manifest` | Generic heuristic/evidence layer; not structure/method/resource algorithms |
| Executable plan validation | `calculation_plan.py` | Existing narrow CP2K-shaped executable contract |
| Project lifecycle | `project_lifecycle.py` shares `WorkflowStore._db` | Reuse same DB; currently direct CORR approval import must later move behind plugin interface |
| Project orchestration | `project_pipeline.py` | Reuse workflow/Data_analysis handoffs; currently direct CORR model-pipeline import is a future isolation seam |
| Model build and review | `projects/corr_dft_v4_1/model_plugin/` | CORR-specific structure and topology pipeline; never global defaults |
| Method values and blockers | `projects/corr_dft_v4_1/project_profile.json` | Project-scoped values, scope and blockers, not a method catalogue |
| Execution persistence | `workflow.py` | WorkflowStore/Controller and WorkflowAdapter already exist |
| HPC transport | `hpc_runtime.py` | Configured Slurm transport/job lifecycle; not resource estimation |
| Artifact custody | `real_adapters.py` Data_analysis bridge | Reuse official Artifact/Analysis Run/Evidence Package APIs |

**Boundary debt:** both `project_pipeline.py` and `project_lifecycle.py` currently import CORR-specific plugin functions. A generic ProjectPlugin/approval-provider seam is needed later; this design PR does not edit code.

## 3. Structure and model capabilities

| Capability | Current Pipeline status | Concrete gap |
|---|---|---|
| Explicit atom/topology spec | PROJECT-SCOPED | CORR ModelSpec requires atom IDs, elements, bonds, fragments, constraints and evidence |
| Candidate structure coordinates | PROJECT-SCOPED | CORR builder transforms coordinates and can write ASE extxyz |
| Model validation | PROJECT-SCOPED | CORR validator checks composition/formula, atom order/coordinates, bond/coordination ranges, charge/electron count, multiplicity parity, overlaps/readback |
| Independent review and user approval | PROJECT-SCOPED | CORR review package and frozen Data_analysis Artifact approval |
| Generic molecule/conformer generation | NOT PRESENT | No general molecule graph/conformer plugin and QC |
| Generic crystal generation | NOT PRESENT | No general crystal/phase/source-normalization plugin |
| Surface/slab/facet/termination planner | NOT PRESENT | No general slab recipe, termination, cell/vacuum or convergence planner |
| Adsorption/interface candidate generation | NOT PRESENT | No general adsorption site/orientation/interface match and strain planner |
| Explicit-solvent packing | UNDERLYING SOFTWARE / EXTERNAL SKILL ONLY | Packmol instructions are external; Pipeline has no packing plugin, output QC or equilibration task |
| Implicit solvation | UNDERLYING SOFTWARE ONLY | CP2K SCCS exists in software docs, but no Pipeline SCCS operation/method plugin/QC path |
| NEB / Dimer / TS | UNDERLYING SOFTWARE ONLY | CP2K BAND and ASE APIs exist; Pipeline lacks path recipe, registered operation, parser and per-image/TS QC |
| AIMD | UNDERLYING SOFTWARE ONLY / NOT IN CURRENT PLAN GRAMMAR | No AIMD operation and no ensemble/sampling QC in current plan workflow |

## 4. Method and software capability

| Parameter / capability | Current state | Required planner |
|---|---|---|
| XC functional | CP2K field `xc` required and presence validated | Source/policy decision and exact engine capability |
| Dispersion | Not an independently normalized required MethodPlan decision in current CP2K contract | Versioned model/parameter provenance and translation |
| Basis set | CP2K basis field and per-KIND definition required | File identity/hash, element/KIND and version checks |
| Pseudopotential | CP2K potential field/per-KIND definition required | Exact file identity, valence, element and compatibility validation |
| Cutoff / rel_cutoff | Positive numeric validation exists | Source/policy and convergence evidence |
| SCF method/convergence | Existing OT/DIAGONALIZATION, eps_scf/max_scf checks | Broader task-specific compatibility, stability and output QC |
| Charge / multiplicity / UKS | Explicit plan values; CORR model validator checks electron/spin parity | Generic model-derived evidence and policy; never infer missing charge/spin |
| Periodicity / cell / Poisson | CP2K periodicity/Poisson and cell fields validated | Generic system model and engine-specific capability |
| k-points / smearing | Can be extracted as Manifest terms, not planned generally | Evidence-backed task applicability and engine translation |
| Explicit/implicit solvent | Extractable terms only; no integrated planner | Separate packing/equilibration and continuum-solvent task families |
| Software/version capability matrix | No central complete registry found in inspected paths | Exact version/operation, writer, adapter, parser and QC state |
| License compatibility | Not a complete method-planner gate | Engine/plugin/data license metadata and site authorization |

## 5. Execution and resource planning

| Function | Current state | Missing |
|---|---|---|
| Workflow Run / task persistence | IMPLEMENTED | Reuse WorkflowStore |
| Dependency execution/recovery | IMPLEMENTED for current operations | Generic operation/task materializer and QC-gated edges |
| WorkflowAdapter | IMPLEMENTED (`preflight/execute/analyze`) | Plugin/capability registry around existing protocol |
| HPC submission transport | PARTIAL INTEGRATION | Do not add scheduler; connect planned task/resources to current backend profiles |
| Resource-related Manifest/Plan fields | DATA / FIELD ONLY | Typed resource profile, evidence and policy provenance |
| Calibrated resource prediction | NOT PRESENT | Historical-job estimator with uncertainty/out-of-domain refusal |
| Preflight | Existing runtime/backend checks | Per-operation software/data/license/filesystem/scratch/queue gates |

## 6. Task-specific QC coverage

| Task family | Pipeline QC now | Required contract |
|---|---|---|
| GEO_OPT | Workflow checks scheduler/app completion, output Artifact, convergence; CORR plugin checks structure | Files; normal end; force/geometry convergence; structure/constraints; scientific review; acceptance |
| ENERGY / SCF | Operation and output Artifact/Data_analysis handoff exist | Normal end, SCF convergence, energy validity, method/reference consistency |
| Frequency | NOT PRESENT | Hessian completeness, imaginary/near-zero modes, atom/constraint mapping and thermo applicability |
| NEB | NOT PRESENT | endpoint hashes/method match, atom mapping, per-image completion/forces, path validity/barrier stability |
| Dimer / TS | NOT PRESENT | search initialization, convergence, saddle Hessian, meaningful imaginary mode and reaction-coordinate alignment |
| AIMD | NOT PRESENT | trajectory integrity, timestep/ensemble/temperature, energy drift, equilibration and statistical sufficiency |
| Explicit solvent prep | NOT PRESENT | molecule/atom counts, topology, box/PBC, overlaps; separate minimization/equilibration |
| Electronic analysis | PARTIAL INTEGRATION through adapter/owner tools | parser-version completeness, units/atom map, normalization and scientific interpretation |

## 7. Summary

The foundation already exists: evidence-preserving source intake, a narrow CP2K CalculationPlan, the only WorkflowStore/WorkflowController, HPC transport and Data_analysis Artifact/Evidence custody. The missing layer is planning intelligence and shared contracts: general ResearchPlan, plugin registry, method capability/license selection, generic model recipes, provenance-backed resources and task-specific QC.

CP2K/ASE/Packmol feature availability must remain a separate category from Pipeline support. A manual keyword, external Skill, or underlying API is not a Pipeline feature until its complete planning, execution and QC chain is integrated and verified.
