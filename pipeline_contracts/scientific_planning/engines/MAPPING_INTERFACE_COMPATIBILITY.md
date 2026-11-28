# Engine planners: Mapping interface and Agent B compatibility

Date: 2026-11-28

## Ownership and schema boundary

This package does **not** define a second Planning Core schema, edit contracts,
or create/modify a CalculationPlan. Every public planner accepts a read-only
Python Mapping and returns ordinary dictionaries, lists and scalars. The mappings
below are integration guidance, not a frozen JSON Schema or persisted contract.
Agent B owns the authoritative Planning Core model and translation into its fields.

No external executable, calculator, HPC service or third-party Skill is invoked.

## Input mapping

Minimum routing fields:

~~~python
request = {
    "engine": "cp2k",
    "task_type": "cp2k.geo_opt",
    "software_version": "2025.2",  # declaration only; not runtime verification
    "structure": {
        "atom_count": 48,
        "system_type": "slab",
        "periodicity": "XY",
        "cell": {"a": 18.0, "b": 18.0, "c": 28.0}
    },
    "sources": [
        {
            "source_kind": "user_explicit",
            "source_ref": "frozen-docx-sha256:page-8/table-2",
            "fields": {
                "xc_functional": {"value": "PBE", "rationale": "Explicit source method"},
                "dispersion": {"value": "D3(BJ)", "source_ref": "paper:SI:Table-S2"}
            }
        }
    ],
    "resource_profile": {
        "profile_id": "owner-verified-site-profile",
        "verified": True,
        "source_ref": "local-resource-profile-record",
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "allocation": {
            "nodes": 1, "mpi_ranks": 32, "openmp_threads": 1, "gpu_count": 0,
            "memory_gb": 128, "walltime_seconds": 3600, "scratch_gb": 100
        }
    }
}
~~~

An SCCS request should explicitly include top-level feature routing:

~~~python
request["features"] = ["sccs"]
~~~

Source kinds and priority:

1. `user_explicit`
2. `frozen_source` (`frozen_docx`, `paper`, `si` are aliases)
3. `approved_profile` (`project_profile` and `policy` are aliases; `approved: true` is mandatory)
4. `capability_rule` (`rule_verified: true` and exact `verified_for_version` are mandatory)
5. `candidate` (comparison only; never selected automatically)

A `source_ref` should be a stable evidence pointer: document SHA plus page/table/paragraph,
a project-profile path plus revision, or an explicit user-decision record. Each field
may be a scalar or a mapping with `value`, `rationale`, `uncertainty`,
`applicability`, and `approval_required`. Conflicting values at the same highest
priority return `CONFLICT`.

Missing dispersion/solvation never means “none”. Missing basis/potential/cutoff/SCF
values are not filled. A candidate list is not a selected method. An explicit
no-dispersion or no-solvent decision must itself have a source.

## Resource mapping

Allocation values are accepted only from an engine/task-specific profile with
`verified: true` and a `source_ref`. Required allocation keys are:
`nodes`, `mpi_ranks`, `openmp_threads`, `gpu_count`, `memory_gb`,
`walltime_seconds`, and `scratch_gb`.

A historical benchmark is exposed only as a reference when all match exactly:
engine, task type, software version, atom count, method fingerprint, and hardware
fingerprint. It is not extrapolated and does not replace a local resource profile.
Without a complete verified profile, real execution preflight remains blocked.
No numeric resource estimate is synthesized.

## Output mapping

`build_engine_planning(request)` returns:

- `capability_route`: software support separated from Pipeline adapter status and real-plan permission
- `method_plan`: field-level value, provenance, source reference, applicability, rationale, uncertainty, approval requirement and status
- `resource_plan`: verified allocation or missing-resource blockers
- `qc_contract`: task-specific evidence contract
- flags stating that this plugin does not construct CalculationPlan or execute a calculation

Agent B should map these dictionaries into the authoritative Planning Core schema and
retain unknown fields, blockers and provenance rather than silently dropping them.

## Current CalculationPlan compatibility at PR #5 HEAD

The inspected PR #5 CalculationPlan is version 1.0. Its allowed operations currently
contain `cp2k.geo_opt`, `cp2k.energy`, and `dft.artifact.read`. Its CP2K method
validator requires `xc`, `basis_set`, `pseudopotential`, `cutoff_ry`,
`rel_cutoff_ry`, SCF `method/eps_scf/max_scf`, `charge`, `multiplicity`,
`kind_definitions`, basis/potential file names, Poisson solver, cell/Poisson
periodicity, UKS and coordinate-centering policy.

| Planner field | Current CalculationPlan target | Compatibility note |
|---|---|---|
| `xc_functional` | `method.xc` | Direct value mapping |
| `dispersion` | No stable required field | Preserve in Agent B schema/metadata; never discard |
| `basis_set` | `method.basis_set` and per-element `method.kind_definitions.*.basis_set` | Element-specific mapping may be required |
| `pseudopotential` | `method.pseudopotential` and per-element `method.kind_definitions.*.potential` | Keep authorized local file references separately |
| `cutoff_ry` | `method.cutoff_ry` | Direct value mapping |
| `rel_cutoff_ry` | `method.rel_cutoff_ry` | Direct value mapping |
| `scf.method` | `method.scf.method` | Direct value mapping |
| `scf.eps_scf` | `method.scf.eps_scf` | Direct value mapping |
| `scf.max_scf` | `method.scf.max_scf` | Direct value mapping |
| `charge` | `method.charge` | Direct value mapping |
| `multiplicity` | `method.multiplicity` | Direct value mapping |
| `spin`, `uks` | `method.uks` plus explicit spin metadata | Spin is not an independent required key in current Plan |
| `cell` | `structure.cell` | Current plan validates a/b/c and alpha/beta/gamma |
| `periodicity` | `method.cell_periodicity` and `method.poisson_periodicity` | Preserve distinction |
| `poisson_solver` | `method.poisson_solver` | Direct value mapping |
| `kpoints`, `smearing` | No canonical current required fields | Keep as pending schema extension where applicable |
| `solvation.implicit`, `solvation.explicit` | No canonical current required fields | SCCS/explicit solvent cannot pass current adapter gate |
| `software_version` | Each calculation's `tool_version` | Use exact version, not a “latest” alias |
| Resource allocations | `execution.backend` and `execution.resources.profile` | Keep site-specific allocation in the local runtime profile |

The current real adapter preflight accepts only `cp2k.geo_opt` and `cp2k.energy`,
requires a local runtime configuration/resource profile, and calls the existing
chem-scitoolkit `validate_cp2k_input` and `validate_cp2k_output` functions.
WorkflowController creates ENERGY only after GEO_OPT convergence and a verified
optimized-structure Artifact are available. The adapter is code-level implemented,
but it has not been verified against a live cluster or production CP2K calculation.

## QC integration

The QC contracts preserve six independent gates:

1. output/Artifact completeness
2. normal termination
3. technical convergence
4. structural/numerical plausibility
5. scientific conclusion validity
6. explicit user acceptance

Levels 5 and 6 are separate records. Neither can be inferred from a return code,
scheduler state, energy value or optimizer convergence. The NEB/BAND contract
rejects a transition-state claim based only on the highest-energy image; an
independent frequency job, one chemically meaningful imaginary mode and mode
alignment evidence are required. If IRC connectivity is claimed, it also needs
its own evidence.

## Upstream research and licensing

- `jianzushen/Computational-chemistry-skill`, version 1.1.0, MIT, reviewed at
  commit `4ea66ea8633e4a65d5b9041928b363b0375bb81b`. Reviewed workflow decomposition
  and provenance/approval practices only; no code or prose copied.
- `JCLiuGroup/AI-Computational-Chemist`, CC BY-NC 4.0, reviewed at commit
  `e27b555ecfee3a7b66472c19c93b01ad0a1ccae1`. Conceptual research only; no code
  or prose copied.
- No third-party code was vendored. Software-specific versions, licenses and
  documentation links are recorded in `capability_registry.json`.


## CP2K MethodPlan → CalculationPlan v1.0 projection

The independent adapter is exported as:

~~~python
from pipeline_contracts.scientific_planning.engines import (
    plan_method,
    to_cp2k_calculation_plan_method,
)
~~~

The request passed to plan_method may include calculation_plan_context: the actual
CalculationPlan v1.0 envelope fields excluding method (plan identifiers, scientific
question, project root, structure, calculations, execution, analysis, quality gates,
retry policy and metadata). The projection replaces context.method with the exact
REQUIRED_METHOD projection and invokes the existing CalculationPlan.validate().
It does not create a second validator and does not insert synthetic envelope values.

Mapping rules:

| CalculationPlan v1.0 method key | MethodPlan source | Rule |
|---|---|---|
| xc | xc_functional | Direct, provenance required |
| basis_set / pseudopotential | basis_set / pseudopotential | Direct, provenance required |
| cutoff_ry / rel_cutoff_ry | Same names | Direct, provenance required |
| scf | scf.method, scf.eps_scf, scf.max_scf | Each nested value requires provenance |
| charge / multiplicity / uks | Same names | Direct, provenance required |
| kind_definitions | kind_definitions | Explicit per-element definitions; never derived from a generic basis/potential label |
| basis_file_name / potential_file_name | Same names | Explicit file basenames; never inferred |
| poisson_solver | poisson_solver | Explicit, provenance required |
| cell_periodicity | cell_periodicity or periodicity | periodicity is an alias only for the cell boundary setting |
| poisson_periodicity | poisson_periodicity | Independent source required; never copied from cell_periodicity |
| center_coordinates | center_coordinates | Explicit boolean, provenance required |

The structure cell geometry remains in calculation_plan_context.structure.cell, not
inside the CalculationPlan method mapping. Projection returns source provenance per
target key and preserves fields not represented by REQUIRED_METHOD in preserved_fields.
This sidecar includes dispersion, spin, solvation choices, k-points, smearing and
keyword compatibility; these are not silently discarded or added as invented v1.0
method keys.

A source-backed NOT_APPLICABLE record has the form:

~~~python
{
    "status": "NOT_APPLICABLE",
    "value": None,
    "rationale": "Explicit reason from the source/policy",
    "source_ref": "stable-document-or-decision-reference",
}
~~~

The source_ref may be inherited from the containing source record when the field
record does not repeat it. Ordinary None remains MISSING. An explicitly N/A field
can be preserved for an optional scientific feature such as dispersion/solvation,
but it cannot satisfy any CalculationPlan.REQUIRED_METHOD key. Such a projection
returns BLOCKED rather than substituting another scientific value.

Deterministic MethodPlan status priority (highest first) is:
BLOCKED_MISSING_METHOD_FIELDS > BLOCKED_SOURCE_CONFLICT >
BLOCKED_RUNTIME_VERSION_UNVERIFIED > PROPOSED > METHOD_FIELDS_RESOLVED.
METHOD_FIELDS_RESOLVED is emitted only with an empty blocker list.

The projection result is READY only when all REQUIRED_METHOD fields are sourced,
the real CalculationPlan envelope is present, and CalculationPlan.validate() passes.
Otherwise method is null and blockers explain why.
