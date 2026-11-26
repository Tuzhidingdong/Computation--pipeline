# Agent Execution Prompt — Upstream Skill Remediation v1.0.0

**This file is the executable task brief for the coding Agent.** It is intentionally self-contained. Do not treat the link to this file as a substitute for reading the task: read the whole document, follow the sequence, and use the linked repository documents as the governing technical evidence.

## 0. Your assignment in one paragraph

Prepare the existing scientific-computing Skills so that the new public repository, `Tuzhidingdong/Computation--pipeline`, can later orchestrate them without duplicating their responsibilities. You are currently doing **pre-implementation upstream remediation**, not building the Computation--pipeline engine and not running the user's scientific project. Implement and test the bounded, reusable capability gaps in **chem-scitoolkit** and **Data_analysis**; audit and map the existing **BeiLong_HPC** and **UCAS_hpc** interfaces without redesigning them; verify the selected external-tool choices; and produce mock-based integration evidence plus reviewable GitHub PRs. Use synthetic fixtures only. No production DFT or HPC task may be submitted. Do not change the frozen v4.1 science protocol.

## 1. Repositories and exact scope

Work with these repositories:

| Repository | Visibility | Your authorized work |
|---|---|---|
| `Tuzhidingdong/Computation--pipeline` | Public | Coordination docs, adapter mapping, mock contract tests/evidence, tracker and status updates only. Do not implement the workflow engine or production project. |
| `Tuzhidingdong/chem-scitoolkit` | Public | Implement CST-1 through CST-7 as backward-compatible, generic reusable library/Skill improvements. |
| `Tuzhidingdong/Data_analysis` | Private | Implement DA-1 through DA-3: DFT artifact formats, reader/operation registration, provenance/evidence links. |
| `Tuzhidingdong/BeiLong_HPC` | Private | Read-only/reuse-first interface audit and pipeline adapter mapping. No planned code changes. |
| `Tuzhidingdong/UCAS_hpc` | Private | Read-only/reuse-first interface audit and pipeline adapter mapping. No planned code changes. |

The audited snapshots, which are **historical baselines and not permission to ignore newer changes**, were:

- chem-scitoolkit: `87a061b309bbb9fdf4461d2d1d2873dbfd8681fb`
- Data_analysis: `5684c6a762ac09caf24661c987b2e7a97eb0e2e7`
- BeiLong_HPC: `40ce15a9285e94f4abf1418361387e90e850a899`
- UCAS_hpc: `ebde5c1e76432d7e0d6728da804fb62dc5f84583`

The audit is source-level evidence, not a claim that all external executables or cluster environments have been tested. Refresh every repository before editing. If any relevant upstream file changed since the audited snapshot, re-read and re-audit that code before deciding what to change. Do not overwrite newer owner work.

## 2. Read first; do not code before this review

Read the following files in full, in this order:

1. `TASK_PLAN_v1.0.0.md` — overall objective, scientific scope and acceptance baseline.
2. `docs/ARCHITECTURE_OWNERSHIP.md` — what belongs in the orchestrator versus each specialist Skill and external package.
3. `docs/EXISTING_SKILL_CAPABILITY_AUDIT.md` — concrete source findings and inspected revisions.
4. `docs/UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md` — authorized work packages and ready-to-start gate.
5. `docs/EXTERNAL_TOOL_SELECTION.md` — current dependency choices and cautions.
6. `docs/UPSTREAM_REMEDIATION_STATUS.md` and `STATUS.md` — current tracker and execution state.

Use `AGENT_START_HERE.md` as navigation only. This prompt plus the six governing files above define the task. If documents conflict, use the following priority: (a) user-approved scope and safety boundaries in this prompt, (b) architecture ownership, (c) the detailed remediation task, (d) the capability audit as evidence of the starting point, and (e) the Task Plan for the future pipeline target. Record any conflict instead of silently guessing.

**Requirement-ID reconciliation:** The audit describes provenance work as DA-4 in one section, while the detailed task and status tracker define the same provenance work as DA-3. Use the task/tracker identifiers: **DA-1 = DFT formats, DA-2 = readers and operations, DA-3 = provenance/evidence**. Include all provenance details described under DA-4 in the audit as acceptance criteria for DA-3; do not create a separate untracked DA-4.

## 3. Non-negotiable operating rules

1. **One coordinating Agent.** Do not silently delegate to subagents, background workers or other models. Do not hide model/worker use. Complete the work in a visible, auditable sequence.
2. **No production scientific computation.** Do not submit CP2K production calculations, remote HPC jobs, Slurm jobs, finite-displacement farms, or real project calculations. Do not initiate jobs through either private HPC Skill. Synthetic fixtures, unit tests, parsers, lints and mocks are allowed. A tiny local executable smoke test is permitted only when it is clearly synthetic, isolated, non-production and cannot submit remotely; otherwise use static/linter validation and mark executable validation as not run.
3. **No science-protocol edits.** Do not change v4.1 chemistry, models, atom counts, charges, spin choices, basis/pseudopotential choices, cutoffs, box sizes, convergence thresholds, reaction scope, thermodynamic assumptions, or figure claims. The values in the Task Plan are project-specific validation requirements, not generic library defaults.
4. **No project data in generic Skills.** Do not add real project structures, atom lists, chemical compositions, private research results, manuscript text, or project-specific thresholds as production Skill rules, defaults, examples, fixtures or tests. Tests must be synthetic and clearly separated from production package data.
5. **Keep private HPC details private.** Do not copy cluster hostnames, usernames, accounts, credentials, tokens, keys, private paths, connection commands containing secrets, or private operational configuration into the public pipeline repository, logs, PRs or test fixtures. Keep BeiLong_HPC and UCAS_hpc private.
6. **Backward compatibility.** Preserve current public function names, signatures and behavior unless an additive API or deprecation path is necessary. Do not silently change the semantics of an existing API.
7. **Reuse-first.** Before implementing, search existing code and selected external packages for an equivalent tested capability. Do not build a second CP2K parser, Bader engine, vibration engine, plotting engine, artifact database, HPC ledger or workflow server.
8. **No unrelated cleanup.** Do not reformat or restructure unrelated files, rename unrelated APIs, upgrade broad dependency sets, or introduce new architecture outside the accepted work packages.
9. **No secrets or destructive operations.** Never commit secrets. Do not use destructive `git clean`, force-push, history rewrite, reset of user work, or mass deletion. Preserve pre-existing dirty/untracked work and stop if it makes safe isolation impossible.
10. **No merges or releases.** Push dedicated branches and open separate, review-ready PRs. Do not merge PRs, enable auto-merge, publish packages, tag releases, or change default branches. The owner reviews and merges.
11. **Report evidence honestly.** Distinguish implemented, unit-tested, syntax/lint-checked, executable-smoke-tested, mock-integrated and scientifically validated. A passing unit test does not prove physical correctness or production compatibility.
12. **Do not begin Phase 1 of the Computation--pipeline engine.** The engine work is blocked until the owner has reviewed and merged the necessary upstream PRs.

## 4. Execution sequence

### Phase A — workspace and repository preflight

For each repository:

1. Confirm the repository identity, remote URL and default branch.
2. Inspect current branch, working-tree status, untracked files and existing local changes before fetching or switching.
3. Fetch remote refs without deleting local work. Record current default-branch HEAD SHA and relevant PR/branch state.
4. Compare current source against the historical audited SHA above. Re-audit any changed relevant files.
5. Check whether a remediation branch or PR already exists. Do not overwrite it; inspect and continue only when ownership and state are clear.
6. Create a dedicated branch from the freshly fetched default branch. Suggested names:
   - chem-scitoolkit: `dft-finite-cluster-production-interfaces`
   - Data_analysis: `cp2k-dft-artifact-and-evidence-support`
   - Computation--pipeline: `upstream-remediation-integration-evidence`
7. Never work on an upstream default branch. Keep the two private HPC repositories on read-only inspection unless a concrete blocker is demonstrated.

If a private repository cannot be accessed, do not infer its contents from the old audit. Mark that portion blocked and report the exact access limitation. Do not ask for, print or commit credentials.

### Phase B — chem-scitoolkit: implement CST-1 through CST-7

Repository: `Tuzhidingdong/chem-scitoolkit`.

#### CST-1 — finite/non-periodic CP2K input builder

Extend the existing builder additively. The generic API must support, through explicit configuration:

- Finite molecule/cluster coordinates and a user-defined cell.
- Independent cell periodicity and Poisson periodicity set to non-periodic when requested; configurable Poisson solver such as MT.
- Optional coordinate centering with a documented, testable transformation.
- Per-KIND basis and GTH pseudopotential assignment. Different KIND labels for the same chemical element must be supported when their basis/potential definitions differ.
- Total charge, UKS/spin treatment and multiplicity/electron-parity validation.
- Configurable XC functional and dispersion model/parameters.
- Cutoff and relative cutoff.
- SCF method, diagonalization/OT selection, smearing, added MOs and mixing controls.
- Run type: ENERGY, ENERGY_FORCE or GEO_OPT.
- Explicit print sections required by supported downstream analyses.

Acceptance:
- Existing builder calls and their output defaults remain compatible.
- A synthetic finite-system input demonstrates the new options, including KIND-specific basis/potential, spin settings, smearing and non-periodic Poisson/MT configuration.
- Invalid or missing KIND, basis or pseudopotential references fail before a calculation can be staged.
- Lint/parse the generated input using the selected CP2K input tool where available. Record exact tool and version.
- Do not hardcode project-specific labels or settings such as Cu-q11, Sn-q14, PBE-D3(BJ), 30 Å or 500 Ry as generic defaults.
- Do not claim executable compatibility merely because text generation or lint succeeds.

#### CST-2 — task-aware CP2K output validation

Add a structured task-aware parser/result validator. It must distinguish:

- Program normal termination from a scheduler's COMPLETED state.
- Complete output from truncated/incomplete output.
- SCF convergence and last-iteration details.
- GEO_OPT completion and final force information where available.
- ENERGY and ENERGY_FORCE completion.
- Presence/validity of final energy and expected output records.
- Fatal errors, numerical warnings and missing required records.
- CP2K version and parser version when identifiable.

Acceptance:
- An SCF convergence marker alone must never certify GEO_OPT success.
- The checks must depend on the requested run type.
- Old `is_converged()` behavior must not be silently redefined. Preserve it for compatibility or clearly deprecate it while providing a new explicit validator.
- Fixtures cover normal termination, SCF-only marker, truncation, fatal error, GEO_OPT success/failure, ENERGY_FORCE output and missing energy.

#### CST-3 — truthful Bader versus Hirshfeld reporting

- Preserve the actual Hirshfeld parser.
- Reclassify the existing Hirshfeld-scaling routine as an **approximate calibrated Hirshfeld estimate**, not Bader. Rename/deprecate misleading names/columns with a documented compatibility path.
- True Bader results must be parsed from actual density-basin output produced by Multiwfn or a validated Bader implementation.
- Preserve/map every result to the original atom index, element and atom order.
- Validate atom count, finite values, density-grid metadata, population/electron count and charge convention.
- Report residuals. Never silently redistribute residual charge merely to force neutrality.

Acceptance tests must prove that true Bader and approximate Hirshfeld values cannot be confused in API output, metadata, Skill instructions or report labels; include wrong atom order/count, missing output and charge/population mismatch.

#### CST-4 — CP2K PDOS parsing and normalization

Prefer one primary established parser route, initially evaluating cp2k-output-tools and, where justified, pymatgen. Expose a stable chem-scitoolkit API without maintaining a duplicate parser.

Preserve at minimum:
- Energy grid and units.
- Spin channel.
- Atom index, element and KIND.
- Orbital/projection labels and selection metadata.
- Broadening method/width and grid parameters.
- Input/output source references or hashes.
- Parser/package version and warnings.

Export normalized tabular data plus metadata JSON. Same-grid comparisons must validate compatibility. Fermi-level alignment and vacuum-level alignment must be distinct modes with distinct evidence requirements.

Acceptance tests cover spin-polarized and non-spin-polarized data, multiple projections, unit conversion, metadata, malformed input and grid mismatch.

#### CST-5 — Cube grid, density-difference and vacuum-reference validation

Implement reusable helpers to inspect and compare:
- Atom count and atom records.
- Grid dimensions and origin.
- Voxel vectors/spacing.
- Atomic coordinates and atom mapping.
- Data-array size and finite values.

Only subtract densities when grids and atom mappings are demonstrably compatible. Add a vacuum-region potential plateau detector that reports the sampled region, spread/slope/tolerance and pass/fail state.

Before allowing an energy reference shift, document exactly which CP2K output quantity is used and why its zero is physically appropriate. Do not assume an arbitrary Hartree cube is a valid vacuum reference. If the required potential or reference is unavailable or unverified, fail closed and report that vacuum alignment is unsupported for that input.

Acceptance tests include matching/mismatching grids, reordered atoms, incompatible coordinates, malformed data, stable plateau and sloping/nonuniform vacuum region.

#### CST-6 — ASE vibration/thermochemistry wrapper

Reuse ASE's existing vibration and thermochemistry algorithms; do not reimplement statistical-mechanics formulas.

Add only a thin reusable wrapper/normalized record where needed. Preserve:
- Frequencies and units.
- Atomic masses and selected atom indices.
- Constraints and frozen atoms.
- Imaginary/near-zero mode policy and diagnostics.
- Temperature and thermochemistry convention.
- ZPE and thermal/entropy correction values with units.
- Clear distinction between adsorbate-only/frozen-support subspace and full-system normal modes.
- Required metadata when an ideal-gas treatment is requested.

Remote finite-displacement job enumeration, HPC dispatch, retries and force reassembly belong to Computation--pipeline, not this Skill.

Acceptance tests cover known synthetic harmonic data, unit conversion, temperature metadata, imaginary/near-zero modes, constraints and missing/inconsistent input.

#### CST-7 — configurable publication figure profiles

Extend the existing style system with profile-driven configuration for:
- White/opaque versus transparent background.
- Figure width/height and column sizing.
- Font family and point sizes.
- Axis, tick, spine and line-width rules.
- Panel-label configuration.
- Palette and colour-cycle selection.
- Raster/vector export formats and DPI where relevant.
- Export metadata and reproducibility settings.

Preserve current defaults and existing API behavior. Do not hardcode a journal-specific project figure composition, panel labels, chemical species or Fig. A–D layout into the reusable library.

Acceptance tests verify explicit profile values, white/transparent output options, configured sizes/fonts, vector/raster export and unchanged legacy defaults.

#### CST-1–CST-7 shared completion requirements

- Update the relevant Skill documentation with correct capability descriptions and examples that are synthetic and generic.
- Add focused tests plus the repository's relevant regression/full test suite.
- Record dependency versions and license/runtime caveats.
- Do not mark an external executable pathway production-validated if the executable was unavailable.
- Ensure no project-specific v4.1 chemistry or private configuration leaked into source, tests, docs or fixtures.

### Phase C — Data_analysis: implement DA-1 through DA-3

Repository: `Tuzhidingdong/Data_analysis`.

Retain the existing Artifact, Analysis Run, SHA256, cache and evidence architecture. Extend schemas only when a tested DFT use case cannot be represented by the existing fields.

#### DA-1 — DFT artifact format registration

Add/complete distinct content-aware format definitions for relevant families:
- CP2K input, main output/log and relevant result files.
- CP2K PDOS file families and associated projection metadata.
- Gaussian cube density/potential files.
- ASE structures and trajectories.
- Finite-displacement/force result tables and their mapping metadata.

Do not classify a file based only on a generic extension such as `.out` or `.cube`. Use file content/signatures plus contextual metadata where required. Distinguish format recognition from validation/parse success. Keep unsupported or untested formats candidate/planned.

Acceptance tests include unrelated files with misleading extensions, truncated/malformed examples, file-family association and honest status transitions.

#### DA-2 — reader and deterministic operation registration

Register the selected primary CP2K parser route and its exact version. Register only deterministic operations that are actually provided and tested, including as appropriate:
- CP2K run-summary normalization.
- PDOS normalization/metadata packaging.
- Cube-grid validation result packaging.
- Calculation-result packaging/normalization.

The actual scientific parser and algorithms remain in chem-scitoolkit or the selected external parser. Data_analysis records/validates artifacts and operations; it must not implement a second CP2K parser, PDOS algorithm, density analysis or thermochemistry engine.

Acceptance tests prove registry references resolve, operation versions/parameters are recorded, and an entry cannot be marked validated/production-ready without passing representative tests.

#### DA-3 — DFT provenance and evidence linkage

For each normalized DFT result, preserve links to:
- Input CP2K input artifact ID and SHA256.
- Output log and relevant output artifact IDs/hashes.
- Structure artifact ID/hash and approved-model hash when applicable.
- CP2K executable/version and basis/pseudopotential references where known.
- Upstream HPC task/job reference (identifier only; no private connection details).
- Parser/operation name and version.
- Operation parameters, units, assumptions and warnings.
- QC/eligibility status and source locator.
- Cache identity and relevant software versions.

Reuse the current Artifact and Analysis Run schemas wherever possible. Add fields only with schema migration/backward-compatibility tests and a documented reason. Do not create a second database or project state machine.

Acceptance tests cover input/output hash linkage, structure/model identity, missing job references, partial parse results, warning propagation, schema compatibility and provenance round trips.

### Phase D — BeiLong_HPC and UCAS_hpc: audit and adapter mapping only

Do not redesign either private HPC Skill. Inspect their documented tools and records read-only, and map the existing functions to the future normalized pipeline interface:

- `preflight()`
- `stage_inputs(task_manifest)`
- `submit(task_manifest)`
- `get_status(job_reference)`
- `get_record(job_reference)`
- `retrieve_selected_outputs(job_reference, output_selection)`
- `verify_hashes(manifest)`

For each adapter method, document:
- Existing upstream Skill script/tool or documented operation used.
- Required sanitized input/output fields.
- How scheduler state and application-level completion are distinguished.
- How the existing upstream job record remains authoritative.
- Which behavior must stay cluster-specific.
- Whether the method was inspected, mock-tested or not tested.

Keep different command conventions, path boundaries, job record locations and safety policies. Do not invent a shared remote filesystem layout. Do not run SSH, SCP, Slurm or a real preflight during this task. Use mocks or static inspection only.

Only when a required interface is demonstrably impossible with existing operations may you propose a minimal additive upstream PR. First record the exact blocker and why the pipeline adapter cannot safely solve it. Such a PR is not automatically authorized: report the proposed scope and wait for owner approval before changing either HPC repository.

### Phase E — external tools and dependency verification

Update the existing `docs/EXTERNAL_TOOL_SELECTION.md`; do not create a duplicate. For each dependency actually selected, record exact package/tool version, license, Python/platform compatibility, source URL, relevant API/CLI used, installation/runtime availability and validation status. Evaluate at least ASE, RDKit, optional molSimplify, cp2k-input-tools, cp2k-output-tools, pymatgen, Multiwfn/Bader, Matplotlib and the document-output libraries where they are used.

Rules:
- Select one primary CP2K parser route; use another only as a documented cross-check.
- ASE owns the vibration/thermochemistry algorithms.
- RDKit is for appropriate organic graph tasks; do not assume it solves all transition-metal coordination.
- Multiwfn/Bader output conventions must be tested before true-Bader claims.
- Third-party Skills with draft status or older CP2K validation are references/checklists only, not assumed production dependencies.
- Do not introduce AiiDA, atomate2, jobflow, FireWorks, another workflow server or database in this phase.
- MACE-MP-0, if mentioned, remains geometry prescreen only; do not use it for final energies or as the sole basis for candidate rejection.

If a dependency cannot be installed or executed in the current environment, record the exact version evidence available and mark runtime validation as not performed. Do not guess a version or license.

### Phase F — cross-repository mock integration

In the Computation--pipeline remediation branch, implement only minimal contract/adaptor tests and documentation needed to demonstrate the hand-off between repositories. Do not create the workflow DAG, task scheduler, production project plugin, model builder or report engine.

Using synthetic fixtures and mocks, demonstrate:

1. The pipeline-facing adapter can call the chem-scitoolkit finite-system builder without copying its implementation.
2. Scientific output validation distinguishes scheduler completion from CP2K task success.
3. ASE thermochemistry is reused through the agreed wrapper rather than reimplemented.
4. Data_analysis can register/trace CP2K, PDOS and cube artifacts and link provenance.
5. BeiLong and UCAS adapters map their distinct upstream contracts to the normalized interface.
6. Input/output hashes and task references survive a simulated interrupted/restarted local controller interaction.

Tests must not require network access, private cluster credentials, HPC connectivity or production calculations. Clearly label mock evidence as mock evidence.

## 5. Test and validation procedure

For each repository, inspect its existing test configuration and documented commands first. Then:

1. Run the narrow tests for each changed component.
2. Run schema/registry validation.
3. Run the relevant existing regression tests.
4. Run the full repository test suite when practical.
5. Record skipped tests and the exact reason.
6. For generated CP2K input, run static/input-tool lint where available and record the tool version.
7. For external executables not present, mark the corresponding executable test not run; do not substitute a unit test and claim executable validation.
8. Run mock integration tests from the Computation--pipeline branch.
9. Inspect the final diff for unrelated changes, secrets, project-specific data, API breakage and unsupported scientific claims.

Every test report must include the command, exit code, test count or concise test summary, and whether it used synthetic data, a mock, a real local executable or a remote service. Never report only "tests passed".

## 6. GitHub branch, commit and PR requirements

Create separate dedicated branches from fresh default-branch heads. Keep one PR per changed repository:

- chem-scitoolkit PR for CST-1–CST-7.
- Data_analysis PR for DA-1–DA-3.
- Computation--pipeline PR for the adapter mapping, mock tests, dependency verification and progress documentation.

For BeiLong_HPC and UCAS_hpc, do not open a PR unless a concrete blocker is demonstrated and the owner separately authorizes a minimal patch.

Each PR must:
- Target the repository's default branch.
- Explain the user-facing capability and backward-compatibility behavior.
- List requirement IDs and exact changed files.
- Summarize tests with exact results and unrun validation.
- State explicitly that no production DFT/HPC task was submitted.
- Identify all new dependencies and license/version implications.
- Avoid claiming scientific validation beyond the actual evidence.

Push branches and open review-ready PRs. Do not merge, enable auto-merge, or push to default branches. Do not close or replace an existing PR without owner authorization.

## 7. Required documentation updates

In the Computation--pipeline branch:

1. Update `docs/UPSTREAM_REMEDIATION_STATUS.md` row-by-row for CST-1…7, DA-1…3, HPC-1, HPC-2, EXT-1 and INT-1. Each COMPLETE status must link to code, tests, commit and PR evidence. Use BLOCKED/PARTIAL/NOT RUN honestly.
2. Update `STATUS.md` with the exact current phase, branch/commit/PR references, tests, blockers and explicit statement that the pipeline engine has not started.
3. Update `docs/EXTERNAL_TOOL_SELECTION.md` with verified dependency/version/license/runtime facts and unresolved items.
4. Add a sanitized HPC adapter mapping document under `docs/`.
5. Add a cross-repository mock integration test report with reproducible commands and outcomes.
6. Keep `TASK_PLAN_v1.0.0.md` as the future objective/acceptance baseline. Do not rewrite its scientific scope to fit implementation convenience.

Do not mark this prerequisite complete while any required item is only described but not implemented/tested, unless it is explicitly BLOCKED with a concrete reason and owner decision required.

## 8. Stop conditions — stop the affected work package and report

Stop rather than guess if:
- A current upstream branch contains relevant changes not covered by the audit and they cannot be safely reconciled.
- A required private repository or test dependency is inaccessible.
- An implementation would require changing an existing public API incompatibly.
- CP2K keyword/version support cannot be verified and the implementation would otherwise make an unsupported compatibility claim.
- Bader output lacks adequate atom mapping or electron/charge accounting.
- The vacuum-level reference is physically ambiguous or unsupported by available outputs.
- A proposed fix requires production DFT/HPC execution, secrets, real cluster access or private project data.
- You discover project-specific chemistry/results or private HPC settings in a generic/public repository.
- A test would contact a cluster, submit a job, incur a charge or alter user data.
- You find existing owner work, an active PR or a dirty working tree that cannot be safely isolated.

When blocked, preserve current work, do not bypass the gate, and provide the precise evidence plus the minimum decision needed from the owner.

## 9. Definition of done

This prerequisite is ready for owner review only when:

- CST-1 through CST-7 are implemented and the specified tests pass, or each remaining item is explicitly BLOCKED with evidence and a reason that requires owner decision.
- DA-1 through DA-3 are implemented and the specified tests pass, or explicitly BLOCKED with evidence.
- Both HPC adapters have a sanitized method-by-method mapping and mock evidence; no unnecessary HPC Skill rewrite was made.
- Tool versions, licenses, interfaces and runtime validation states are recorded without guesses.
- Cross-repository mock tests pass or their exact blockers are reported.
- No duplicate CP2K parser/builder, Bader engine, vibration engine, plotting engine, artifact database, HPC ledger or workflow server was introduced.
- Relevant PRs are open, review-ready and unmerged.
- Computation--pipeline engine implementation has not started.
- No production DFT/HPC job was submitted.
- The tracker and STATUS accurately reflect the evidence.

Passing this prerequisite does **not** mean the v4.1 scientific workflow has been run or validated.

## 10. Final report format — mandatory

Return a concise executive summary followed by this evidence table:

| Work package | Repository | Branch | Commit SHA | PR URL | Tests and exact result | Validation level | Status |
|---|---|---|---|---|---|---|---|

Then report:

1. **Baseline refresh:** default branch and current HEAD SHA for all four upstream repositories; any drift from audited snapshots.
2. **CST-1…CST-7:** changed modules/APIs, backward-compatibility strategy and test evidence.
3. **DA-1…DA-3:** registry/schema changes, provenance behavior and test evidence.
4. **HPC-1/HPC-2:** sanitized adapter method mapping, exact upstream tool names inspected and mock results.
5. **External tools:** exact versions/licenses/runtime availability and unresolved validations.
6. **Integration:** reproducible mock-test commands, results and limitations.
7. **Security/scope audit:** confirmation that no secrets, private HPC settings, project-specific chemistry/results or unrelated changes were committed.
8. **Unresolved items:** blocked work, why blocked, evidence and owner decision needed.
9. **Execution boundary:** explicit confirmation that no production DFT/HPC/Slurm task was submitted and no Computation--pipeline engine implementation began.
10. **GitHub evidence:** repository, branch, commit SHA, PR URL and exact changed-file links for every changed repository.

Do not use "done", "validated" or "production-ready" without the evidence level supporting that exact claim.
