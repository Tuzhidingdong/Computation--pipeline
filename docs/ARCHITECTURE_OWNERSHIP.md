# Architecture Ownership and Capability Boundaries

**Status:** Approved architecture baseline  
**Applies to:** `coordination-dft-publication-pipeline` and its four upstream Skills  
**Primary repository:** `Tuzhidingdong/Computation--pipeline`  
**Related documents:**
- [Existing Skill Capability Audit](EXISTING_SKILL_CAPABILITY_AUDIT.md)
- [Upstream Skill Gap Remediation Task](UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)
- [Governing Task Plan](../TASK_PLAN_v1.0.0.md)

## 1. Architectural decision

The system has four responsibility layers:

1. **Orchestration and scientific gates — Computation--pipeline.**
2. **Reusable chemistry/DFT tools, scientific data management, and HPC backends — the four existing Skills.**
3. **Established external scientific software — CP2K, ASE, RDKit, pymatgen, Multiwfn/Bader tools, Matplotlib, and related libraries.**
4. **Project-specific configuration and small project plugins — stored outside generic Skills and loaded by the orchestrator.**

The new repository is not a replacement for the four Skills and must not become a monolithic copy of their tools.

The governing rule is:

> Put a capability where its long-term reusable responsibility belongs. The orchestrator owns decisions about *what runs next*; specialist tools own *how a scientific operation is performed*; HPC Skills own *how a particular cluster is accessed and scheduled*; Data_analysis owns *how artifacts and derived evidence are represented and traced*.

## 2. Responsibility matrix

| Capability | Primary owner | Supporting dependency | Implementation rule |
|---|---|---|---|
| Reusable Agent Skill entry point and invocation | Computation--pipeline | Antigravity runtime | Keep the Skill concise; call deterministic scripts and documented adapters |
| Project manifest loading and validation | Computation--pipeline | JSON Schema / YAML libraries | Generic schema in this repository; chemistry and parameters in project configuration |
| Workflow DAG, dependency scheduling, and state machine | Computation--pipeline | Python workflow code | Must be deterministic, resumable, and testable |
| Stage gates and stop conditions | Computation--pipeline | Validated outputs from specialist tools | Gate rules live here; never confuse scheduler success with scientific validity |
| User model-review package and single approval gate | Computation--pipeline | ASE, RDKit, visualization tools | Present complete candidate package, collect approval, bind approval to file hashes |
| Approved model immutability | Computation--pipeline | SHA256 and filesystem operations | Reject post-approval coordinate/configuration drift |
| Project-specific molecular/support topology | Project plugin under Computation--pipeline | RDKit, ASE, optional molSimplify | Implement only the initial project's explicit atom/bond topology and generalize only after reuse is demonstrated |
| Generic CP2K input building | chem-scitoolkit | cp2k-input-tools | Add reusable finite-system capabilities upstream; do not create a second generic builder in this repository |
| CP2K input syntax/data-file validation | cp2k-input-tools | Actual CP2K executable | Use tool validation plus executable/version smoke checks; lint success is not scientific validation |
| CP2K output parsing | chem-scitoolkit | cp2k-output-tools / pymatgen | Choose one primary parser route; retain raw files and normalized output |
| Generic scientific artifact schemas, inventory, hashes, and evidence | Data_analysis | JSON Schema | Reuse its artifact, dataset, analysis-run, and evidence model |
| CP2K result registration and parse assurance | Data_analysis | chem-scitoolkit parser | Add format/reader/operation registrations; do not duplicate the full CP2K parser |
| Bader/charge analysis algorithms | Multiwfn or a validated Bader implementation, wrapped by chem-scitoolkit | CP2K cube outputs | Must use actual density partitioning; never label empirical Hirshfeld scaling as Bader |
| PDOS extraction / broadening | cp2k-output-tools or pymatgen, wrapped by chem-scitoolkit | CP2K PDOS outputs | Preserve spin channels, atom/orbital selections, units, and raw source |
| Vacuum reference and density-grid checks | chem-scitoolkit reusable analysis | CP2K cube outputs, NumPy | Implement validation primitives; project-specific region and physical reference assumptions remain in project config and must be justified |
| Generic vibrational/thermochemistry utilities | ASE plus thin chem-scitoolkit wrappers | CP2K forces or force results | Reuse ASE algorithms; pipeline creates and schedules remote force tasks |
| Remote finite-displacement task batching | Computation--pipeline | ASE, HPC Skills, CP2K | Pipeline owns the remote job graph, task identity, retries, force reassembly, and recovery |
| CHE reaction definitions and project energy bookkeeping | Project plugin under Computation--pipeline | Generic thermochemistry functions from chem-scitoolkit | Equations, atom mapping, reference states, and allowed claims are project-configured, not global defaults |
| Generic plotting primitives and style profiles | chem-scitoolkit | Matplotlib | Add configurable profiles; no project-specific values or chemistry hardcoded |
| Project figure set, plot-data map, and publication QC orchestration | Computation--pipeline | chem-scitoolkit | Pipeline gathers canonical values, calls plotters, verifies regeneration and provenance |
| Computational Details / Results and Discussion generation | Computation--pipeline | Data_analysis evidence; deterministic templates; optional LLM prose | Write only from validated run manifests and numerical evidence |
| DOCX/PDF/SI generation and cross-artifact consistency QC | Computation--pipeline | python-docx, openpyxl, rendering tools | Orchestrate output; no invented results |
| BSCC-A connection, remote paths, Slurm, transfers, job ledger | BeiLong_HPC | Windows OpenSSH / Slurm | Reuse its existing operational contract; never duplicate SSH or expose private settings |
| UCAS connection, remote paths, Slurm, transfers, job ledger | UCAS_hpc | Windows OpenSSH / Slurm | Reuse its existing operational contract; never duplicate SSH or expose private settings |
| Cross-cluster selection and adapter mapping | Computation--pipeline | Both HPC Skills | Choose backend from live preflight and capability metadata; do not store credentials |
| Canonical project task IDs and overall run manifest | Computation--pipeline | Data_analysis schemas; upstream job records | Store references and hashes; do not clone the full Slurm ledger |
| Final delivery package and user-facing report | Computation--pipeline | All upstream capabilities | Package methods, figures, transferable data, analysis, QC, and provenance |

## 3. What belongs in Computation--pipeline

The following capabilities are exclusive orchestration responsibilities:

### 3.1 Workflow controller

- Parse a versioned project manifest.
- Build a task DAG from explicit task definitions.
- Maintain task states, dependencies, leases/locks, retry limits, and idempotency keys.
- Dispatch only eligible tasks.
- Prevent duplicate active submissions for the same immutable task identity.
- Resume after local process restart or lost network connection by reconciling persisted state with upstream job records and the live scheduler.
- Distinguish infrastructure errors, software/input errors, numerical non-convergence, and scientific QC failures.
- Stop at configured gates without altering scientific parameters.

Do not implement a generic replacement for Slurm, SSH, SCP, or the existing upstream job-record systems.

### 3.2 Model approval and freeze

- Build the project-specific candidate structures through the model plugin.
- Generate static structure images plus an offline interactive preview when practical.
- Export XYZ/extxyz and machine-readable atom/bond/donor mappings.
- Display formula, atom count, charge, valence-electron count, parity, spin candidates, coordination distances, and warnings.
- Require explicit approval before any production DFT task is eligible.
- Record the exact hashes of all approved structure and model-definition files.
- Block all production tasks if any approved model file changes.

Do not create a general chemistry builder here when ASE/RDKit or an upstream specialist package already provides the required primitive.

### 3.3 Scientific gate controller

- Evaluate each project's declared gates against normalized evidence.
- Record the exact source task IDs, values, thresholds, and decision.
- Fail closed on missing, malformed, stale, or mismatched evidence.
- Never infer that a calculation passed because Slurm returned COMPLETED.
- Never increase resource requests, change multiplicities, alter convergence settings, or relax thresholds automatically unless the project explicitly defines a bounded, pre-authorized recovery policy.

### 3.4 Report assembly

- Assemble outputs from canonical analysis tables and task provenance.
- Ensure every text value and plotted value maps to a data record and source task.
- Generate submission-ready documents only when every required artifact has passed its quality gate.
- Keep partial/blocked reports clearly labelled as such.

## 4. What belongs in the existing Skills

### 4.1 chem-scitoolkit

Owns reusable scientific code:

- Configurable CP2K input generation and output interpretation.
- DFT-specific parser and calculation summaries.
- Validated charge, DOS/PDOS, density-grid, and potential analysis wrappers.
- Generic vibrational and thermochemistry functions/wrappers.
- Reusable thermodynamic utilities and plotting functions.
- Publication-style profiles that are configurable by journal/project.

It must not contain Cu-20, SnCu-20, HCCO, or any other initial-project-specific chemical rule as a default or hardcoded example in production behavior.

### 4.2 Data_analysis

Owns reusable scientific data engineering:

- Artifact inventory and immutable source preservation.
- SHA256, file metadata, format and reader registries.
- Dataset/observation/analysis-run/evidence schemas.
- Validated parser-result normalization and provenance links.
- Content-addressed cache and deterministic analysis records.

It must not implement a second CP2K engine, repeat the same scientific calculations, or write manuscript prose.

### 4.3 BeiLong_HPC and UCAS_hpc

Each owns its own cluster-specific operations:

- Authentication/connection instructions and path boundaries.
- Software/module discovery and verified executable profiles.
- Slurm submission, monitoring, reconciliation, resource records, and diagnosis.
- Selective transfer and checksum verification.
- Local job records and resource observations.

Do not merge the two repositories, centralize their credentials, normalize away their operational differences, or copy private cluster details into this public repository.

Their current core capability is considered reusable. Any upstream code change must be justified by a concrete integration blocker and submitted as a small, separate PR. The normal pipeline adapter belongs in Computation--pipeline.

## 5. External software: reuse rather than reinvent

| Software/tool | Use | Rule |
|---|---|---|
| ASE | Atomic structures, optimization wrappers, constraints, file I/O, calculator interfaces, finite-displacement vibration algorithms, thermochemistry | Use native interfaces; pipeline supplies remote scheduling and result reassembly |
| RDKit | Organic ligand graph construction, atom/bond topology, conformers, canonical molecular metadata | Do not treat it as a transition-metal coordination chemistry solver |
| molSimplify | Optional generation/reference for local metal coordination geometries | Use only if its ligand/metal handling fits; never assume it can build the complete project support topology |
| CP2K | DFT energy/force/geometry calculations | Actual executable and feature/version support are authoritative |
| cp2k-input-tools | CP2K input parse/generate/lint and data-file lint | Use to validate syntax and basis/pseudopotential data; still perform executable-level checks |
| cp2k-output-tools | CP2K output parsing and PDOS broadening/export | Prefer a single primary parser path and wrap it consistently |
| pymatgen CP2K interfaces | Alternative parser/structure/PDOS support and cross-checks | Do not implement duplicate parsing unless a required field is missing |
| Multiwfn / Bader tools | Real density partitioning and electronic-structure analysis | Validate executable version, inputs, outputs, atom mapping, and charge accounting |
| Matplotlib | Figure rendering | Reuse through chem-scitoolkit style profiles |
| VESTA / VMD | Structural and volumetric visual inspection/rendering | Use as established visualization tools; automate export only where stable |
| python-docx / openpyxl | DOCX and spreadsheet generation | Use as output libraries, not as scientific analysis engines |
| AiiDA / atomate2 / jobflow | Alternative full workflow/provenance managers | Not part of the initial implementation stack; reconsider only with a documented need |

### Third-party Skill reuse policy

Public Skill repositories may be used as reference material after checking their license, maturity, tested software versions, and actual content. The reviewed `SFETNI/Deep-Matter-Chem-Skills` repository includes CP2K, ASE, AiiDA, and DFT convergence Skills, but those are marked draft and the CP2K workflow metadata identifies CP2K 2023.2. Treat these Skills as checklists/reference, not as production-ready modules for CP2K 2025.2. Do not copy files wholesale without license review and provenance.

## 6. What must be project-specific

The initial CO-reduction validation project must live in a separated project configuration/plugin, not generic package defaults. It may define:

- The Cu-20 and SnCu-20 support atom/bond topologies and donor mappings.
- The exact Cu13 cluster and candidate docking orientations.
- Charge, valence-electron count, spin candidates, and model-specific validation.
- The HCCO, H2CCO, and HCCOH adsorption states and atom mapping.
- CHE equations, gas references, temperature, and potential reference.
- The required 30/34 Å box check and project thresholds.
- The specific six local adsorbate Hessians and selected displaced atoms.
- SCCS/TZV2P sensitivity tasks.
- Figure A–D composition and manuscript claim/scope rules.

No initial-project composition, reaction equation, fixed energy threshold, atom count, or chemical name may be made a generic default in the Skills.

## 7. Integration contracts

Computation--pipeline should depend on stable, narrow contracts rather than internal implementation details.

### 7.1 Chemistry-tool contract

A chemistry-tool operation should expose, directly or through a thin adapter:

- Operation name and version.
- Input artifact paths/IDs and SHA256.
- Parameters, units, assumptions, and software version.
- Exit/result status and typed diagnostics.
- Output artifact paths/IDs and SHA256.
- Machine-readable summary, preferably JSON.

If an upstream package does not expose JSON, the pipeline adapter may parse its documented result or call its Python API. Do not add unnecessary wrapper layers to the upstream Skill solely to imitate a desired interface.

### 7.2 HPC adapter contract

A normalized pipeline adapter should map each upstream cluster to:

- `preflight()`
- `stage_inputs(task_manifest)`
- `submit(task_manifest)`
- `get_status(job_reference)`
- `get_record(job_reference)`
- `retrieve_selected_outputs(job_reference, output_selection)`
- `verify_hashes(manifest)`

The adapter must preserve each cluster's unique safety rules and use the upstream job ledger as the authoritative scheduler record. It must not expose secrets or require a common remote path layout.

### 7.3 Data-analysis contract

The pipeline sends file/artifact references and operation metadata to Data_analysis. Data_analysis returns:

- Artifact and analysis-run IDs.
- Parse/quality/eligibility status.
- Normalized result paths and hashes.
- Warnings, assumptions, and source locators.
- Cache identity and version.

Do not move raw large arrays or CP2K logs into LLM prompts.

## 8. Required implementation ownership guardrails

1. Before writing new code, search the existing four repos and established packages for an equivalent, tested function.
2. Do not build functionality in Computation--pipeline merely because it is convenient to import there.
3. Do not build a second CP2K parser, second HPC job ledger, second artifact database, or second plotting style engine.
4. If a shared general-purpose scientific function is missing, add it to the proper upstream Skill through a separate branch/PR.
5. If a capability coordinates tasks or gates stages, implement it in Computation--pipeline.
6. If a capability is specific to the first chemical project, put it in the project's external configuration or separated project plugin.
7. Keep changes backward-compatible and covered by tests; do not remove old APIs without a migration plan.
8. No production DFT/HPC run is authorized by this architecture document.
9. No upstream PR may be merged automatically. Report the PR and commit SHA for owner review.
10. The private HPC repositories and their operational settings must stay private.
11. Generic Skills must not receive project test-data content, project-specific chemical facts, or hardcoded output values.
12. A feature is not "implemented" until tests demonstrate behavior; it is not "scientifically validated" until compared with an appropriate independent/reference result.

## 9. Architecture acceptance

The architecture is accepted when:

- Each planned capability has exactly one primary owner.
- No required capability is implemented in two repositories without a documented reason.
- Upstream Skills expose reusable functions while preserving existing behavior.
- Computation--pipeline contains orchestration and project-scoped policy, not duplicated scientific engines.
- Private cluster details remain outside the public repository.
- The initial v4.1 configuration remains isolated from generic production behavior.
- All final numerical statements and figures retain artifact/task provenance.
