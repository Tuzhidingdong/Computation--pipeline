# Upstream Remediation Status

**Current state:** Instruction and audit published; implementation not yet started by the user's Agent.  
**Governing instruction:** [UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md](UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)  
**Audit:** [EXISTING_SKILL_CAPABILITY_AUDIT.md](EXISTING_SKILL_CAPABILITY_AUDIT.md)

## Baseline revisions

| Repository | Audited revision | Work branch | PR | Status |
|---|---|---|---|---|
| chem-scitoolkit | `87a061b309bbb9fdf4461d2d1d2873dbfd8681fb` | Not created | — | NOT STARTED |
| Data_analysis | `5684c6a762ac09caf24661c987b2e7a97eb0e2e7` | Not created | — | NOT STARTED |
| BeiLong_HPC (private) | `40ce15a9285e94f4abf1418361387e90e850a899` | No change planned | — | AUDIT REQUIRED |
| UCAS_hpc (private) | `ebde5c1e76432d7e0d6728da804fb62dc5f84583` | No change planned | — | AUDIT REQUIRED |

## Requirement tracker

| ID | Requirement | Target | Status | Evidence |
|---|---|---|---|---|
| CST-1 | Finite/non-periodic CP2K input builder | chem-scitoolkit | NOT STARTED | — |
| CST-2 | Task-aware CP2K output validation | chem-scitoolkit | NOT STARTED | — |
| CST-3 | Distinguish true Bader from calibrated Hirshfeld estimate | chem-scitoolkit | NOT STARTED | — |
| CST-4 | CP2K PDOS parsing and normalization | chem-scitoolkit | NOT STARTED | — |
| CST-5 | Cube grid, density-difference and vacuum-reference validation | chem-scitoolkit | NOT STARTED | — |
| CST-6 | ASE vibration/thermochemistry wrapper | chem-scitoolkit | NOT STARTED | — |
| CST-7 | Configurable publication figure profiles | chem-scitoolkit | NOT STARTED | — |
| DA-1 | DFT artifact format registration | Data_analysis | NOT STARTED | — |
| DA-2 | Reader and operation registration | Data_analysis | NOT STARTED | — |
| DA-3 | DFT provenance/evidence linking | Data_analysis | NOT STARTED | — |
| HPC-1 | BeiLong adapter mapping | Computation--pipeline | NOT STARTED | — |
| HPC-2 | UCAS adapter mapping | Computation--pipeline | NOT STARTED | — |
| EXT-1 | External tool/license/version inventory | Computation--pipeline | NOT STARTED | — |
| INT-1 | Cross-repository mock contract tests | Computation--pipeline | NOT STARTED | — |

## Execution notes

- This is a tracker, not evidence that any remediation has been performed.
- The two HPC Skill repositories are private. Do not publish their cluster-specific connection, path, account or host configuration.
- Do not submit production DFT/HPC jobs during remediation.
- The user reviews upstream PRs; do not merge them automatically.
