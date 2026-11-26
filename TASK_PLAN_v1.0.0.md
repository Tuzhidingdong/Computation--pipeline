# User Task Plan — coordination-dft-publication-pipeline-v1.0.0

> The user owns this document. The implementation agent and all workers must preserve the objective, scientific scope, constraints, and acceptance criteria. Execution progress belongs in the sibling `STATUS.md`. This Task Plan is the governing development baseline; progress reports must not silently redefine it.
>
> **Document status:** Proposed implementation baseline for user-directed development  
> **Project:** coordination-dft-publication-pipeline  
> **Target repository:** `Tuzhidingdong/Computation--pipeline`  
> **Visibility:** Public source repository  
> **Version:** v1.0.0  
> **Primary reusable Skill:** `coordination-dft-publication-pipeline`  
> **Initial validation project:** CO electroreduction ketene thermodynamic selectivity, frozen scientific protocol v4.1  
> **Upstream Skills:** `chem-scitoolkit`, `BeiLong_HPC`, `UCAS_hpc`, and `Data_analysis`  
> **Primary control environment:** User's existing Antigravity / Windows environment; exact OS, Python, and installed tool versions must be detected rather than assumed  
> **Compute backend:** User-configured HPC systems through the existing HPC Skills  
> **Default orchestration:** One coordinator, deterministic scripts, bounded HPC submission, resumable DAG  
> **Default LLM role:** Orchestration and evidence-grounded writing only; no LLM-generated numerical results or scientific parameter changes  
> **Execution tracking:** Sibling `STATUS.md`

## 1. Objective

Develop an independent, reusable scientific-computing orchestration Skill named `coordination-dft-publication-pipeline`.

The Skill must turn a user-approved atomistic model and a user-defined, scientifically bounded DFT protocol into a reproducible computational workflow that can:

1. Build and validate candidate molecular/cluster/support models.
2. Present a compact, inspectable model-review package to the user.
3. Freeze the user-approved model by content hash.
4. Generate version-correct CP2K inputs and execute calculations through the user's existing HPC Skills.
5. Control a multi-stage calculation workflow with strict gates, resumability, and failure isolation.
6. Perform deterministic energy, vibrational, charge, PDOS, and thermodynamic analysis.
7. Generate publication-quality figures together with transferable numerical data and scripts that regenerate those figures.
8. Generate an article-ready English Computational Details section and Results and Discussion report using only verified calculation outputs.
9. Package the source inputs, calculation provenance, validated data, figures, scripts, tables, and reports for independent review and reuse.

The system must be general-purpose. The initial CO-reduction project is a validation project and must not become hardcoded domain knowledge, fixed chemistry, or hidden production behavior in the reusable Skill.

### Core principle A — one intentional human review gate

The normal workflow has one required user interaction: review and approve the proposed atomistic models before production DFT calculations begin.

The review package must make the model assumptions, chemical topology, geometry, formula, charge, valence-electron count, spin-parity constraints, and candidate differences inspectable. After approval, the model files are immutable inputs to the workflow. The system must not silently replace or modify the approved starting models.

After model approval, all routine scheduling, job monitoring, parsing, numerical analysis, plotting, report generation, and quality-control steps must run automatically when their gates pass.

The system must not repeatedly ask the user questions that are already answered by the project specification or stored configuration. When a genuine scientific ambiguity or failed gate cannot be resolved within the authorized protocol, stop the affected branch and report a precise blocker in `STATUS.md` and the run report. Do not invent a resolution merely to continue.

### Core principle B — deterministic scientific execution

Scientific calculations and numerical transformations must be performed by versioned scripts and validated configuration, not by free-form LLM reasoning.

The LLM may explain, coordinate, summarize, and write prose from validated results. It must not:

- Invent structures, coordinates, energies, frequencies, charges, PDOS values, or uncertainty estimates.
- Change a functional, basis set, pseudopotential, spin multiplicity, cutoff, convergence threshold, or scientific scope without explicit authorization.
- Treat a successful process exit code as proof of a successful scientific calculation.
- Convert a thermodynamic result into a kinetic barrier or product Faradaic efficiency.
- Hide missing or failed calculations in a polished report.

### Core principle C — science/configuration separation

The reusable Skill must contain generic workflow logic, schemas, reusable software interfaces, and generic validation rules. Project-specific chemistry, atom counts, reaction equations, DFT values, and report content belong in a separate project configuration and project workspace.

The initial v4.1 validation configuration may be stored in a clearly separated `validation_projects/` or external project directory. It must not be imported as a default chemistry profile by the reusable Skill.

### Core principle D — no invisible worker orchestration

The default implementation and execution path uses one coordinator and deterministic scripts. Do not silently spawn additional LLM agents/workers or switch models. If a development task genuinely requires an additional LLM worker, disclose the proposed role, model, project, and expected deliverable before starting it and obtain the user's authorization.

### Core principle E — provenance and reproducibility

Every result must be traceable to:

- The exact approved input structure and its SHA256.
- The project configuration and schema version.
- The exact CP2K input file and pseudopotential/basis files used.
- The CP2K version and execution environment.
- HPC backend, job ID, resource request, and execution record.
- All upstream task IDs and output hashes.
- The analysis script, parameters, and software versions.
- The source data used to generate each figure and report statement.

A figure without transferable source data and a reproducible plotting script is not a complete deliverable.

## 2. Current state

### 2.1 Existing Skills to integrate

The user has identified four existing public Skill repositories:

- `Tuzhidingdong/chem-scitoolkit`
- `Tuzhidingdong/BeiLong_HPC`
- `Tuzhidingdong/UCAS_hpc`
- `Tuzhidingdong/Data_analysis`

Their intended roles are:

| Existing Skill | Intended responsibility in this project | Integration rule |
|---|---|---|
| `chem-scitoolkit` | Chemistry/DFT utilities, CP2K-related tooling, charge/PDOS processing, scientific visualization | Reuse validated functions and scripts; add narrow adapters or missing functions in the new repository. Do not assume its generic defaults match finite non-periodic cluster calculations. |
| `BeiLong_HPC` | Remote execution on the configured BeiLong/BSCC-A system | Use its established connection, Slurm, transfer, monitoring, and job-recording workflow where supported. Do not duplicate its SSH/Slurm implementation. |
| `UCAS_hpc` | Remote execution on the configured UCAS HPC system | Use its established connection, Slurm, transfer, monitoring, and job-recording workflow where supported. Do not duplicate its SSH/Slurm implementation. |
| `Data_analysis` | File inventory, hashes, data provenance, structured result handling, reports, and reusable analysis utilities | Reuse validated provenance and data-management components. Verify actual CP2K support before relying on it. |

The implementation agent must audit the current repository versions, `SKILL.md` files, scripts, configuration interfaces, tests, dependencies, supported Python versions, execution assumptions, and licenses before designing adapters.

Do not rely on the role descriptions above as proof that a particular function is implemented or production-ready. The audit must classify each relevant capability as `REUSE_AS_IS`, `REUSE_WITH_ADAPTER`, `IMPLEMENT_IN_NEW_REPO`, `NOT_AVAILABLE`, or `NOT_VALIDATED` and cite its repository path and test evidence.

### 2.2 Integration boundary

The four existing Skills are upstream dependencies and remain independent projects.

The new project must:

- Treat their repositories as read-only during the initial development and integration work.
- Not refactor, rename, replace, or silently patch their generic Skills.
- Avoid copying large amounts of source code from them.
- Prefer documented CLI/API/function interfaces and small compatibility adapters.
- Record the exact source revision or release used for each integration.
- Detect incompatible or missing functionality and report it instead of pretending the integration succeeded.
- Keep credentials, private SSH keys, host-specific paths, account names, and tokens outside the public repository.

Any proposed modification to an upstream Skill must be reported separately and must not be implemented without explicit user authorization.

### 2.3 Initial validation project: frozen v4.1 scientific protocol

The first end-to-end validation target is the user's frozen protocol:

**Project question:** Thermodynamic selectivity bifurcation in CO electroreduction toward ketene (`H2CCO`) by comparing Cu-20 and SnCu-20 model environments.

**Comparison:**

- Cu-20: 70-atom support + Cu13 cluster = 83 atoms; neutral model; 417 explicit valence electrons.
- SnCu-20: 71-atom support + Cu13 cluster = 84 atoms; neutral model; 426 explicit valence electrons.
- The support comparison is defined as the change from the Cu-based polyphenol coordination environment to the Sn(IV)-containing, oxygen-coordinated, charge-compensated polyphenol environment. It is not a single-element-only intervention.
- The finite support motifs are representative local coordination models. They must not be described as a complete tannic-acid polymer network or a bulk SnOx phase unless the actual atom connectivity supports that description.
- No Cu-Sn alloying is intended in the model.

**Reaction scope:**

- Shared adsorbed intermediate: `*HCCO`.
- C-terminal protonation branch: `*HCCO + H+ + e- -> *H2CCO`.
- O-terminal protonation branch: `*HCCO + H+ + e- -> *HCCOH`.
- `ΔΔG = ΔG1 - ΔG2` compares the two adsorbed-state branches.
- Ketene desorption, `*H2CCO -> H2CCO(g) + *`, is evaluated separately.
- The CHE comparison is thermodynamic, not a transition-state or kinetic-barrier calculation.
- `ΔG1 = G(*H2CCO) - G(*HCCO) - 1/2 G(H2)`.
- `ΔG2 = G(*HCCOH) - G(*HCCO) - 1/2 G(H2)`.
- `ΔΔG = ΔG1 - ΔG2 = G(*H2CCO) - G(*HCCOH)` when the two endpoints share the same support, atom balance, and reference state; the common potential/proton reference terms cancel in this relative difference.
- `ΔG_des = G(*) + G(H2CCO(g)) - G(*H2CCO)` is evaluated independently.
- No NEB, transition-state search, desorbed-ketene alkaline hydrolysis, acetate Faradaic-efficiency prediction, or microkinetic claim is authorized by the initial protocol.

**Important model-construction requirements:**

- The support must be represented by an explicit atom/bond/connectivity graph and explicit donor-atom assignments. A molecular formula alone is insufficient to define a unique chelation topology or three-dimensional structure.
- Do not call the four-gallate local motif a depside/ester-linked tannic-acid structure unless the corresponding ester bonds actually exist in the atom graph and the formula/electron count is recalculated consistently.
- Describe the Sn-containing support as an Sn(IV)-containing oxygen-coordinated polyphenol environment unless a distinct oxide phase is explicitly present in the atomistic model.
- Preserve charge neutrality, exact atom counts, electron counts, and explicit spin-parity checks.

**Exact v4.1 model compositions to be represented in the project configuration:**

| | Cu-20 | SnCu-20 |
|---|---|---|
| Support motif | `[Cu2(C7H5O5)4]^0` | `[CuSn(C7H5O5)2(C7H4O5)2(H2O)]^0` |
| Support atoms | 70 | 71 |
| Complete atomistic model | `Cu15C28H20O20` (including Cu13) | `Cu14SnC28H20O21` (including Cu13) |
| Total atoms | 83 | 84 |
| Explicit valence electrons | 417 | 426 |
| Total charge | 0 | 0 |

The formulas above must be independently recalculated from the actual atom graph; the manifest must avoid counting the Cu13 cluster twice when recording full-model composition.

**Frozen computational settings to be represented in the project configuration:**

- CP2K Quickstep / GPW.
- PBE + DFT-D3(BJ).
- Cu: GTH-PBE-q11 with matching DZVP-MOLOPT-SR-GTH-q11; Sn: GTH-PBE-q14 with matching DZVP-MOLOPT-SR-GTH-q14; C/O/H: matching q4/q6/q1 GTH pseudopotentials and MOLOPT basis sets.
- 500 Ry / 60 Ry cutoffs.
- Spin-polarized UKS and 300 K Fermi-Dirac smearing.
- Geometry optimization target: maximum force about 0.01 eV/Å; the exact CP2K force unit and conversion must be checked in the parser.
- SCF threshold 1e-6 Ha for optimization/ordinary single points and 1e-8 Ha for local-Hessian force evaluations, subject to executable/version validation.
- Finite non-periodic cubic cells, with `PERIODIC NONE` consistently declared for the cell and Poisson solver, the Martyna-Tuckerman solver, and coordinate centering (`CENTER_COORDINATES`) as configured for the CP2K version.
- 30 Å production cell, checked against 34 Å. The boundary density target is below 1e-6 e/Bohr^3 and the total-energy difference must meet the explicit v4.1 tolerance (the run manifest must record the exact numerical threshold used, not the shorthand range “1–2 meV”).
- ASE finite-displacement local adsorbate Hessian using ±0.01 Å displacements, with the support and Cu13 frozen for the local vibration calculation.
- CHE at 298.15 K and U = 0 V vs. RHE for the specified branch comparison.
- SCCS dielectric sensitivity using ε = 78.4 and TZV2P basis sensitivity on the prescribed key states.

**Frozen v4.1 task quantities to encode explicitly:**

- WP1: pre-screen the v4.1-configured set of 15 support/cluster docking orientations; retain 3–4 structurally distinct candidates for DFT relaxation for each catalyst. The manifest must explicitly state whether “15 orientations” applies per catalyst or across both systems before calculating the task count; do not infer this from prose. MACE is a geometry pre-screen only, with the configured `fmax < 0.05 eV/Å`, and cannot be the sole basis for discarding a chemically distinct topology.
- WP1 spin candidates: isolated Cu13 M=2/4/6; Cu-20 support M=1/3; SnCu-20 support M=2; complete Cu-20 M=2/4; complete SnCu-20 M=1/3 (M=5 only when the configured diagnostic condition requires it).
- WP2: one representative SnCu-20 model checked in 30 Å and 34 Å cells, plus matched-grid total/fragment single-point calculations for each system.
- WP3: three `*HCCO` candidates per catalyst; optimize both protonation products per catalyst; gas-phase H2 and H2CCO references.
- WP4: six adsorbed-state local Hessians. For the stated adsorbate atom counts (4, 5, and 5 per catalyst), central finite differences require `6N + 1` force evaluations per state, giving 174 adsorbate force evaluations in total. Generate the count from the actual selected atom indices. Also calculate the configured gas-phase vibrational references.
- WP5: six SCCS single points and four TZV2P single points, plus at most the configured optional alternative local Sn coordination model.

The executor must calculate exact task counts from the manifest and report any deviation from these values before production submission.
The exact CP2K keyword spelling and supported options must be verified against the actual CP2K executable/version installed on the selected HPC system. A template that merely looks plausible is not acceptable.

### 2.4 Known planning checks to resolve before production

The v4.1 description contains workload counts that must be reconciled in a machine-readable task manifest before submission. In particular, the explicitly listed isolated-fragment spin candidates (Cu13 M=2/4/6, Cu-20 support M=1/3, and SnCu-20 support M=2) enumerate six candidate single-point checks, whereas one WP1 summary line reports four fragment single points. The implementation must preserve the stated spin candidates and report the reconciled count; it must not silently omit candidates to match an approximate total.

The task manifest must similarly derive all geometry optimizations, spin comparisons, finite-displacement force calls, gas-phase calculations, SCCS single points, and TZV2P single points directly from explicit task definitions. Do not trust a hand-written aggregate count if the underlying task list disagrees.

### 2.5 Development strategy

Development must proceed in the following order:

1. Bootstrap the independent repository and record the existing Skills audit.
2. Define the generic project manifest, schemas, task model, status model, and execution contracts.
3. Build the model-construction and model-review gate before any production DFT work.
4. Implement deterministic CP2K input generation, parsing, and HPC adapters.
5. Validate Stage 1 ground-state calculations and resource behavior.
6. Implement Stage 2 adsorbate, local vibration, CHE, and sensitivity workflows.
7. Implement analysis, transferable visualization data, publication figures, and manuscript reports.
8. Validate full restart/recovery and package the final deliverables.

Do not start by writing the manuscript or polishing figures. Prove the model and calculation execution path first.

## 3. Required outcome

Deliver an independently usable Skill plus a deterministic Python workflow engine that can run the initial validation project end-to-end after the user approves the model package.

### 3.1 Reusable Skill package and installation contract

Create a standard, independently installable Skill structure containing at least:

- `SKILL.md` as the concise entry point and workflow contract.
- `references/` for stage rules, schemas, supported interfaces, scientific guardrails, and troubleshooting.
- `scripts/` or a separately packaged Python module for deterministic orchestration and analysis.
- `schemas/` for project manifests, model manifests, job records, result manifests, approvals, and report metadata.
- `templates/` for generic configuration and publication report templates.
- `tests/` for unit, integration, parser, workflow, and recovery tests.
- `examples/` for small generic examples that do not encode the initial project's chemistry as production behavior.
- `README.md` with installation, invocation, configuration, and supported workflow documentation.
- `STATUS.md` for execution progress.

The Skill must be callable through a documented entry point or CLI. The implementation must not depend on undocumented Antigravity UI behavior or hidden cross-Skill state.

### 3.2 Generic project manifest and schema

Define a versioned `project.yaml` or equivalent manifest that declares the user-specific project without changing the reusable Skill. It must support at least:

- Project ID and description.
- Scientific question and explicitly permitted conclusions.
- Model files and their expected hashes.
- Chemical composition, atom count, net charge, valence-electron count, spin candidates, and model identity.
- Reaction states and balanced reaction equations.
- DFT method, pseudopotentials, basis sets, cutoff values, SCF settings, geometry thresholds, cell/Poisson settings, temperature, and CHE references.
- Stage and work-package definitions.
- Task dependencies and expected output types.
- HPC backend alias, remote work directory, queue/partition/resource profile references, and file-transfer settings. Secret credentials must never be stored in the manifest.
- Retry limits and retryable failure classes.
- Numerical and structural QC thresholds.
- Analysis definitions and figure specifications.
- Report templates and output paths.
- Software/version constraints.

The schema must reject unknown or contradictory critical settings rather than silently ignore them. Defaults must be explicit and versioned. A changed configuration must invalidate only the calculation stages that depend on the changed fields.

Project-specific reaction states, formulas, atom counts, and scientific assumptions must remain in the project configuration, not in the generic Skill's code paths or default templates.

### 3.3 Model construction and validation engine

Implement a model builder or a clearly defined adapter layer using appropriate chemistry/structure libraries (for example ASE, RDKit, and narrowly scoped geometry utilities). Select libraries only after checking actual capability, version compatibility, and licensing.

The model builder must accept explicit chemical graph/topology and coordination instructions. It must not infer a unique chemically meaningful structure from a formula alone.

Required functions:

1. Read or construct molecular fragments and metal clusters.
2. Preserve explicit atom identity, element, formal charge where defined, bond graph, donor atoms, and fragment membership.
3. Build candidate support conformations and metal/cluster docking orientations within the configured search limits.
4. Produce structurally distinct candidates using geometry/topology criteria, not only numerical energy ranking.
5. Use MACE or another ML potential only when its species and chemistry coverage is documented. ML potentials may pre-screen plausible geometries but must not be the sole basis for deleting chemically distinct topologies or claiming DFT accuracy.
6. Apply cheap geometry checks before any CP2K task: atom overlap, bond plausibility, coordination distances, fragment integrity, charge, formula, and atom-count consistency.
7. Calculate explicit valence-electron counts from the exact pseudopotential valence definitions selected in the project configuration.
8. Validate electron parity against allowed spin multiplicities.
9. Produce a machine-readable model manifest and a human-readable validation report.
10. Preserve every candidate and its provenance; do not overwrite candidate coordinates during optimization.

For the initial v4.1 validation project, the model-generation stage must preserve the intended 70/71-atom supports, identical Cu13 cluster composition, neutral total models, and stated Cu/Sn formal coordination assumptions. It must also expose the actual bond graph and donor-atom assignments so that the user can inspect whether the proposed local motif corresponds to the stated chemistry.

#### Model review package

Generate one review package containing:

- Cu-20 and SnCu-20 candidate structures in XYZ and extended XYZ.
- A rotatable offline HTML 3D preview where feasible.
- Static white-background images with overview and interface close-ups.
- Candidate docking-orientation comparisons.
- Explicit atom labels, metal labels, fragment coloring, and key coordination distances.
- Chemical formula, atom count, charge, valence-electron count, spin candidates, donor-atom list, and topology summary.
- Model validation results and all assumptions or unresolved warnings.
- A `model_review_manifest.json` containing candidate IDs and SHA256 hashes.

The review package must clearly distinguish:

- Chemical topology decisions.
- Initial geometric guesses.
- ML-pre-screen scores, if used.
- DFT-optimized structures, which do not exist yet at this gate.

#### Single approval and model lock

The user must be able to approve one candidate model for each catalyst through a simple, explicit approval artifact or supported UI action. The approval must bind to exact candidate IDs and SHA256 hashes.

After approval:

- Set model state to `APPROVED_LOCKED`.
- Store the approval record and hashes.
- Refuse to start production DFT tasks if any approved file changes.
- Do not silently regenerate, substitute, or edit an approved starting structure.
- Use new derived files for every subsequent optimization.

No additional user approval is required for routine downstream stages when the frozen gates pass. If a later calculation reveals a genuine structural invalidity, stop and report a blocker rather than silently changing the model.

### 3.4 Workflow DAG, task identity, and state machine

Implement a deterministic workflow engine. The Python engine, not the Skill prompt, is authoritative for task states, dependencies, idempotency, retry policy, and gate decisions.

Every task must have:

- Stable task ID.
- Work-package/stage ID.
- Parent dependency IDs.
- Input artifact paths and SHA256 hashes.
- Exact configuration subset and configuration hash.
- Executable/tool version.
- Expected output contract.
- Execution backend and job identity.
- Attempt number and retry history.
- State and timestamps.
- Exit/termination status.
- Scientific QC result.
- Output manifest and output hashes.
- Failure classification and diagnostic references where applicable.

Required task states should include at least:

`PENDING`, `READY`, `SUBMITTED`, `QUEUED`, `RUNNING`, `POSTPROCESSING`, `QC_PASSED`, `COMPLETED`, `RETRY_WAIT`, `BLOCKED`, `FAILED_PERMANENT`, `CANCELLED`, and `INTERRUPTED_RECOVERY`.

The engine must distinguish scheduler completion from scientific success. A job is not `COMPLETED` until required parsing and QC pass.

#### Idempotency and resume

- A task with unchanged inputs, configuration, executable, and valid output hashes must be reusable without rerunning.
- A changed upstream input must invalidate dependent tasks only.
- Partial finite-displacement Hessian jobs must resume only missing or invalid displacement calculations.
- A failed plotting/reporting task must not trigger recalculation of valid DFT energies.
- A failed DFT task must not erase successful independent tasks.
- Atomic writes and content hashes must prevent partially written files from being mistaken for valid outputs.

#### Bounded scheduling

The default behavior is one coordinator and a bounded number of HPC jobs. Parallelism is a resource-control setting, not a requirement. Do not create duplicate concurrent submissions of the same task. Each task must have a submission lock or equivalent lease.

### 3.5 CP2K input generation and execution engine

Implement a project-configured CP2K input generator and validator that supports finite non-periodic molecular/cluster systems. Do not assume a generic periodic CIF builder is suitable.

Required capabilities:

- Generate geometry optimization, static single-point, force evaluation, and required analysis inputs.
- Generate explicit `CELL` and `POISSON` settings for the selected finite-system method.
- Verify exact CP2K keyword support against the executable version before production runs.
- Resolve and verify pseudopotential and basis-set files by content and exact element/valence mapping.
- Validate charge, UKS, multiplicity, SCF method, smearing, cutoffs, dispersion, and convergence settings.
- Keep optimization and analysis settings separated, with explicit inheritance.
- Record the fully expanded input file as an immutable job artifact.
- Support restart wavefunctions only when their provenance and compatibility are validated.
- Parse output for normal termination, SCF convergence, geometry convergence, warnings, final coordinates, total energy, force metrics, and relevant electronic properties.
- Fail closed on missing energy, unsupported keywords, non-converged SCF, geometry convergence failure, or incomplete output.

For the initial v4.1 validation, provide validated support for the configured PBE-D3(BJ), GTH-q11 Cu, GTH-q14 Sn, matching MOLOPT basis sets, 500/60 Ry cutoffs, UKS/Fermi-Dirac smearing, finite `PERIODIC NONE` cell and Poisson settings, and Martyna-Tuckerman solver. These are project-profile values, not universal defaults.

The generator must not silently substitute a pseudopotential, basis set, functional, dispersion scheme, SCF algorithm, or cutoff when a requested file or keyword is unavailable.

### 3.6 HPC adapter layer

Integrate `UCAS_hpc` and `BeiLong_HPC` through thin adapters. The new project must not rebuild their SSH, Slurm, transfer, or remote-monitoring implementations unless an audited interface is demonstrably unavailable.

Required abstract operations:

- Inspect configured backend and software environment.
- Verify remote work directory and storage capacity.
- Stage immutable input artifacts.
- Submit a job and return a stable remote job ID.
- Query queue/running/completed/failed state.
- Retrieve stdout, stderr, CP2K output, restart data, and output artifacts.
- Verify transferred file sizes and SHA256 hashes.
- Cancel a job when explicitly required by the workflow.
- Record node/partition/resource usage when the backend exposes it.

Routing rules:

1. Use only backends whose connection, CP2K executable, required data files, and job interface have passed environment inspection.
2. Prefer the backend selected by the user's stored configuration or an auditable resource-selection rule.
3. Do not submit the same calculation to both HPC systems for speculative duplication.
4. A failover may occur only after verifying the original job is no longer active and the input/output state is reconciled.
5. Do not invent queue time, runtime, memory use, or cost estimates. Learn resource requirements from actual job records.
6. Respect the user's existing HPC-specific permissions and safety controls.

Remote hostnames, usernames, paths containing personal information, SSH keys, tokens, and passwords must not be committed to the public repository or printed into reports.

### 3.7 Stage-gated scientific workflow

Implement stages as explicit dependency graphs. The v4.1 validation profile supplies the first concrete instance.

#### Stage 0 — environment and project preflight

- Audit selected Skills and their exact revisions.
- Validate project configuration and schema.
- Verify model inputs and pseudopotential/basis file availability.
- Inspect CP2K version and required feature support on candidate HPC backends.
- Verify remote transfer and workspace behavior.
- Generate a dry-run task graph and exact task-count report.
- No production DFT submission is allowed before model approval.

#### Model gate — user review

- Produce the model review package described in 3.3.
- Wait for the explicit approval record.
- Verify candidate hashes before releasing Stage 1.
- This is the single planned user review gate.

#### Stage 1 — ground-state model and electronic-structure gate

**WP1: support/cluster construction and spin validation**

- Validate isolated fragment electron counts and spin candidates.
- Generate the configured finite set of docking-orientation candidates.
- Use ML pre-screening only within its documented validity range; retain chemically distinct candidates.
- DFT-relax the selected 3–4 structurally distinct candidates per catalyst according to the frozen profile.
- Compare configured full-model multiplicities and retain the lowest valid state only after checking convergence and structure consistency.
- Save all candidate energies and optimized geometries, not only the selected minimum.
- Derive task counts from the manifest, including the isolated-fragment spin-count reconciliation noted in 2.4.

**WP2: non-periodic cell and ground-state electronic validation**

- Perform the configured 30 Å versus 34 Å static single-point check on the representative model.
- Check electron-density decay at the box boundary.
- Verify the configured energy-difference tolerance.
- Generate density, electrostatic-potential, and PDOS artifacts required by later analysis.
- Perform frozen-geometry, same-grid fragment calculations needed for charge-density differences and charge analysis.
- Validate actual cube grid dimensions, origin, voxel spacing, coordinate frame, cell, and basis consistency before subtracting densities.

**Stage 1 release gate**

Stage 2 may start only when all required conditions pass:

- Approved model hashes match the manifest.
- Both complete models have valid, converged ground-state structures.
- Configured spin candidates have been compared and the selected states are documented.
- CP2K jobs terminated normally and scientific parsing/QC passed.
- The 30/34 Å MT check meets the frozen profile's density-tail and energy criteria.
- Required electronic-structure and fragment-reference data exist and pass integrity checks.

If a criterion fails, the engine must set the relevant branch to `BLOCKED` or `FAILED_PERMANENT` and produce a diagnostic. It must not automatically relax the threshold or switch scientific methods.

#### Stage 2 — adsorbate, thermodynamic, and sensitivity calculations

**WP3: common intermediate and protonation products**

- Build and screen the configured `*HCCO` adsorption candidates.
- Include representative top and cluster-edge adsorption geometries in the finite candidate set unless the actual approved model topology makes one site type inapplicable; record the reason.
- DFT-optimize the configured candidate structures and select valid minima using the same objective criteria for both catalysts.
- Build and optimize `*H2CCO` and `*HCCOH` branches with consistent atom mapping and stoichiometry.
- Optimize/reference gas-phase H2 and ketene according to the project profile.
- Save all candidate geometries, energies, and selection decisions.

**WP4: local Hessian, thermodynamic corrections, and CHE**

- Use ASE finite displacements with the configured ±0.01 Å step.
- Displace only the designated adsorbate atoms; freeze the support and Cu13 cluster for the local adsorbate Hessian.
- Use CP2K force calculations at the configured high SCF threshold.
- Validate that the equilibrium reference force and all displacement calculations correspond to the same frozen environment and atom ordering.
- Verify the expected central-difference task count from the actual adsorbate atom counts; do not hardcode the number without checking the structure.
- Store each displacement input, force output, parsed force array, and checksum.
- Calculate local vibrational frequencies, mode vectors, ZPE, and vibrational entropy corrections with an explicit statement of the frozen-support approximation.
- Calculate gas-phase reference vibrational corrections as configured.
- Calculate `ΔG1`, `ΔG2`, `ΔΔG`, and `ΔG_des` from a single versioned thermodynamic implementation.
- Keep adsorbed-state protonation thermodynamics separate from ketene desorption.
- Report that local Hessian mode checks apply to the adsorbate subspace, not the full catalyst Hessian.

**WP5: sensitivity checks**

- Run the configured SCCS calculations at ε = 78.4 for the specified matched states.
- Run the configured TZV2P basis-set single points for the specified key states.
- Run an alternative local Sn coordination structure only when authorized by the project configuration; keep it as a bounded sensitivity check, not an invitation to expand the model indefinitely.
- Compare changes in `ΔΔG` and the relative trends, preserving all raw results.

**Stage 2 acceptance gate**

- Every required adsorption state has a valid optimized structure and energy.
- Every required finite-displacement force task is present, converged, parsed, and hash-verified.
- Local vibrational modes satisfy the configured stability criteria, with any imaginary mode explicitly reported rather than deleted.
- Thermodynamic equations pass unit and stoichiometric consistency tests.
- No missing energy or frequency correction is silently replaced with zero.
- Sensitivity results are present for all required states.
- The analysis dataset contains enough provenance to regenerate all reported values.

### 3.8 Numerical analysis and scientific interpretation

Implement deterministic, unit-tested routines for:

**A. Energies and thermodynamics**

- Parse and normalize CP2K energies using explicit units and references.
- Calculate ZPE and thermal/entropic corrections from the stored frequencies and declared model assumptions.
- Calculate CHE reaction free energies using the exact balanced equations in the project configuration.
- Verify atom/electron/proton bookkeeping and shared-reference cancellation.
- Calculate `ΔΔG` independently from the two branch values and cross-check it against the algebraically simplified expression where valid.
- Calculate desorption separately using the clean-site reference and gas-phase ketene reference.
- Explicitly record the vibrational-correction treatment for the clean-site state `G(*)`. The v4.1 workflow does not include a full clean-catalyst Hessian by default; do not describe `ΔG_des` as fully vibrationally corrected unless the required reference contribution was actually calculated. If a frozen-support/local-mode approximation is used, state it and its limitation.
- Preserve raw total energies and all correction terms in tables; do not report only the final ΔG.

**B. Charge density and atomic charges**

- Generate `Δρ = ρ_total - ρ_fragment1 - ρ_fragment2` only from geometrically consistent frozen fragments and the same numerical grid.
- Verify cell, grid origin, grid spacing, dimensions, basis, cutoff, pseudopotential, atom coordinates, and charge/spin choices before subtraction.
- Store cube files and a metadata sidecar describing the density sign convention and units.
- Parse and report Bader charges with atom identity mapping and a documented partitioning method.
- Report charge changes at the cluster and active-site levels without implying a unique causal mechanism from charge redistribution alone.

**C. PDOS and descriptors**

- Parse spin-resolved PDOS with atom and angular-momentum projection metadata.
- Align finite-cluster spectra using a verified vacuum-level reference from the electrostatic potential.
- Verify that the box contains a sufficiently flat vacuum-potential region; if the plateau is not established, mark vacuum alignment invalid rather than substituting the Fermi level silently.
- Define the Cu atom selection, orbital projection, integration window, occupancy convention, and d-band-centre calculation explicitly.
- Treat the d-band centre as an auxiliary finite-cluster descriptor, not an independently established causal proof.

**D. Geometry descriptors**

- Extract support Cu–O, cluster Cu–Cu, adsorption Cu–C, C–C, and C–O distances from atom-identified structures.
- Record the exact atom-pair selections used in each average.
- Avoid comparing a finite-cluster geometric coordination count directly with an ensemble-averaged EXAFS coordination number.

**E. Scientific scope checks**

The report generator must not claim:

- Transition-state barriers or reaction rates from CHE free energies.
- A complete CO-to-acetate pathway from the limited branch calculation.
- Acetate Faradaic efficiency from `ΔΔG` or ketene desorption alone.
- A simulated OH⁻ hydrolysis mechanism when that solution-phase process was not calculated.
- A unique causal chain merely because charge, PDOS, bond lengths, and ΔG change together.

### 3.9 Publication-quality visualization and transferable data

Generate the required figures from validated canonical data, not directly from hand-edited spreadsheet values.

**Figure A — model and adsorption structures**

- White background, clean orthogonal views, overview plus interface close-up.
- Consistent atom colors and labels.
- Selected key distances with reproducible atom-pair definitions.
- Provide exact source structures and rendering settings.

**Figure B — charge-density difference**

- Identical coordinate frame, cell, grid, isovalue, camera, and color mapping for Cu-20 and SnCu-20.
- For the initial v4.1 profile, use matched positive/negative isosurfaces at ±0.003 e/Å^3 and the configured sign convention.
- Include a legend and the associated Bader summary.
- Do not visually amplify or clip one model differently to create an apparent contrast.

**Figure C — CHE free-energy diagram**

- Show `*HCCO` as the shared starting state.
- Show the `*H2CCO` and `*HCCOH` adsorbed-state branches and `ΔΔG`.
- Show `*H2CCO` desorption separately, not as part of the protonation selectivity difference.
- Label the reference potential and temperature.
- Keep the plot consistent with the exact numerical table.

**Figure D — PDOS**

- Show the configured Cu 3d projection and spin channels where applicable.
- Align spectra to the verified vacuum level and label the energy axis as `E - E_vac`.
- Mark the defined d-band centre and its integration convention.
- Include a compact data table or metadata sidecar.

**Transferable visualization data**

Every plot must have:

- A machine-readable CSV/TSV/JSON data file.
- The plotting script and configuration.
- A metadata file describing units, axes, references, filters, atom selections, and source task IDs.
- An output image in the publication formats configured by the user (at minimum vector PDF/SVG and high-resolution TIFF/PNG where applicable).
- A regeneration test demonstrating that the stored source data reproduces the plot within defined visual/numerical tolerances.

For the initial project, preserve source XYZ/extxyz structures, electrostatic/density cube files, PDOS files, vibration/frequency data, Bader charge tables, raw and corrected energy tables, and all plotted series.

Use the publication typography and figure sizes defined by the project profile. Do not silently inherit incompatible defaults from a general plotting Skill.

### 3.10 Article-ready report generation

Generate at least:

1. `Computational_Details_EN.docx` and a Markdown source.
2. `Results_and_Discussion_EN.docx` and a Markdown source.
3. A structured supplementary-results workbook or equivalent set of CSV/TSV tables.
4. A run/provenance report and QC report.

**Computational Details** must be populated from the actual executed job manifest, not copied blindly from planned settings. It must report the real CP2K version, functional, dispersion, basis, pseudopotentials, cutoffs, SCF settings, cell/Poisson setup, spin treatment, optimization thresholds, frequency method, CHE references, solvent/basis sensitivity checks, and analysis methods.

**Results and Discussion** must be populated only from validated numeric results. Every numerical claim must map to a result record and source file. The report must distinguish observed trends, computed thermodynamic quantities, model limitations, and interpretation. No bracketed placeholders, guessed numbers, or unsupported causal statements are permitted in the final report.

If a critical calculation is missing or failed, the report may be generated as a clearly marked incomplete draft, but it must not be labelled submission-ready.

### 3.11 Provenance, immutable data, and recovery

Use a canonical output structure with clear separation between:

- Immutable inputs and approved models.
- Raw HPC outputs.
- Parsed intermediate results.
- Validated analysis data.
- Publication figures and their source data.
- Manuscript reports.
- Logs, provenance, and QC evidence.

For every artifact, record relative POSIX path, size, SHA256, creation task, parent task IDs, software versions, and data schema version.

The workflow must support:

- Resume after local process interruption.
- Resume after remote job interruption.
- Recovery of lost SSH connections without duplicate job submission.
- Re-download of verified remote outputs.
- Partial Hessian recovery.
- Re-running only invalidated analysis or figure stages.
- Rebuilding summaries from canonical records.

Never overwrite raw CP2K outputs or approved model inputs. Use versioned derived artifacts and atomic updates.

### 3.12 Required CLI / orchestration interface

Provide a documented CLI or equivalent stable entry points, including at least:

- `init` — initialize a project from a schema-validated template.
- `inspect` — audit Skills, software, pseudopotentials, basis files, and HPC configuration without submitting production calculations.
- `build-models` — build and validate configured candidates.
- `review-package` — create the user-facing model-review package.
- `validate-approval` — validate the user's approval artifact and hashes.
- `plan` / `dry-run` — render the DAG, exact task counts, resource requests, and outputs without submission.
- `run` — submit eligible tasks after approval and gate checks.
- `status` — report local and remote job/stage state.
- `resume` — continue from valid completed tasks.
- `retry-failed` — retry only explicitly retryable tasks within the configured finite limit.
- `validate` — run artifact, scientific, provenance, and figure QC.
- `report` — generate reports and publication artifacts from validated results.
- `export` — package source data, figures, scripts, tables, and reports.

Command names may be adjusted to fit the repository conventions, but all listed capabilities must remain available and documented.

## 4. Scope

### In scope

**A. Reusable orchestration Skill**

- Generic Skill entry point and references.
- Project configuration and schemas.
- Workflow DAG and task state machine.
- Deterministic orchestration scripts.
- Model review and approval gate.
- Provenance, checkpointing, and recovery.

**B. Model construction and DFT execution**

- Explicit chemistry/topology-aware model generation and checks.
- Candidate review package.
- CP2K input generation and output parsing.
- Spin/electron/charge validation.
- HPC adapters for the user's existing UCAS and BeiLong workflows.
- Two-stage gated execution.
- ASE finite-displacement local Hessian.

**C. Analysis and publication**

- Thermodynamic calculations and unit consistency.
- Charge-density difference and Bader analysis.
- Vacuum-aligned PDOS and auxiliary descriptors.
- Geometry descriptors.
- Publication figures, source data, and plotting scripts.
- Article-ready English method and results reports.
- Reproducibility and final quality reports.

**D. Initial validation**

- End-to-end execution of the frozen v4.1 Cu-20 / SnCu-20 workflow after model approval.
- Verification of all gates, work-package counts, task recovery, and publication deliverables.

### Out of scope

- Modifying the four existing Skills without explicit authorization.
- Rebuilding a generic HPC/SSH/Slurm framework already provided by the existing HPC Skills.
- Changing or redesigning the frozen v4.1 scientific question or broad computational scope.
- Automatically increasing model size or adding arbitrary support/cluster models.
- NEB, transition-state search, activation barriers, kinetics, microkinetics, and reaction-rate prediction for the initial project.
- Simulating solution-phase OH- hydrolysis of desorbed ketene or predicting acetate FE from this calculation alone.
- Requesting new experiments or fabricating missing experimental information.
- Automatically inferring an under-specified atom connectivity or silently inventing a chemically unique structure.
- Mandatory paid LLM/API calls.
- Letting LLMs generate or modify numerical calculation results.
- Automatic public release of a Python package, container, or manuscript.
- Pushing confidential HPC configuration, private keys, user data, raw calculation outputs, or unpublished results into the public Skill repository without explicit authorization.
- Claiming universal CP2K support or publication readiness without actual validation evidence.

## 5. Architecture / constraints

### 5.1 Separation of responsibilities

Use four clear layers:

**Layer 1 — Skill / orchestration interface**

- Reads the task plan and project manifest.
- Calls deterministic CLI/script functions.
- Presents the model-review package.
- Reports progress, blockers, and final artifacts.
- Does not calculate energies or alter numeric outputs itself.

**Layer 2 — deterministic workflow engine**

- Owns the DAG, task identity, dependencies, leases, retries, cache, checkpoints, and gates.
- Generates exact task lists and job manifests.
- Owns validation rules and state transitions.

**Layer 3 — scientific adapters and engines**

- Model-building adapter.
- CP2K input/output adapter.
- ASE vibration adapter.
- UCAS and BeiLong HPC adapters.
- chem-scitoolkit and Data_analysis adapters.
- Analysis and plotting modules.

**Layer 4 — canonical data and publication outputs**

- Immutable inputs and raw outputs.
- Parsed structured records.
- Validated analysis datasets.
- Reproducible figures and transferable data.
- Article-ready text and QC reports.

Do not build excessive agent layers or multiple competing coordinators. One Skill/coordinator controls the complete workflow.

### 5.2 Suggested repository structure

```text
coordination-dft-publication-pipeline/
├── README.md
├── SKILL.md
├── TASK_PLAN_v1.0.0.md
├── STATUS.md
├── pyproject.toml
├── config/
│   ├── project.schema.json
│   ├── model.schema.json
│   ├── task.schema.json
│   ├── approval.schema.json
│   └── report.schema.json
├── src/coordination_dft_pipeline/
│   ├── cli/
│   ├── config/
│   ├── workflow/
│   ├── models/
│   ├── cp2k/
│   ├── hpc/
│   ├── vibrations/
│   ├── analysis/
│   ├── visualization/
│   ├── reporting/
│   ├── provenance/
│   └── integrations/
├── templates/
│   ├── project.yaml
│   ├── publication_style.yaml
│   └── report_templates/
├── references/
│   ├── architecture.md
│   ├── scientific_guardrails.md
│   ├── cp2k_contract.md
│   ├── hpc_adapter_contract.md
│   ├── model_review_contract.md
│   ├── data_provenance.md
│   └── publication_output_contract.md
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── recovery/
├── validation_projects/
│   └── corr_ketene_v4.1/   # project-specific config/fixtures only; never imported as generic Skill defaults
└── docs/
    ├── installation.md
    ├── cli.md
    ├── configuration.md
    └── troubleshooting.md
```

The exact structure may be simplified when implementation evidence shows a module is unnecessary. Do not create empty abstractions merely to match this tree.

### 5.3 Runtime and resource constraints

- Detect local Python and platform at runtime; do not hardcode the user's local paths.
- Use the Python versions supported by the audited Skills and selected dependencies.
- Run CP2K production calculations on the configured HPC backend, not by accidentally falling back to the local machine.
- Use bounded HPC job submission and no duplicate task submissions.
- Use one coordinator process by default.
- Allow multiple independent HPC jobs only when the configured scheduler limits and user's resource policy permit them.
- Store large cube, trajectory, wavefunction, and raw output files on the configured project storage; do not load them all into memory.
- Use streaming parsers and incremental file hashing for large outputs where possible.
- Provide explicit disk-space checks and safe cleanup only for known regenerable temporary files.
- Never delete raw outputs or user inputs as an automatic cleanup action.

### 5.4 Security and public repository hygiene

The repository is public. Therefore:

- Commit generic code, schemas, generic templates, docs, and small synthetic tests only.
- Do not commit HPC credentials, SSH configuration, user paths, access tokens, private keys, unpublished structures/results, or raw production output unless separately authorized.
- Use environment variables or local ignored configuration for secrets.
- Provide `.gitignore` rules for local config, credentials, large calculation artifacts, and project output directories.
- Run secret scanning or an equivalent repository check before each push.
- Never include full remote command lines containing secrets in logs or progress reports.

### 5.5 Git and execution-reporting discipline

- Keep the task plan as the governing baseline.
- Maintain `STATUS.md` as the sibling execution log, with AC IDs, phase, status, latest evidence, blockers, and next action.
- Use a dedicated implementation branch for agent development; do not force-push, rewrite, or overwrite `main` or an existing branch.
- Do not merge or create a release automatically.
- Commit meaningful milestones with descriptive messages.
- Every progress report to the user must include repository, branch, commit SHA, changed files, evidence/test results, and links to the exact files or commits.
- The user must be able to inspect each pushed deliverable directly in GitHub.

## 6. Implementation phases and acceptance gates

### Phase 0 — repository bootstrap and existing-Skill audit

**Tasks**

- Create the independent public repository and initial documentation skeleton.
- Add this Task Plan, `README.md`, and `STATUS.md`.
- Audit all four existing Skill repositories and record exact revisions.
- Produce a capability/integration matrix with file paths and tests.
- Identify CP2K, ASE, MACE, Multiwfn, VESTA/VMD, and plotting availability/versions where configured.
- Identify actual HPC adapter entry points and required configuration without exposing secrets.
- Define repository license status; do not add a license without the user's choice.

**Acceptance criteria**

- AC-0.1: Repository and Skill identity are stable and documented.
- AC-0.2: All four Skills have an evidence-backed capability audit.
- AC-0.3: No upstream repository was modified.
- AC-0.4: No credentials or private configuration entered the public repository.
- AC-0.5: Integration gaps and unsupported interfaces are explicit.

### Phase 1 — contracts, schemas, and workflow skeleton

**Tasks**

- Implement versioned schemas for project, model, approval, task, job, result, figure, and report manifests.
- Implement task identity, dependency DAG, task state machine, leases, finite retry policy, and event log.
- Implement artifact hashing, atomic writes, provenance manifests, and cache invalidation.
- Implement CLI commands `init`, `inspect`, `plan`, `dry-run`, `status`, `validate`, and `resume` at least at skeleton level.
- Implement a generic project template independent of the v4.1 chemistry.
- Implement secret redaction and public-repository safeguards.

**Acceptance criteria**

- AC-1.1: Invalid or contradictory project configurations fail with actionable errors.
- AC-1.2: Dry-run produces a deterministic DAG and task list without submitting jobs.
- AC-1.3: Task IDs and cache keys are stable for unchanged inputs/configuration.
- AC-1.4: A changed upstream input invalidates only its dependent tasks.
- AC-1.5: Interrupted and partially written artifacts cannot be marked complete.
- AC-1.6: Secrets are absent from committed files and ordinary logs.

### Phase 2 — model builder, structural QC, and single review gate

**Tasks**

- Implement explicit graph/topology import and candidate model generation.
- Implement chemistry-aware charge, formula, atom, electron, valence, donor, and coordination checks.
- Implement bounded candidate geometry generation and structurally distinct candidate selection.
- Integrate ASE/RDKit/MACE only through validated interfaces.
- Generate the review package and approval artifact.
- Verify SHA256 locking and refusal to run before approval.
- Validate the initial v4.1 model manifest without placing its chemistry into generic production defaults.

**Acceptance criteria**

- AC-2.1: A model cannot pass validation from formula and atom count alone; explicit topology and donor assignments are required.
- AC-2.2: Atom count, formula, net charge, valence-electron count, parity, spin candidates, and key coordination assignments agree.
- AC-2.3: Candidate structures and assumptions are inspectable in 3D and machine-readable forms.
- AC-2.4: User approval is bound to exact file hashes.
- AC-2.5: Any post-approval change to the model hash blocks production execution.
- AC-2.6: No CP2K production job is submitted before model approval.
- AC-2.7: One review package contains the complete set of candidate structures needed for the user's single planned review.

### Phase 3 — CP2K engine, HPC adapters, and Stage 1

**Tasks**

- Implement CP2K input templates and input validation for supported finite non-periodic systems.
- Implement CP2K output parsers and scientific completion checks.
- Integrate the audited UCAS and BeiLong HPC interfaces.
- Implement job staging, submission locks, monitoring, transfer verification, and failure classification.
- Implement WP1 fragment/full-model spin validation and candidate geometry optimization.
- Reconcile actual spin-check and optimization task counts in the manifest.
- Implement WP2 30/34 Å MT, density-tail, same-grid fragment, and electronic-structure checks.
- Implement the Stage 1 gate.

**Acceptance criteria**

- AC-3.1: All generated CP2K inputs are validated against the actual selected executable version.
- AC-3.2: Unsupported pseudopotential, basis, keyword, or feature requests fail before production submission.
- AC-3.3: HPC task submission cannot create duplicate active jobs for the same task ID.
- AC-3.4: Job state is reconciled against the remote scheduler after interruptions.
- AC-3.5: CP2K scientific success requires normal termination, converged SCF/geometry, parsable outputs, and QC—not exit code alone.
- AC-3.6: Every configured spin candidate is accounted for in the run manifest and final report.
- AC-3.7: Stage 1 gate checks every configured condition and does not relax thresholds automatically.

### Phase 4 — Stage 2 adsorption, local vibration, CHE, and sensitivity

**Tasks**

- Implement adsorption candidate generation, selection, and geometry optimization.
- Implement gas-phase reference calculations.
- Implement ASE/CP2K central finite-displacement local Hessian task generation and recovery.
- Implement frequency, ZPE, and entropy processing with explicit frozen-support assumptions.
- Implement CHE equations and independent ketene desorption thermodynamics.
- Implement SCCS and basis-set sensitivity workflows.
- Implement Stage 2 task and numerical consistency gates.

**Acceptance criteria**

- AC-4.1: Adsorption-state stoichiometry and atom mapping are validated before calculations.
- AC-4.2: All displacement tasks are individually recorded and recoverable.
- AC-4.3: Expected finite-difference force-call counts are generated from actual atom selections.
- AC-4.4: Local Hessian reports clearly state that the support/cluster are frozen and that stability applies to the adsorbate subspace.
- AC-4.5: No missing vibrational contribution is silently set to zero.
- AC-4.6: `ΔG1`, `ΔG2`, `ΔΔG`, and `ΔG_des` pass independent formula/unit/stoichiometry tests.
- AC-4.7: CHE results are not labelled as activation barriers or rates.
- AC-4.8: All required sensitivity tasks are complete and hash-verified before final analysis.

### Phase 5 — charge, PDOS, structure, and publication visualization

**Tasks**

- Implement identical-grid density-difference validation and calculation.
- Implement Bader charge parsing with atom identity mapping.
- Implement vacuum-potential plateau detection and PDOS alignment.
- Implement declared d-band-centre integration and spin-channel handling.
- Implement geometry descriptor extraction.
- Generate Figures A–D and transferable data packages.
- Implement figure rendering/regeneration tests and publication-style QC.

**Acceptance criteria**

- AC-5.1: Density subtraction is blocked when grid/cell/origin/coordinates/basis metadata are inconsistent.
- AC-5.2: Vacuum alignment is blocked when no defensible vacuum plateau is found.
- AC-5.3: Every charge and PDOS quantity is traceable to raw output and analysis settings.
- AC-5.4: Every figure has source data, plotting code, metadata, and a regeneration test.
- AC-5.5: Figure comparisons use the same declared plotting scales and rendering conventions.
- AC-5.6: No plotted value is manually typed into a figure independently of the canonical data table.

### Phase 6 — manuscript/report generation, integration acceptance, and delivery

**Tasks**

- Generate Computational Details from actual execution records.
- Generate Results and Discussion from validated analysis data.
- Generate supplementary tables and QC/provenance reports.
- Run a full end-to-end `resume`/recovery test and final artifact audit.
- Package the final delivery directory with immutable manifests.
- Produce a concise user-facing completion report with exact repository/branch/commit and artifact links.

**Acceptance criteria**

- AC-6.1: No placeholder values remain in documents labelled submission-ready.
- AC-6.2: Every numerical claim maps to canonical data and source task IDs.
- AC-6.3: Computational Details match actual executed settings, not intended defaults.
- AC-6.4: Results text respects the scientific scope and limitations in the project manifest.
- AC-6.5: All publication figures can be regenerated from included transferable data and scripts.
- AC-6.6: Final output manifest contains paths, sizes, hashes, versions, and QC status.
- AC-6.7: Final package includes all requested deliverables: computational method, visual results, transferable visualization data, and results analysis.
- AC-6.8: The final progress report identifies passed, failed, blocked, and not-run tasks without presenting partial work as complete.

## 7. Testing and validation

### 7.1 Unit tests

At minimum, test:

- Project and task schema validation.
- Formula parsing and atom-count validation.
- Pseudopotential valence-electron accounting.
- Charge/electron parity/spin-multiplicity consistency.
- Explicit atom mapping and donor assignment.
- Candidate geometry collision and coordination checks.
- CP2K input generation and version gating.
- CP2K output parsing for normal termination, SCF/geometry convergence, total energy, force, warnings, and missing records.
- Task identity, cache invalidation, lease expiry, and retry classification.
- HPC adapter response mapping and secret redaction.
- ASE displacement enumeration and force-array assembly.
- Unit conversions and energy reference bookkeeping.
- CHE equation and `ΔΔG` cancellation checks.
- Desorption reference bookkeeping.
- ZPE and vibrational entropy calculations.
- Density cube grid compatibility.
- Bader atom mapping.
- Vacuum plateau detection and PDOS alignment.
- d-band descriptor integration.
- Figure data extraction and regeneration.
- Report-value provenance and placeholder rejection.

### 7.2 Integration tests

Use small synthetic or non-sensitive fixtures to test:

- End-to-end project initialization and dry-run.
- Model-review package generation.
- Approval hash verification and lock rejection.
- CP2K input staging and parser flow using known fixture outputs.
- HPC adapter submission/polling/transfer behavior using a mock backend, followed by a controlled real-backend smoke test when authorized.
- Stage 1 gate pass/fail behavior.
- Adsorption task graph generation.
- Partial Hessian recovery when selected force evaluations are missing.
- Stage 2 gate pass/fail behavior.
- Density/PDOS analysis data flow.
- Figure regeneration from saved data.
- DOCX/Markdown report generation.
- Final export and hash verification.

Synthetic fixtures validate software behavior only; they do not establish scientific correctness or replace the initial real v4.1 calculation.

### 7.3 HPC and operational tests

- Verify each backend's configured software environment and CP2K feature support.
- Confirm job submission returns a valid scheduler job ID.
- Confirm queue/running/completed/failed states are reconciled correctly.
- Test lost SSH connection while a remote task continues running.
- Test controller restart without duplicate submission.
- Test interrupted file transfer and SHA256 mismatch handling.
- Test finite retry limits and permanent-failure classification.
- Test storage checks and safe handling of large cube/wavefunction files.
- Record actual wall time, peak memory where available, CPU/node allocation, and filesystem behavior.

Do not extrapolate 83–84 atom production performance from tiny smoke tests. Use the first approved Stage 1 calculations as the empirical resource benchmark.

### 7.4 Scientific acceptance for the initial v4.1 project

The actual Stage 1 and Stage 2 calculations must pass the frozen project gates. The final package must include:

- Approved starting structures and approval hashes.
- Optimized structures and their convergence evidence.
- Spin-state comparisons and selected multiplicities.
- 30 Å/34 Å MT comparison and density-tail evidence.
- Same-grid density and fragment-reference validation.
- All required adsorption geometries and energies.
- All finite-displacement force records and vibrational corrections.
- CHE and desorption energy tables with correction breakdowns.
- SCCS and TZV2P sensitivity results.
- Charge-density, Bader, PDOS, geometry, and figure-source data.
- A documented list of failures, exclusions, or unresolved modes.

A calculation that fails a gate may still produce a diagnostic report, but cannot be represented as a passed scientific result.

### 7.5 Regression and recovery tests

Maintain regression cases for:

1. Odd-electron and even-electron systems.
2. Fragment and full-system spin comparisons.
3. CP2K non-periodic MT input validation.
4. Missing basis/pseudopotential file.
5. SCF non-convergence.
6. Geometry optimization non-convergence.
7. Output truncated after scheduler completion.
8. Duplicate HPC submission prevention.
9. Lost connection and job reconciliation.
10. Changed approved model hash.
11. Missing finite-displacement force output.
12. Wrong atom order in force assembly.
13. Inconsistent density cube grids.
14. Invalid vacuum reference.
15. CHE stoichiometry/reference mismatch.
16. Missing thermal correction.
17. Figure data/script regeneration mismatch.
18. Manuscript placeholder or unsupported scientific claim detection.
19. Restart from a partially completed Stage 1.
20. Restart from a partially completed Stage 2.

## 8. Deliverables

### 8.1 Public reusable repository

- Independent repository `Tuzhidingdong/Computation--pipeline`.
- Reusable Skill `coordination-dft-publication-pipeline`.
- Installation and invocation documentation.
- Versioned project/configuration schemas.
- Generic templates.
- Clear integration documentation for the four existing Skills.
- No credentials or confidential user data.

### 8.2 Source modules and workflow engine

- Project loader and validator.
- Model graph/geometry builder and structural QC.
- Model review package generator and approval verifier.
- Workflow DAG and task-state engine.
- CP2K input generator and output parser.
- UCAS and BeiLong adapters.
- ASE local Hessian task generator and assembler.
- Thermodynamic/CHE analysis.
- Density, Bader, PDOS, and geometry analysis.
- Publication figure and data exporters.
- Manuscript/report generator.
- Provenance, cache, resume, recovery, and final package exporter.

### 8.3 Documentation and schemas

- `SKILL.md`.
- `README.md`.
- `TASK_PLAN_v1.0.0.md`.
- `STATUS.md`.
- Architecture and adapter contracts.
- Project, model, approval, task, job, result, figure, and report schemas.
- CP2K version compatibility matrix.
- HPC adapter compatibility matrix.
- Scientific guardrails and supported/not-supported capability matrix.
- CLI and troubleshooting guide.

### 8.4 Model review deliverables

For the initial v4.1 project:

- Approved-model candidate structures.
- Offline 3D preview and static images.
- Explicit connectivity and coordination records.
- Formula/atom/electron/charge/spin validation report.
- Candidate comparison report.
- Approval artifact and locked hashes.

### 8.5 Calculation and provenance deliverables

- Expanded CP2K inputs.
- Raw CP2K outputs and restart artifacts.
- Scheduler job records.
- Optimized structures and energy tables.
- Finite-displacement input/force records.
- Frequency, ZPE, and entropy tables.
- CHE and desorption thermodynamic table.
- SCCS and TZV2P sensitivity tables.
- Density, electrostatic potential, PDOS, Bader, and geometry artifacts.
- Per-task and project-level manifests with SHA256.
- Gate and failure reports.

### 8.6 Publication visualization deliverables

- Figures A–D in configured vector and high-resolution raster formats.
- Figure data CSV/TSV/JSON.
- Plotting scripts and style configuration.
- Source structures/cube/PDOS/frequency data necessary to recreate the plots.
- Figure metadata and regeneration-test report.

### 8.7 Manuscript/report deliverables

- `Computational_Details_EN.docx` and `.md`.
- `Results_and_Discussion_EN.docx` and `.md`.
- Supplementary numerical tables in XLSX and/or CSV/TSV.
- Scientific-scope and limitation statement.
- Run summary, QC report, and provenance manifest.

### 8.8 Final project delivery structure

A recommended project output layout is:

```text
<project_workspace>/
├── config/
├── model_review/
├── approved_models/
├── stage1_ground_state/
├── stage2_adsorption/
├── analysis/
│   ├── energies/
│   ├── vibrations/
│   ├── charges/
│   ├── pdos/
│   └── structures/
├── figures/
│   ├── Fig_A/
│   ├── Fig_B/
│   ├── Fig_C/
│   └── Fig_D/
├── manuscript/
├── supplementary_tables/
├── provenance/
├── reports/
└── final_delivery/
```

The exact path is configurable and must not be hardcoded to a user-specific drive letter.

## 9. Release and execution boundary

- [x] Authorized: create a public source repository and add this development Task Plan. (Repository creation is pending.)
- [x] Authorized: develop the reusable Skill and deterministic workflow engine according to this plan after the user starts the implementation agent.
- [ ] Publish a versioned package/container or announce a software release; wait for explicit user approval.
- [ ] Automatically merge implementation branches into `main`; not authorized.
- [ ] Upload private production structures, raw calculation outputs, unpublished results, or HPC configuration to the public Skill repository; not authorized unless separately approved.
- [ ] Change the frozen v4.1 science protocol, model size, DFT parameters, thresholds, or reaction scope; not authorized.

The initial model review is the only planned user approval gate for the normal calculation workflow. A failed scientific gate must block the affected stage and produce a report; it must not create a new user questionnaire or silently relax the protocol.

Before claiming implementation complete, report:

1. Repository, branch, latest commit SHA, and exact changed-file links.
2. Audit findings for all four existing Skills.
3. Implemented modules and supported interfaces.
4. Model-review package and model approval/hash status.
5. Actual CP2K version and validated input capabilities.
6. HPC backend selected and actual job records.
7. Stage 1 and Stage 2 gate results.
8. Actual task counts, including spin checks and all finite-displacement calls.
9. Runtime/resource observations from real jobs.
10. Numerical results and sensitivity checks.
11. Figure files and transferable data/scripts.
12. Computational Details and Results and Discussion documents.
13. Unit/integration/recovery test results.
14. Known limitations and unresolved blockers.
15. Proof that public repository contents contain no secrets or unauthorized production data.

A software capability may be marked implemented after code and tests pass, but the initial scientific workflow must not be called end-to-end validated or submission-ready until the real approved v4.1 workflow and publication deliverables pass their acceptance criteria.

## 10. User decisions already made

1. The new orchestration Skill is an independent public repository, not a modification or merger of the four existing Skills.
2. Its name is `coordination-dft-publication-pipeline`.
3. The initial target repository name is `Tuzhidingdong/Computation--pipeline`.
4. The four existing Skills are `chem-scitoolkit`, `BeiLong_HPC`, `UCAS_hpc`, and `Data_analysis`.
5. The four existing Skills should be reused where their actual interfaces and tests support the required work; do not reimplement their established responsibilities unnecessarily.
6. The new Skill must coordinate the full workflow from model construction/review through HPC DFT, numerical analysis, publication figures, transferable visualization data, and manuscript-ready reports.
7. The user wants the model presented for review before production DFT calculations.
8. The normal workflow must require only one planned user review gate: approval of the generated model package.
9. After model approval, routine calculations, monitoring, analysis, plotting, report generation, and quality checks should run automatically when gates pass.
10. The implementation must stop and report genuine scientific blockers rather than repeatedly bothering the user, guessing, silently changing science settings, or presenting failed work as complete.
11. The frozen CO-reduction ketene-selectivity v4.1 protocol is the first validation project, not the generic Skill's hardcoded scientific domain.
12. The initial v4.1 models contain 83 and 84 total atoms, with 70- and 71-atom supports plus the same Cu13 cluster, neutral charge, and 417/426 explicit valence electrons.
13. The support comparison is Sn(IV)-containing oxygen-coordinated polyphenol environment plus local charge compensation, not a pure single-Sn intervention.
14. Explicit atom/bond topology and donor assignments are required; a formula alone is not a structurally complete model.
15. A depside/ester-linked tannic-acid description is permitted only if those bonds exist in the actual atom graph and the formula is consistent.
16. The initial reaction scope compares the adsorbed `*H2CCO` and `*HCCOH` protonation branches from `*HCCO` and calculates ketene desorption separately.
17. CHE free energies are thermodynamic quantities; NEB, transition states, kinetics, solution hydrolysis, acetate FE, and microkinetics are outside the initial scope.
18. The existing HPC Skills remain the preferred SSH/Slurm execution backends; their live configuration and exact interfaces must be audited.
19. No HPC credentials, keys, hostnames, or private paths may be committed to the public repository.
20. Deterministic code must calculate and validate numbers; LLMs must not invent or modify scientific data.
21. Every publication figure must have transferable numerical data, plotting code, metadata, and a reproducibility check.
22. Computational Details must describe what was actually executed; Results and Discussion must use only validated results.
23. `STATUS.md` is the execution log; this Task Plan remains the objective and acceptance baseline.
24. Development progress must be pushed to a dedicated branch with repository, branch, commit SHA, and exact deliverable links reported to the user.
25. No automatic merge, package publication, release announcement, or upload of private scientific data is authorized.