# Existing Skill Capability Audit

**Audit date:** 2026-11-27  
**Scope:** Current default branches of the four user-owned Skills and the public Computation--pipeline bootstrap  
**Purpose:** Identify only the missing capabilities that must be addressed before implementing the orchestrator.  
**Evidence rule:** This audit records repository paths and visible code/contracts. It does not claim that unexecuted external software or uninspected cluster configurations have been tested.

## 1. Revisions inspected

| Repository | Visibility | Inspected default-branch tree / revision |
|---|---|---|
| [chem-scitoolkit](https://github.com/Tuzhidingdong/chem-scitoolkit) | Public | `87a061b309bbb9fdf4461d2d1d2873dbfd8681fb` |
| [BeiLong_HPC](https://github.com/Tuzhidingdong/BeiLong_HPC) | Private | `40ce15a9285e94f4abf1418361387e90e850a899` |
| [UCAS_hpc](https://github.com/Tuzhidingdong/UCAS_hpc) | Private | `ebde5c1e76432d7e0d6728da804fb62dc5f84583` |
| [Data_analysis](https://github.com/Tuzhidingdong/Data_analysis) | Private | `5684c6a762ac09caf24661c987b2e7a97eb0e2e7` |
| [Computation--pipeline](https://github.com/Tuzhidingdong/Computation--pipeline) | Public | `66e086f9f2c45b318f7ecc3234f0e1e3fcf167be` |

The revisions above are the audited snapshots. Before making changes, the implementation Agent must refresh each default branch and confirm that the target files have not changed.

## 2. Executive findings

| Repository | Existing useful capability | Material gap for the planned workflow | Required action |
|---|---|---|---|
| chem-scitoolkit | CP2K builder/parser, Multiwfn wrappers, Bader-related utilities, PDOS/LDOS wrapper, publication styles | Existing CP2K builder is not a safe production builder for finite non-periodic cluster calculations; parser completion logic is too permissive; Bader calibration can be mistaken for true Bader; no validated DFT local-vibration/thermochemistry integration; PDOS/vacuum alignment and matched-grid validation incomplete | **Must remediate** generic reusable tools and tests |
| Data_analysis | Artifact, analysis-run, evidence schemas; inventory, hashing, cache, data-quality/provenance architecture | CP2K output format is explicitly planned, not implemented; DFT-specific reader/operation registrations are absent or incomplete; Cube/PDOS artifact handling and test coverage must be formalized | **Must remediate** DFT artifact/reader/operation registration and evidence normalization, without duplicating chemistry parser algorithms |
| BeiLong_HPC | Cluster-specific connection rules, Slurm lifecycle, checksums, job records, resource advisor, diagnosis, tests | Core scheduler functionality exists; no common pipeline adapter contract is exposed, but this is a cross-system concern rather than a reason to rewrite the cluster Skill | **Reuse as-is; no planned code change** unless adapter testing proves a specific blocker |
| UCAS_hpc | Cluster-specific SSH/SCP/Slurm workflow, job record, checksum manifest, resource advisor, bounded diagnostics, tests | Core scheduler functionality exists; its command/record conventions differ from BeiLong, requiring normalization in the new pipeline adapter | **Reuse as-is; no planned code change** unless adapter testing proves a specific blocker |

Do not interpret "not present" as a defect in a general-purpose Skill unless the missing feature belongs to that repository's responsibility. The HPC Skills are not CP2K scientific parsers or global workflow engines; their lack of a shared cross-cluster interface should be handled in Computation--pipeline.

## 3. chem-scitoolkit — concrete findings

### 3.1 Current relevant code

| File | Existing capability observed | Gap / risk |
|---|---|---|
| `.agents/skills/chem-scitoolkit/SKILL.md` | General CP2K/VASP/ORCA, charge, PDOS/LDOS, kinetics, and figure guidance | PDOS rule states `E - E_F = 0` as the general alignment rule; it does not describe finite-cluster vacuum-level alignment as a separately validated option |
| `my_sci_toolkit/simulation/cp2k/builder.py` | Builds CP2K input from coordinates and CIF parser; has basic PBE, cutoffs, OT option and default KIND sections | Defaults to `PERIODIC XYZ`; emits no `&POISSON`/MT; generic one-size basis/potential per element; DFTD3 mode is not configured as a selectable BJ variant; spin, smearing, per-element KIND and finite-cell options are incomplete for this task |
| `my_sci_toolkit/simulation/cp2k/parser.py` | Parses final energy, SCF iteration energies, COLVAR/energy trajectory, and CP2K Hirshfeld data | `is_converged()` returns true if it finds either geometry completion OR an SCF-converged string. That is not task-type-aware; it does not prove normal termination, complete output, or geometry/force convergence independently |
| `my_sci_toolkit/simulation/multiwfn/charge_bader.py` | Calls Multiwfn for Bader-like basin analysis, ESP surface and ELF cube generation | Returned runner object is not in itself a validated charge table; actual output parsing, atom order, population/charge convention, completeness and charge sum need tests |
| `my_sci_toolkit/simulation/cp2k/parser.py::calibrate_bader_from_hirshfeld` | Produces columns named `bader_population` and `bader_net_charge` using element scaling of Hirshfeld charges and residual neutralization | This is not a topological Bader partition. The name/output columns can misrepresent an empirical estimate as actual Bader data; it must be renamed or explicitly marked as an approximate calibrated Hirshfeld estimate and excluded from true-Bader reporting |
| `my_sci_toolkit/simulation/multiwfn/cohp_dos.py` | Multiwfn fragment COHP helper and single-atom LDOS/PDOS menu wrapper | No robust parser/normalizer for CP2K PDOS files is shown here; spin channels, atom/orbital labels, energy units, broadening/grid consistency, and output metadata need validation |
| `my_sci_toolkit/viz/style.py` | Arial-capable configurable Nature/JACS style, 8 pt default, column widths and palettes | Defaults to transparent export and general colored palettes. It lacks a clearly specified configurable white-background profile and no figure-specific font/label/file QC is shown |
| `my_sci_toolkit/kinetics/thermodynamics.py` | Capillary pressure and nanoscale solubility functions | It is not a DFT vibrational thermochemistry, ZPE, entropy, CHE, or adsorption/desorption energy module |
| `tests/test_simulation.py` | Basic CP2K builder smoke test and synthetic Bader-calibration test | Does not test finite non-periodic CP2K input, MT syntax, version-specific keywords, strict normal termination, truncated outputs, real Bader output parsing, PDOS parsing, or ASE/CP2K force displacement |

### 3.2 Required chem-scitoolkit remediation

**CST-1 — Generic finite-system CP2K input support**

Extend the existing builder without breaking existing APIs. Support user-configurable:
- Finite molecule/cluster geometry coordinates and a defined cell.
- Independent `&CELL PERIODIC NONE` and `&POISSON PERIODIC NONE` configuration and selectable solver such as MT.
- Coordinate centering options where appropriate.
- Per-`KIND` basis and GTH potential labels, including different kinds for the same element when required.
- Charge, UKS, multiplicity, XC functional, dispersion type and parameters, cutoff/relative cutoff, SCF method, diagonalization/smearing, added MOs, mixing, and run type (`ENERGY`, `ENERGY_FORCE`, `GEO_OPT`).
- Requested CP2K print sections needed by supported operations.

Do not hardcode Cu-q11, Sn-q14, PBE-D3(BJ), 30 Å, 500 Ry or any specific v4.1 values as generic defaults. Validate element/pseudo/basis references against supplied data files. Use `cp2k-input-tools` for syntax/data lint where available, and test actual keyword support against the target CP2K executable version before claiming executable compatibility.

**CST-2 — Task-aware CP2K output validation**

Add structured parse results with distinct fields for:
- Program normal termination.
- Output truncation/incomplete output.
- SCF convergence and last iteration details.
- Geometry optimization completion and final maximum force where available.
- ENERGY/ENERGY_FORCE completion and last total energy.
- Fatal errors, numerical warnings and missing expected outputs.
- Parser version and CP2K version identification where possible.

Do not change the meaning of the old `is_converged()` silently. Preserve compatibility and introduce an explicit task-aware result/validator. A task must pass only the checks relevant to its run type.

**CST-3 — Correctly distinguish Bader from non-Bader charge estimates**

- Preserve actual Hirshfeld parsing.
- Mark `calibrate_bader_from_hirshfeld` as an approximate calibrated Hirshfeld estimate, rename/deprecate misleading Bader naming, and prevent its output from being labelled true Bader.
- For true Bader analysis, parse actual Multiwfn or Bader program outputs from an electron-density grid.
- Map every population to the original atom index and element.
- Validate atom count, finite values, density-grid origin/spacing/dimensions, electron population sum against the relevant valence-electron count, and residual charge.
- Fail or report the residual; never silently redistribute residual charge merely to force neutrality.

**CST-4 — PDOS parsing and normalization**

Prefer an established parser such as `cp2k-output-tools` where suitable, wrapped through a stable chem-scitoolkit API. Support:
- Energy grid, units, spin channel, atom index, element, KIND and orbital/projection metadata.
- Broadening/grid metadata and explicit sum/selection rules.
- Same-grid validation when comparing systems.
- Export to a normalized CSV/TSV plus a metadata JSON.
- A clear distinction between Fermi-level alignment and vacuum-level alignment; do not imply they are interchangeable.

**CST-5 — Density grid and vacuum-reference utilities**

Implement reusable checks/operations for:
- Cube atom count, grid dimensions, grid origin, voxel vectors and coordinate consistency.
- Compatibility checks before density subtraction.
- Density difference using matching grids and atom mappings.
- Sampling a declared vacuum region and detecting whether a stable potential plateau exists.
- Applying a documented energy-reference shift to PDOS only when the potential quantity and zero are physically validated.

The developer must first verify which CP2K cube/potential output represents the electrostatic reference required by the chosen alignment method. Do not assume that any Hartree cube is automatically the correct vacuum level. If the available output does not provide a defensible reference, stop and document the limitation rather than silently using it.

**CST-6 — ASE vibration/thermochemistry wrapper**

Reuse ASE's tested vibration and thermochemistry implementations rather than reimplementing statistical mechanics formulas. Add a thin, versioned API only where it is useful for reusable post-processing:
- Input frequencies/masses/atom selection and declared constraints.
- Imaginary/near-zero mode checks and explicit policy.
- ZPE and thermal/entropic corrections with temperature and unit metadata.
- Clear labels distinguishing adsorbate-only/frozen-support subspace from full-system normal modes.
- Gas-phase ideal-gas treatment only when the input includes the required geometry, masses, symmetry/rotational data and conventions.

Do **not** attempt to make ASE's local calculator execution perform the remote HPC task farm. Remote displacement submission and force reassembly belong to Computation--pipeline.

**CST-7 — Configurable publication plotting profile**

Add a profile-driven style API rather than one hardcoded journal style. It must support white/opaque and transparent backgrounds, figure dimensions, raster/vector outputs, font family/size, axis and tick rules, line widths, panel labels, colour palette and output metadata. Keep old defaults/backward compatibility. Automated figure verification can be added as a reusable utility, but project-specific figure composition remains in Computation--pipeline.

### 3.3 chem-scitoolkit tests required

- Legacy builder/parser/style APIs still pass.
- Build a finite-system input with explicit per-KIND pseudo/basis, UKS, multiplicity, smearing and MT; validate syntax with the selected linter and with a real executable/version smoke test if available.
- Missing pseudopotential/basis references fail before submission.
- Parser fixtures cover normal completion, SCF-only completion, incomplete/truncated output, fatal error, normal GEO_OPT completion, GEO_OPT not converged, ENERGY_FORCE output, and missing energy.
- Hirshfeld and true-Bader data are never conflated.
- Bader parser handles wrong atom count, bad charge sum, wrong atom order and missing output.
- PDOS fixtures cover spin-polarized output, multiple atomic projections, units, grid mismatch and broadening.
- Cube mismatch tests cover grid dimensions, origin, voxel vectors, atoms/coordinates and incompatible data.
- Vacuum plateau detector passes a synthetic stable plateau and rejects a sloped/non-uniform region.
- ASE thermochemistry tests cover known harmonic frequencies, temperature, imaginary modes and unit conversions.
- Style tests confirm configured font sizes/background/export formats while preserving defaults.

## 4. Data_analysis — concrete findings

### 4.1 Current relevant code

| File | Existing capability observed | Gap / risk |
|---|---|---|
| `.agents/skills/scientific-data-analysis/SKILL.md` | Script-first intake, artifact preservation, hashes, schemas, evidence packages, cache and scientific synthesis policy | It correctly says a format/reader status must reflect tests; CP2K cannot be presented as supported while its registry status remains planned |
| `registries/formats.json` | Contains a `cp2k_output` entry | Explicitly sets `adapter_status: planned` and `validation: not_sample_validated` |
| `registries/readers.json` | Contains available and candidate readers such as standard-library, OpenReadout, xraylarch, etc. | No validated CP2K output, CP2K PDOS, or CP2K cube-reader route is registered as production-ready |
| `registries/operations.json` | Separate operation registry with explicit deterministic/model-required fields | No complete set of DFT operations for CP2K run summaries, PDOS normalization, density-grid validation, or calculation-result provenance is registered |
| `schemas/artifact.schema.json` | Source/generated custody, SHA256, format IDs, parser status, quality status, eligibility and use status | Reusable as-is; extend only if a concrete DFT artifact field cannot be represented |
| `schemas/analysis_run.schema.json` | Input/output artifact IDs, operation version, parameters, software, status, hashes, provenance | Reusable as-is for deterministic DFT post-processing records |
| `src/data_analysis/inventory.py`, `cache.py`, `evidence.py` | General inventory/cache/evidence packages | Reuse; do not duplicate in the new repository |

### 4.2 Required Data_analysis remediation

**DA-1 — DFT artifact format registration**

Register CP2K logs and outputs, CP2K PDOS families, CP2K cube grids, ASE structures/trajectories, and force/displacement result tables as distinct artifact types where appropriate. Detection must use file content/signatures and associated context, not extension alone. Record parser status and validation assurance honestly.

**DA-2 — Reader/adapter registration**

Register the selected CP2K parser route and its version. The numerical parser itself should be provided by chem-scitoolkit or a documented external parser; Data_analysis should not implement a parallel CP2K parser.

**DA-3 — DFT operation registration**

Define deterministic operation entries for the supported normalized outputs, such as CP2K run summary parsing, PDOS normalization metadata, cube grid validation, and calculation-result packaging. These records should reference the actual worker/adapter and version and should not duplicate physics calculations already owned by chem-scitoolkit.

**DA-4 — Evidence/provenance linking**

Ensure each derived DFT record connects to:
- Input CP2K input artifact and SHA256.
- Output log and relevant output artifacts.
- Structure artifact and approved model hash.
- Executable, basis/pseudopotential and analysis versions.
- Upstream HPC task/job reference.
- Parser/operation version and parameters.
- Warnings, assumptions, and QC status.

Reuse current artifact and analysis-run schemas unless testing proves an extension is necessary. Do not create a new database or a second project-level workflow state machine.

### 4.3 Data_analysis tests required

- Format detection distinguishes CP2K logs from arbitrary `.out` files using content.
- PDOS/cube families are grouped and linked correctly.
- Reader and operation status cannot be marked implemented/validated without the corresponding tests.
- Input/output hashes and source relationships survive normalization.
- Partial/malformed CP2K outputs are represented as partial/failed, not successful.
- Synthetic fixtures cover parser and metadata paths; any production-validation claim must cite a real CP2K reference output and matching version.

## 5. HPC Skills — concrete findings

### BeiLong_HPC

The inspected Skill has a defined local-workspace/remote-execution boundary, explicit cluster-specific path and SSH policies, Slurm submission/monitoring, checksums, a job-record helper, resource advisor, bounded diagnosis, tests, and software smoke-test documentation. Its job record requires scheduler and application-level completion evidence. Keep it private and reuse those functions.

### UCAS_hpc

The inspected Skill has its own SSH/SCP/Slurm contract, software catalogue, selective transfer/checksum workflow, Slurm state/exit-code/application-marker logic, job record, resource advisor, and unit/smoke validation. Keep it private and reuse those functions.

### HPC remediation decision

No mandatory upstream feature addition is justified from the inspected code. The two Skills intentionally differ in connection invocation, remote path policy, and record locations. The pipeline should supply two narrow adapters that translate those differences into one internal interface.

Only if a mock contract test or read-only integration test proves that a required operation cannot be performed through the existing documented scripts should a small upstream compatibility PR be proposed. Do not change cluster profiles, connection configuration, paths, permissions, or operational policies as part of this preparation task.

## 6. External reusable components and Skills

The following existing components should be evaluated/reused rather than reimplemented:

| Component | Intended reuse | Validation caution |
|---|---|---|
| ASE | Atomic structures, file I/O, CP2K calculator interface, finite-difference vibration and thermochemistry | The standard local ASE calculator is not a substitute for the project's remote Slurm task batching |
| RDKit | Organic ligand connectivity, bond topology and conformer generation | Does not solve all transition-metal coordination chemistry |
| molSimplify | Optional local coordination geometry construction/reference | Confirm the actual ligand/metal coordination pattern; may not build the entire support-cluster model |
| cp2k-input-tools | CP2K input parsing, generation, syntax lint and basis/potential data-file lint | Linting does not prove executable compatibility or scientific validity |
| cp2k-output-tools | CP2K parser utilities and PDOS broadening/export | Verify exact output variants and preserve all projection/spin metadata |
| pymatgen CP2K interfaces | Independent output/PDOS cross-check where appropriate | Avoid maintaining duplicate primary parsers |
| Multiwfn / Bader implementations | Actual electron-density partitioning | Confirm output convention, atom order, grid and charge accounting |
| Matplotlib | General rendering | Use chem-scitoolkit's configurable style profile |
| VESTA / VMD | 3D structural/volumetric inspection and figure generation | Project-specific exports and QC still need orchestration |

The public `SFETNI/Deep-Matter-Chem-Skills` includes CP2K, ASE, AiiDA and DFT-convergence Skills. Its CP2K workflow is labelled draft and lists CP2K 2023.2 in its tested-version metadata. Use only as a design/reference checklist after license and revision inspection; do not copy blindly or treat it as validated against CP2K 2025.2.

AiiDA and its CP2K plugin provide an established provenance/workflow option, but are not mandatory for this initial, relatively small campaign. Do not introduce AiiDA, atomate2, jobflow, FireWorks or another orchestration service in parallel with the planned lightweight controller unless the owner approves a documented architecture change.

## 7. Classification legend

- **REUSE_AS_IS:** Existing code/contract fits; test/invoke without changing ownership.
- **REUSE_WITH_ADAPTER:** Existing code is useful but needs a small compatibility wrapper in the new repository or a narrow upstream interface addition.
- **EXTEND_UPSTREAM:** A reusable capability belongs in an existing Skill and must be added there with backward-compatible tests.
- **IMPLEMENT_IN_PIPELINE:** Capability is orchestration, gate, cross-backend logic, or project-specific policy.
- **EXTERNAL_TOOL:** Prefer an established external program/library.
- **NOT_VALIDATED:** Code exists but its claimed behavior has not been adequately tested against representative outputs.
- **NOT_REQUIRED:** No implementation is needed for the initial pipeline.

## 8. Audit limitations

- This was a targeted source and test-structure review, not a full execution of all unit tests in all repositories.
- No production DFT or HPC jobs were submitted.
- The live installed version and exact CP2K 2025.2 keyword support on each cluster still require a later read-only/software-validation check.
- The existence of Multiwfn, Bader, VESTA, or other executables on a user's machine/cluster must be detected at runtime; this audit does not assume installation.
- No proprietary or private operational data from the two HPC repositories should be copied into the public repository.
