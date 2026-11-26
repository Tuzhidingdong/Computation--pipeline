# Upstream Skill Remediation — Agent Task v1.0.0

**Purpose:** Close the reusable capability gaps identified in [EXISTING_SKILL_CAPABILITY_AUDIT.md](EXISTING_SKILL_CAPABILITY_AUDIT.md) before implementation of the Computation--pipeline workflow engine.

**Ownership rules:** Follow [ARCHITECTURE_OWNERSHIP.md](ARCHITECTURE_OWNERSHIP.md). This task authorizes only the scoped, backward-compatible improvements below. It does not authorize changes to the frozen v4.1 scientific protocol or production calculations.

## 1. Required execution discipline

- Refresh the four repository heads and record the exact revisions inspected.
- Use a dedicated branch in each repository that needs changes; never develop directly on `main`.
- Open separate pull requests. Do not merge them.
- Work sequentially as one coordinating Agent. Do not silently create additional agents.
- Use synthetic or non-sensitive fixtures. Do not place project-specific molecules, structures, numerical results, or operational cluster configuration in generic Skills.
- Do not submit production DFT/HPC tasks during this remediation.
- Keep existing APIs backward-compatible; test every changed contract.
- Report implementation, testing, and scientific validation as separate levels of evidence.

## 2. chem-scitoolkit — required remediation

Repository: https://github.com/Tuzhidingdong/chem-scitoolkit  
Suggested branch: `dft-finite-cluster-production-interfaces`

### CST-1 — finite-system CP2K builder

Extend the existing builder, preserving old APIs, to support:
- Configurable molecular/cluster coordinates and finite simulation cell.
- Cell and Poisson `PERIODIC NONE`, configurable MT solver, and coordinate centering.
- Per-KIND basis and pseudopotential assignment.
- Charge, UKS, multiplicity, XC, dispersion, cutoff, SCF method, smearing, diagonalization, added MOs, mixing and print settings.
- ENERGY, ENERGY_FORCE and GEO_OPT run types.

Do not hardcode v4.1 choices such as Cu-q11, Sn-q14, PBE-D3(BJ), 30 Å or 500 Ry as generic defaults. Validate KIND/data-file references. Use cp2k-input-tools for syntax/data-file lint where available, but retain executable/version checks as a separate requirement.

### CST-2 — strict CP2K output assessment

Add task-aware structured parsing for normal program termination, incomplete/truncated output, SCF convergence, GEO_OPT completion/final force, ENERGY/ENERGY_FORCE completion, final energy, fatal errors and warnings. Keep the old `is_converged()` contract backward-compatible; do not equate an SCF marker with successful geometry optimization.

### CST-3 — truthful charge reporting

Keep Hirshfeld parsing. Mark the existing Hirshfeld-scaling routine as an approximate estimate, not true Bader analysis; rename/deprecate misleading output labels. Add tested parsing of actual Multiwfn/Bader density-basin output, preserving atom order and charge convention. Validate atom count and charge/population residuals; do not silently redistribute residuals to force neutrality.

### CST-4 — CP2K PDOS adapter

Prefer cp2k-output-tools or pymatgen for parsing, then expose a stable chem-scitoolkit API. Preserve energy units/grid, spin channel, atom/KIND/orbital projection, broadening settings, source hash and parser version. Keep Fermi-level and vacuum-level alignment distinct.

### CST-5 — density-grid and vacuum checks

Add reusable cube metadata checks (atom count, grid dimensions, origin, voxel vectors and coordinates), grid-compatibility checks, and density subtraction for compatible grids. Add a vacuum-region plateau detector. Before energy alignment, document which CP2K potential output and zero are physically valid; a Hartree cube must not automatically be treated as a validated vacuum reference. Block alignment if the reference is not defensible.

### CST-6 — ASE thermochemistry interface

Reuse ASE's vibration and thermochemistry implementations. Provide thin wrappers for frequency/mass/constraint metadata, imaginary-mode policy, ZPE and thermal/entropy corrections, and explicit adsorbate-subspace versus full-system scope. Remote displacement scheduling is not part of this Skill.

### CST-7 — configurable figure profiles

Extend existing plotting styles with configurable opaque white or transparent background, fonts and point sizes, column widths, axis/tick rules, panel labels, vector/raster export, and metadata. Preserve current defaults and do not hardcode the v4.1 figure composition.

### chem-scitoolkit tests

Cover legacy API compatibility; finite non-periodic input; per-KIND mapping; missing data files; CP2K success/failure/truncation cases for each run type; Bader/Hirshfeld distinction; atom ordering and charge residuals; spin-resolved PDOS; cube-grid match/mismatch; stable/non-flat vacuum regions; ASE thermochemistry units and imaginary modes; figure profiles and export formats.

## 3. Data_analysis — required remediation

Repository: https://github.com/Tuzhidingdong/Data_analysis  
Suggested branch: `cp2k-dft-artifact-and-evidence-support`

### DA-1 — DFT file-family registry

Add content-based format entries for CP2K logs/outputs, CP2K PDOS families, Gaussian cube density/potential files, ASE structures/trajectories, and displacement force-result tables where relevant. Do not trust generic extensions alone. Keep status as candidate/planned until representative tests pass.

### DA-2 — reader and operation registration

Register the selected primary CP2K parser route and version, plus deterministic result-normalization operations for CP2K summaries, PDOS metadata, cube-grid validation, and calculation-result packaging. The CP2K parser and scientific calculations remain in chem-scitoolkit or established parsers; do not implement a duplicate parser here.

### DA-3 — provenance

Link every normalized result to input/output artifact IDs and hashes, structure/model hash, CP2K and parser versions, operation parameters, upstream job reference, warnings and QC status. Reuse existing artifact and analysis-run schemas unless tests prove a missing field.

### Data_analysis tests

Test content-based detection, file-family association, partial/truncated status, registry consistency, schema validation, input/output hash linkage, and provenance round trips with synthetic fixtures.

## 4. BeiLong_HPC and UCAS_hpc — reuse-first decision

Repositories:
- https://github.com/Tuzhidingdong/BeiLong_HPC (private)
- https://github.com/Tuzhidingdong/UCAS_hpc (private)

The inspected Skills already provide cluster-specific submission, monitoring, job records, checksums, resource advice and diagnostics. Do not redesign or merge them.

For each backend, document how the future pipeline adapter can call preflight, submit, status, record lookup/sync, selective output retrieval and checksum verification. Use mocks/read-only inspection only. If an essential operation cannot be performed through the existing interface, propose one small additive PR with tests. Keep each cluster's own connection, filesystem and operational rules intact.

## 5. External tools to select and record

Create `docs/EXTERNAL_TOOL_SELECTION.md` in Computation--pipeline. Evaluate ASE, RDKit, optional molSimplify, cp2k-input-tools, cp2k-output-tools, pymatgen, Multiwfn/Bader, Matplotlib and document-generation libraries. Record license, version, platform, chosen interface and validation state. Third-party Agent Skills marked draft or tested against older CP2K releases may be used as checklists, not production dependencies.

Do not introduce AiiDA, atomate2, jobflow or another workflow server in this phase.

## 6. Cross-repository interface tests

Using local fixtures and mocks, demonstrate:
1. Pipeline can call the finite-system CP2K builder without copying it.
2. CP2K result assessment distinguishes scheduler completion from scientific success.
3. ASE thermochemistry can be reused without a second vibration engine.
4. Data_analysis can register and trace CP2K/PDOS/cube artifacts.
5. Separate HPC adapters can use the existing two cluster Skills.
6. Input/output hashes survive a simulated controller restart.

Do not implement the workflow DAG or production project during this task.

## 7. Deliverables

For each changed upstream repository, deliver a dedicated branch, tested changes, updated Skill/API documentation, commit SHA and an open PR. For any unchanged repository, provide a brief evidence-based no-change decision.

In Computation--pipeline, commit:
- `docs/UPSTREAM_REMEDIATION_STATUS.md`
- `docs/EXTERNAL_TOOL_SELECTION.md`
- A normalized HPC adapter mapping without cluster-specific settings.
- Cross-repository mock-test evidence.
- A summary of repository, branch, commit, PR, tests and unresolved limitations.

Update `STATUS.md` with the exact phase, evidence and blockers.

## 8. Ready-to-start gate

This prerequisite is complete when:
- CST-1 through CST-7 are implemented and tested, or explicitly marked blocked/not required with a justified fallback.
- DA-1 through DA-3 are implemented and tested.
- Both HPC adapter mappings are demonstrated without unnecessary HPC Skill rewrites.
- External tools, licenses, versions and interfaces are recorded.
- No duplicate generic CP2K builder/parser, HPC ledger, vibration engine or plotting engine exists in Computation--pipeline.
- All required upstream PRs are open for owner review; none is merged automatically.
- No production DFT/HPC task was submitted.

After the owner reviews and merges the needed upstream PRs, begin the Computation--pipeline implementation under `TASK_PLAN_v1.0.0.md`.

## 9. Progress report format

Report each work package with:
- Requirement IDs completed/blocked.
- Repository, branch, commit SHA, changed files and PR URL.
- Tests run and exact results.
- What is implemented, syntax-checked, or scientifically validated.
- Remaining blockers and no-change decisions.
- Confirmation that no production DFT/HPC task was submitted.
- Link to `docs/UPSTREAM_REMEDIATION_STATUS.md`.
