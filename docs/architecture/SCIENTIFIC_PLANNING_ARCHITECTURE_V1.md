# Scientific Planning Architecture v1

**Status:** architecture proposal only  
**Baseline:** PR #5 Head `23e664acaae01ee55f77e252bfa6eb838bd35db1`  
**Scope:** object contracts, module boundaries, capability audit and implementation roadmap. No algorithm, scientific parameter, project profile, scheduler, engine adapter or existing PR is changed.

## 1. Architecture

The Pipeline needs a **scientific planning layer**, not another workflow engine. It compiles source-backed research intent into reviewable planning objects, then freezes their validated projection into the existing CalculationPlan boundary.

```text
Frozen sources + user intent
        |
        v
ScientificIntent
        |
        v
ResearchPlan ---- decisions / evidence gaps / research DAG
        |
        +---------------------+
        |                     |
        v                     v
ModelRecipe(s)             MethodPlan
        |                     |
Structure plugins       Method/capability planner
        |                     |
        +----------+----------+
                   |
                   v
             ExecutionPlan
                   |
                   v
                 QCPlan
                   |
                   v
validation + approvals + canonical hashes
                   |
                   v
          frozen CalculationPlan
                   |
                   v
existing ProjectLifecycle / WorkflowStore / WorkflowController
                   |
                   v
existing WorkflowAdapter / HPC transport / Data_analysis Artifact-Evidence
```

This is a dependency graph, not a forced linear sequence. Model feasibility and method feasibility may be explored in parallel; executable plan freeze requires all referenced components, evidence, capability and approval gates to pass.

### Non-negotiable boundaries

1. **Evidence before parameters.** Valid JSON is not scientific authorization. Each material field is evidence-backed, policy-selected within a recorded scope, explicitly not applicable with rationale, or missing.
2. **Planner is not an executor.** It creates decisions, recipes, dependency graphs and plan projections. It does not submit jobs.
3. **One state ledger.** Reuse WorkflowStore. ProjectLifecycle continues to share its SQLite database. Do not add another WorkflowStore, Artifact Store, scheduler or generic execution engine.
4. **Retain CalculationPlan.** `pipeline_contracts.calculation_plan.CalculationPlan` remains the executable boundary. Its current v1.0 contract is CP2K-oriented; add future capabilities through explicit schema/versioned projections, not silent reinterpretation.
5. **Artifact custody is upstream-owned.** Data_analysis continues to own Artifact registration, content hashes, source lineage, Analysis Runs and Evidence Packages.
6. **Domain rules live in Project Plugins.** Generic planning code must not contain CORR chemistry or import CORR defaults. CORR v4.1 continues to provide its own DOCX adapter, profile, model rules and approval semantics.
7. **No invisible defaults.** Do not infer atom topology, charge, multiplicity, spin, solvent, XC, dispersion, basis/pseudopotential, cutoffs, convergence criteria, cell, Poisson solver, k-point or smearing values.

## 2. What exists in the current code

| Current path | Verified responsibility | Reuse / limitation |
|---|---|---|
| `pipeline_contracts/plan_compiler/docx_reader.py` | Reads frozen DOCX blocks and source locations | Reuse source-ingestion adapter; not a complete scientific semantic parser |
| `plan_compiler/manifest.py` | Extracts claims, evidence, unresolved definitions, conflicts and method/model/resource keyword buckets | Reuse evidence intake. Keyword classification is not ResearchPlan/MethodPlan/ResourcePlan logic |
| `plan_compiler/compiler.py` | Compiles DOCX into an evidence-preserving Manifest; confirmed Manifest compiler rejects blockers/unresolved definitions and requires approved Artifact ID/SHA in supplied CalculationPlan mapping | Reuse source/Manifest gates; currently does not infer a full planning bundle |
| `pipeline_contracts/calculation_plan.py` | Versioned dataclass, canonical SHA, validation of CP2K-oriented fields; operations presently limited to `cp2k.geo_opt`, `cp2k.energy`, `dft.artifact.read` | Keep as frozen executable object; current operation grammar is narrow |
| `pipeline_contracts/project_lifecycle.py` | Stage status, model approval records and transitions share `WorkflowStore._db` | Reuse. Current file imports CORR approval verification directly: generic-boundary debt |
| `pipeline_contracts/workflow.py` | WorkflowStore persists runs/tasks/events/attempts and plan hash/JSON; WorkflowAdapter is `preflight/execute/analyze`; WorkflowController handles DAG, resume/recovery and current GEO_OPT→ENERGY dependency | Reuse the one execution control plane |
| `pipeline_contracts/project_pipeline.py` | Orchestration and Data_analysis Artifact/Evidence handoff, including PR #5 frozen plan resume integrity | Reuse sequencing; currently directly imports CORR model plugin, a boundary to isolate later |
| `pipeline_contracts/real_adapters.py` | Existing bridge to Data_analysis and chem-scitoolkit APIs | Reuse owner APIs. Adapter existence does not prove every scientific operation is implemented |
| `pipeline_contracts/hpc_runtime.py` | Configured Skill/Slurm SSH/SCP transport, preflight, job IDs, status and artifact retrieval | Reuse transport; it is not a calibrated ResourcePlanner |
| `projects/corr_dft_v4_1/plan_compiler.py` | CORR document claim enrichment and profile reconciliation | Remains project-specific |
| `projects/corr_dft_v4_1/model_plugin/` | Explicit ModelSpec, candidate builder, ASE extxyz output, topology/geometry/electron validation, review package and user approval | Real but project-scoped implementation, not a generic structure framework |
| `projects/corr_dft_v4_1/project_profile.json` | CORR frozen method/model/scope data and WP1 blockers | Data only; not a generic default catalogue |

### Concrete code facts

- The current Manifest has method/model/resource terms and dependency extraction heuristics. It does **not** choose functionals, generate atomistic topology, estimate walltime or compile a complete research DAG.
- Current CalculationPlan validates a required set of CP2K values (XC, basis/pseudopotential, cutoffs, SCF, charge, multiplicity, periodicity/Poisson, KIND data and cell). Validation of a supplied mapping is not automatic scientific method selection.
- Its allowed operations are three narrow identifiers; the current WorkflowController starts with GEO_OPT and dynamically adds ENERGY after the existing convergence/Artifact gate.
- The CORR model plugin is substantive: its model specification represents atoms/bonds/fragments; its validator checks composition, atom mapping/order/coordinates, charge/electron count, multiplicity parity, bond/coordination geometry and overlaps; it registers candidates, generates review artifacts and waits for explicit approval. This is **PROJECT-SCOPED**.
- ProjectLifecycle and project_pipeline currently have direct CORR imports. A later refactor should introduce a ProjectPlugin/approval provider registry; do not rewrite that dependency in this documentation-only PR.
- Existing HPC runtime is transport and scheduler job handling. It does not yet supply a general calibrated resource estimate or task-specific science QC.
- CP2K/ASE APIs and external Skills are not Pipeline integration. A feature becomes Pipeline-supported only when its plugin, frozen task contract, engine writer/adapter, output parser, Artifact handoff and QC have been implemented and validated together.

## 3. The seven planning objects

The complete strict structural schema is `schemas/scientific-planning.schema.json`; a purposely BLOCKED example is under `schemas/examples/`. The schema is structural. Runtime semantic validators must also check hashes, references, source coverage, graph acyclicity, capability and approval consistency.

### 3.1 ScientificIntent — what question is being asked?

**Fields:** stable `intent_id`, `project_id`, research question, research object/comparison/phenomenon/target conclusion, requested observables and task families, constraints (required/prohibited/preferred/budget/scope), source EvidenceRefs, unresolved questions, status and provenance.

**Sources:** user statement, frozen DOCX/PDF/manuscript/SI, experiment, registered Artifact or cited literature. Store source SHA-256 and exact page/section/paragraph/table/figure/record locator.

**Hash/version:** canonical object SHA. Question, scope, comparison or success criterion changes create a new revision; do not rewrite the original source record.

**Depends on / feeds:** source intake and stable project identity; feeds ResearchPlan.

**Validation/BLOCKED:** no traceable evidence for a claimed fact; decisive source conflict; ambiguous system, comparison or observable; unsupported target conclusion.

**Approval:** users authorize research scope, comparison, exclusions and changes to success criteria. Extraction can be automated; intent approval cannot be silently inferred.

### 3.2 ResearchPlan — which evidence and tasks answer the intent?

**Fields:** `plan_id`, Intent object ID/version/SHA, objectives and observable success criteria, work packages, task families, dependencies, required inputs, expected outputs, decision records, evidence gaps, assumptions, status and provenance.

**Sources:** ScientificIntent, source documents, evidence chain and approved project policies.

**Hash/version:** hash the exact intent reference, work packages, dependency edges, decisions and assumptions. Semantic changes create a new plan revision.

**Validation/BLOCKED:** objective without a measurable observable; unlinked or cyclic task dependencies; absent required input; conclusion without an evidence-producing observable; unapproved assumption promoted to fact.

**Approval:** system may compile dependency order within scope. User approves scope changes, deletion of necessary controls, or trade-offs that can alter conclusions.

### 3.3 ModelRecipe — which exact atomic model is required?

**Fields:** model class, plugin ID/version, input ArtifactRefs, origin (supplied/reproduced/database-derived/designed/reconstructed/generated), composition, atom identities, topology/connectivity, coordinates or construction recipe, charge/multiplicity/spin, constraints, construction steps, validation contract, evidence/decision records and gaps.

Model classes include molecule/conformer, crystal, surface/slab, adsorption/interface, explicit solvent, implicit-solvation context and transition-state path. Null charge/spin/topology means unresolved, not neutral/singlet or a guessed graph.

**Sources:** original structure Artifact, paper/SI, validated database record, explicit user description or approved reconstruction.

**Hash/version:** bind source Artifact bytes, recipe, generator/plugin/version, deterministic transform settings, topology and produced structure bytes. A coordinate file hash alone does not freeze topology.

**Validation/BLOCKED:** formula-only structure without atom-level graph; missing atom mapping, coordination or donor evidence; invalid valence/electron/spin parity; unresolved charge/spin; unsupported cell/termination; missing generator/validator pin.

**Approval:** model producer cannot approve its own structure. An authorized reviewer accepts the exact Data_analysis Artifact ID/SHA before the recipe can be consumed by an executable CalculationPlan.

### 3.4 MethodPlan — which method applies to this model and task?

Each material parameter is a `ParameterDecision`:
- `EVIDENCED`: directly supported by original source, literature reproduction or supplied validated input.
- `POLICY_SELECTED`: selected using an already approved, versioned policy within its explicit applicability scope.
- `MISSING`: no value; do not fill it.
- `NOT_APPLICABLE`: explicitly justified for this task.
- `NEEDS_APPROVAL`: candidate or trade-off awaits authorized approval.

**Required parameter groups:** XC functional; dispersion; basis set; pseudopotential; cutoff and relative cutoff; SCF strategy and convergence; charge, multiplicity, spin and UKS; periodicity, cell and Poisson solver; k-points and smearing; explicit/implicit solvation; exact software/version capability; license compatibility. Engine-specific extensions must be namespaced.

**Source priority:** original research/reproduction settings → cited paper/SI → approved project protocol → explicit user-approved choice → capability-constrained alternatives. A lower-priority source cannot silently override a higher-priority one.

**Hash/version:** include values, units, engine/version, applicability scope, source/policy refs and capability/licensing evidence. Engine or dataset version change may invalidate capability checks and requires a new revision.

**Validation/BLOCKED:** any missing decisive parameter; missing basis/potential data; unsupported keyword combination for exact version; incompatible/unknown license; charge/spin inconsistency; unsupported periodicity/solvent; method not applicable to the required observable.

**Approval:** methodological deviations, approximations and physically consequential changes need explicit approval unless a scoped approved policy already authorizes them.

### 3.5 ExecutionPlan — where and with what resources is the DAG run?

**Fields:** task nodes with operation/plugin/version, dependencies, Artifact inputs/outputs, parameter fingerprints, QC contract refs; backend/adapter; resource profile; preflight requirements; evidence, decisions and gaps.

**Resources:** atom count/system class, software/task type, CPU cores, MPI ranks, OpenMP threads, GPU count/model, memory, walltime and scratch. Each known value requires provenance. Estimates carry method, sample coverage and uncertainty/limitations; they are not a guaranteed runtime.

**Sources:** model metadata, exact software requirements, configured site/queue policy, administrator-approved bounds and comparable completed jobs.

**Hash/version:** task DAG + backend + adapter/environment identity + requested resources + resource evidence.

**Validation/BLOCKED:** no compatible adapter, executable or data files; license unavailable; queue/account/profile not approved; preflight/filesystem/scratch failures; resource estimate outside calibrated applicability. Unknown walltime remains UNKNOWN.

**Approval:** auto-select only within approved hardware, queue and budget bounds. Site/architecture/budget changes outside policy require approval.

### 3.6 QCPlan — which independent proof is required?

Do not collapse these into one success boolean:
1. **File completeness** — declared files, parse/schema validity and hashes.
2. **Program normal termination** — engine/scheduler records show normal end, not merely nonzero/zero exit code.
3. **Technical convergence** — task-specific convergence criteria.
4. **Structural plausibility** — atom count/order/topology/geometry/constraints/path/solvent checks.
5. **Scientific validity** — model/method/reference choices and stability support the scientific interpretation.
6. **User acceptance** — designated authority accepts the result for the specified purpose.

QC task families include GEO_OPT, ENERGY/SCF, Frequency, NEB, Dimer, TS, AIMD, explicit solvent preparation and electronic-structure analysis.

**Sources:** validated parser/checker and its exact version; task-specific science contract; engine manual/version; approved project and user acceptance policy.

**Hash/version:** hash criteria, thresholds and their provenance, parser/checker versions, evidence requirements and authority. Changing a QC rule creates a new version.

**BLOCKED:** missing/truncated output, wrong task marker, no required convergence, invalid structure, unsupported scientific inference or missing acceptance. An authorized waiver is a distinct decision; it cannot turn FAIL into PASS.

### 3.7 CalculationPlan — frozen executable projection, not LLM-generated parameters

Only a deterministic compiler may create it after upstream objects and required approvals validate. It binds exact Intent/ResearchPlan references, approved model Artifact(s), MethodPlan and capability/license evidence, ExecutionPlan DAG/resource source, QC contracts, approvals, plugin and adapter versions.

The current `CalculationPlan` Python class remains the runtime boundary. Its existing CP2K-shaped `1.0` form must keep working. This architecture schema is the richer planning-bundle contract; a future versioned compiler will create a compatible execution projection or a new explicit CalculationPlan schema version. No in-place schema reinterpretation is allowed.

A Workflow Run freezes the full canonical CalculationPlan. PR #5's database-backed plan hash/JSON and strict resume verification is the existing invariant to reuse. Changed sources, model, method, engine capability, resource request or QC rule require a new plan revision and approval; never mutate a running plan.

## 4. Three automation decision paths

Every automatic choice stores selected value, source/policy version, applicability scope, candidates, rejected candidates and reasons, assumptions, uncertainties and whether approval is required.

### A. Decisive evidence or approved fact

Compile deterministically from one clear source or approved policy. Preserve exact source locator and SHA. Conflicting decisive sources generate a conflict and block the dependent field; do not majority-vote scientific parameters.

### B. Multiple valid choices with an approved policy

Enumerate candidates; check only declared policy criteria; rank deterministically; store excluded candidates/reasons. Auto-select only if the policy explicitly authorizes automatic selection for this system/task/version/range. If the policy permits recommendation but not auto-selection, set `AWAITING_USER_APPROVAL`.

Policies may cover software availability, verified capabilities, license compatibility, approved budget bounds or an owner-approved tie-break. API/keyword similarity is not scientific equivalence.

### C. Missing decisive scientific information

Mark the dependent node `BLOCKED`, identify the smallest evidence gap and ask the minimum question that resolves it. Never guess atom topology, charge, spin, solvent, cell/termination, XC, basis/pseudopotential, k-point, smearing, reaction endpoints or resource allocation. A solvent name does not define composition/count/box; a TS request does not define endpoints or atom mapping.

## 5. Plugin interfaces and ownership

A plugin descriptor records immutable ID/version, plugin kind, supported operations, input/output schema IDs and hashes, system/task applicability, dependencies/software/version/license, deterministic behavior, validators, verification evidence and unsupported cases. Capability state is one of `VERIFIED`, `PARTIAL`, `PLANNED`, `UNVERIFIED`, `INCOMPATIBLE` and always version/evidence scoped.

### Structure / model plugins

Conceptual contract:

```python
class StructurePlugin(Protocol):
    descriptor: PluginDescriptor
    def propose(self, intent, recipe_request, evidence, policy) -> CandidateSet: ...
    def build(self, approved_recipe, artifact_api) -> tuple[ArtifactRef, ...]: ...
    def validate(self, recipe, artifacts) -> StructureQCResult: ...
```

Separate operations:
- `molecule/conformer`: graph and atom mapping, conformer candidates, duplicate and selection policy.
- `crystal/surface/slab`: crystal source, space group, Miller index, termination, cell, slab/vacuum, symmetry, constraints and convergence.
- `adsorption/interface`: sites/orientations, surface matching, strain allocation, contact geometry, atom mapping and independent review.
- `explicit-solvent-packing`: molecule source Artifacts, counts/composition, density or box, regions, tolerance, PBC and seed; packed configuration is not equilibrated solvent.
- `implicit-solvation`: engine-specific continuum model, dielectric/cavity/electrostatic setup and version; require cycle consistency and sensitivity policy.
- `transition-state-path`: approved endpoints, atom correspondence, path strategy and engine-specific NEB/Dimer/TS capability.

Producer and critic are separate roles. Candidate construction may occur before approval; engine consumption waits for accepted model Artifact.

### Method Planner

```python
class MethodPlanner(Protocol):
    def compare(self, task, model_recipe, candidates, capability_registry,
                evidence, approved_policies) -> MethodDecisionSet: ...
    def validate(self, selected_method, engine_version, data_files) -> MethodValidation: ...
```

For every engine distinguish manual feature availability, exact installed-version support, Pipeline input writer, runtime adapter, output parser, task-aware QC, and compatible license/data files. Only a complete verified chain qualifies as Pipeline-supported.

### Resource Planner

```python
class ResourcePlanner(Protocol):
    def profile(self, model_metadata, software_task, capability,
                site_policy, historical_jobs) -> ResourceDecision: ...
```

Report model provenance, comparable sample size/range, predicted interval or uncertainty class, limitations and out-of-domain status. When calibration is absent, return UNKNOWN/BLOCKED or a policy-bounded user allocation; do not invent walltime.

### QC Planner

```python
class QCContractProvider(Protocol):
    def contract_for(self, task_type, engine_id, engine_version,
                     method_plan, approved_policy) -> QCContract: ...
    def evaluate(self, contract, outputs, artifact_api) -> QCResult: ...
```

A QC PASS releases only its authorized downstream dependency. It never implies scientific/user acceptance.

### Engine and workflow adapters

Do **not** create a parallel executor interface. Extend/route to the existing `WorkflowAdapter.preflight/execute/analyze` via operation and engine registries. Existing WorkflowStore persists runs/tasks/events/attempts; existing WorkflowController owns dependencies/recovery; existing HPC runtime owns transport; Data_analysis owns Artifacts/Evidence.

## 6. Readiness and state ownership

A task is ready only when dependencies complete, exact input Artifacts resolve with matching SHA, required QC passes, approvals validate, relevant plugin/engine capability is VERIFIED for that version, and no decisive evidence gap remains.

Proposed nodes may exist before approval, but cannot be dispatched before gates release. Iteration creates new tasks/revisions; never rewrite historical decision or execution events.

| Owner | Responsibility |
|---|---|
| Scientific planning layer | typed intents/plans, decisions, evidence gaps, capability comparison and DAG compilation |
| ProjectLifecycle | project-stage/approval state in existing WorkflowStore DB |
| WorkflowStore / WorkflowController | Workflow Runs, task execution state, attempts, events, recovery and dependency dispatch |
| Project Plugin | project-specific evidence enrichment, domain rules, model generation/validation and policy |
| Data_analysis | Artifact custody, hash verification, Analysis Runs, Evidence Packages |
| Workflow/engine/HPC adapter | preflight, execution transport, native job state and result handoff |

## 7. Solvation and transition-state growth path

### Explicit solvent

A packing task requires component molecule Artifacts, molecule counts/fractions, target density or explicit box, insertion regions, tolerance, PBC, random seed and output contract. All are supplied or policy-authorized. QC checks molecule/atom counts, identity/topology, minimum distances, cell/PBC and hashes. Packmol output is only an initial packing; if required, add distinct minimization/equilibration tasks with approved force field/method, ensemble and separate equilibration/sampling QC.

### Implicit solvation

Use an engine/version-specific plugin. Solvent, dielectric, cavity parameters, boundary conditions and energy terms are sourced MethodPlan fields. Compare matched systems under an explicit thermodynamic cycle; record sensitivity. Do not infer continuum settings from a solvent label or import example values.

### NEB / Dimer / TS

Before path generation require exact, accepted endpoint structures, SHA, matched method/cell/constraints and atom correspondence. Path construction creates reviewable initial images only. NEB then needs an engine writer/adapter, image-level output parser and convergence/path QC. Dimer is a separate task family. A converged path or dimer search is not automatically a validated TS: saddle/frequency check and meaningful reaction-coordinate mode are separate evidence.

Lower-level references:
- CP2K BAND: https://manual.cp2k.org/trunk/CP2K_INPUT/MOTION/BAND.html
- CP2K SCCS: https://manual.cp2k.org/cp2k-2026_2-branch/CP2K_INPUT/FORCE_EVAL/DFT/SCCS.html
- ASE NEB: https://docs.ase-lib.org/ase/neb.html
- ASE Dimer: https://docs.ase-lib.org/ase/dimer.html

These references document lower-level software functionality only; they do not establish that this Pipeline currently supports those task families.

## 8. Smallest next usable development closure

Implement a single vertical slice before broad scientific feature work:

1. Compile one ScientificIntent from a frozen, source-hashed input/Manifest, retaining field locators and A/B/C decision records.
2. Produce one ResearchPlan work package and minimum missing-question diagnostics.
3. Reuse an already supplied and validated structure Artifact; no new topology generation in the first closure.
4. Require every mandatory CP2K MethodPlan value from original method source or an approved protocol; verify exact executable/data file/version/license. No guessed defaults.
5. Create one ExecutionPlan node for existing `cp2k.geo_opt`.
6. Bind a task-specific QCPlan separating file completeness, normal termination, geometry convergence, structural plausibility, scientific validity and acceptance.
7. Deterministically freeze to existing CalculationPlan, run existing WorkflowController in Mock first, and use Data_analysis Artifact/Evidence handoff.
8. Add new structure plugins and operations only after this narrow chain passes.

## 9. Design-round non-goals

This PR does not implement molecule/conformer, surface, solvent, NEB, Dimer, TS, AIMD algorithms, a resource predictor or new real HPC adapters. It does not modify CalculationPlan, WorkflowStore, ProjectLifecycle, WorkflowController, Data_analysis or runtime adapters. It does not change `project_profile.json`, resolve CORR WP1 blockers, edit main or alter PR #1–#5.
