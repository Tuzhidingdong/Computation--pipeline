# Scientific Planning Architecture v1 — Roadmap

**Baseline:** PR #5 Head `23e664acaae01ee55f77e252bfa6eb838bd35db1`  
**Rule:** prove a narrow vertical closure before adding multiple scientific algorithms. This roadmap does not authorize scientific parameter changes or resolution of project blockers.

## Development order

| Phase | Deliverable | Acceptance evidence | Not included |
|---|---|---|---|
| P0 — Architecture and contracts | This architecture, capability matrix, schemas, external license audit | JSON parse; schema/example structure validation; review of module mappings and safety invariants | No runtime algorithm or CI matrix expansion |
| P1 — Intent/ResearchPlan compiler | Frozen source/Manifest → ScientificIntent + one ResearchPlan; field-level EvidenceRefs; A/B/C decisions and missing-question list | Deterministic same-input hashes; contradictions block dependent decisions; no invented scientific values; minimum decisive questions | No model generation/method selection/dispatch |
| P2 — Project plugin isolation | Provider/registry seam for ProjectPlugin and model approval; eliminate direct CORR imports from generic orchestration/lifecycle through compatibility bridge | Generic tests run without importing CORR package; CORR v4.1 behavior and WP1 blockers unchanged | No new scientific algorithm |
| P3 — First executable vertical slice | Existing user-supplied validated model Artifact + source-backed/approved CP2K MethodPlan + one current GEO_OPT operation + QCPlan + existing Workflow/DA | Mock E2E first; frozen SHA and evidence lineage through resume; real execution only after exact local env preflight | No generated topology, solvent or TS |
| P4 — Molecule/conformer plugin | Generic molecular graph ingestion, atom mapping, conformers and independent model review | Golden structures, charge/spin evidence, duplicate policy, deterministic plugin version, QC | No surface or solvent claim |
| P5 — Crystal/surface/adsorption/interface plugins | Separate crystal, slab, adsorption, interface recipes and validators | Source/termination/cell/coverage/strain provenance; atom mapping; reviewer gate and convergence contract | No universal catalyst-model guesser |
| P6 — Method/capability registry | Engine/version/operation matrix; parameter mappings and license gates | Exact-version capability evidence plus input writer, runtime adapter, output parser and QC contract | No LLM-invented defaults |
| P7 — QC contract library | GEO_OPT/ENERGY first, then Frequency, NEB/Dimer/TS, AIMD, solvent preparation and analysis | Each task separates file/program/technical/structural/scientific/user acceptance and has failure fixtures | No global `exit code 0 = pass` |
| P8 — Resource planner | Site/software/task resource profiles, historical-job calibration, uncertainty intervals | Backtest against real recorded jobs, provenance, out-of-domain refusal, queue-bounded preflight | No precise runtime promises without calibration |
| P9 — Advanced methods | Explicit solvent packing then equilibration; implicit solvation; path/TS operations | Per-plugin input/output contracts, pinned software, method and structural QC; real regression datasets | No single generic solvent/TS algorithm |

## First minimum usable closure

Use a project where the user already supplied:
- frozen source document/Manifest with evidence hashes and locators;
- one exact validated structure Artifact, with topology, charge and spin supported by evidence;
- original method section or approved protocol that supplies every mandatory CP2K value;
- exact installed CP2K version, data files and license/site policy;
- approved resource profile or a bounded Mock profile.

Compiler steps:
1. Create ScientificIntent and one scientific question.
2. Compile one ResearchPlan work package and A/B/C decision records.
3. Bind an existing structure Artifact into ModelRecipe—no coordinate generation.
4. Fill every MethodPlan parameter from source/approved policy and verify exact capability.
5. Build one ExecutionPlan node for existing `cp2k.geo_opt`.
6. Attach its QCPlan: file, normal termination, geometry convergence, structural plausibility, scientific review, acceptance.
7. Deterministically compile/freeze the current CalculationPlan version.
8. Exercise WorkflowController in Mock first; label mock data explicitly as non-scientific.
9. Verify Data_analysis Artifact ID/SHA and Evidence Package lineage.

This is the first measurable closed loop. Do not start with automatic system reconstruction or broad method discovery.

## Solvent feature sequence

1. **Explicit packing plugin:** source molecular structures, counts/fractions, density or box, insertion region, PBC, tolerance and seed are explicit or policy-authorized.
2. **Packing QC:** molecule/atom counts, identity/topology, minimum distances, cell and PBC. Mark output as not equilibrated.
3. **Equilibration tasks:** only after force field/method, ensemble and conditions are authorized; use energy/temperature/density drift and sampling QC.
4. **Implicit solvation plugin:** exact engine/version, solvent/cavity settings, electrostatic boundary conditions, matched thermodynamic cycle and sensitivity.

Packing and implicit solvation are different scientific models and must not share a single `solvent=true` flag.

## Transition-state / path sequence

1. Validate and approve exact endpoint structures, hashes, method consistency and atom correspondence.
2. Build a reviewable initial path through a separately versioned path-construction plugin.
3. Add NEB only after writer, adapter, parser, per-image force QC and barrier validation exist.
4. Add Dimer as its own operation with explicit initialization and convergence contract.
5. Add TS refinement/frequency verification. A path maximum or converged Dimer alone is not proof of a first-order saddle.
6. Release downstream activation free-energy claims only after reaction-coordinate and scientific review.

## Every phase must preserve these invariants

- No CORR rules or profile values in generic modules; project rules are registered by plugin.
- No second WorkflowStore, Artifact Store, scheduler or general executor.
- Every material value has evidence, policy provenance, explicit N/A rationale, or remains missing.
- Plugin, schema, engine, parser and capability versions are pinned.
- Plan and artifact hashes freeze after approval; changed inputs create a new revision.
- Tests prove state/side-effect invariants, not just JSON serialization.
- No scientific defaults from external Skill examples.
- A phase advances only after its acceptance evidence and exact commit are recorded.
