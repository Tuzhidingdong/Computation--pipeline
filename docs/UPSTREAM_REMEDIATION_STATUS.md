# Upstream Remediation Status

**Current state:** Agent A is working on the upstream CST/DA requirements. Agent B has completed the separate Pipeline-side mock contract preparation; real upstream bindings remain pending.  
**Governing instruction:** [UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md](UPSTREAM_SKILL_GAP_REMEDIATION_TASK_v1.0.0.md)  
**Audit:** [EXISTING_SKILL_CAPABILITY_AUDIT.md](EXISTING_SKILL_CAPABILITY_AUDIT.md)  
**Agent B contract:** [SKILLS_ADAPTER_CONTRACT_V0.1.md](SKILLS_ADAPTER_CONTRACT_V0.1.md)

## Baseline revisions recorded by the existing audit

| Repository | Audited revision | Work branch / PR | Status |
|---|---|---|---|
| chem-scitoolkit | `87a061b309bbb9fdf4461d2d1d2873dbfd8681fb` | Agent A to report | Agent A implementation in progress; actual API binding pending |
| Data_analysis | `5684c6a762ac09caf24661c987b2e7a97eb0e2e7` | Agent A to report | Agent A implementation in progress; actual API binding pending |
| BeiLong_HPC (private) | `40ce15a9285e94f4abf1418361387e90e850a899` | No changes by Agent B | Mock adapter contract ready; exact per-Skill mapping remains read-only follow-up |
| UCAS_hpc (private) | `ebde5c1e76432d7e0d6728da804fb62dc5f84583` | No changes by Agent B | Mock adapter contract ready; exact per-Skill mapping remains read-only follow-up |

These are historical audit revisions, not refreshed upstream HEAD claims.

## Requirement tracker

| ID | Requirement | Target | Status | Evidence |
|---|---|---|---|---|
| CST-1 | Finite/non-periodic CP2K input builder | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-2 | Task-aware CP2K output validation | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-3 | Distinguish true Bader from calibrated Hirshfeld estimate | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-4 | CP2K PDOS parsing and normalization | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-5 | Cube grid, density-difference and vacuum-reference validation | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-6 | ASE vibration/thermochemistry wrapper | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| CST-7 | Configurable publication figure profiles | chem-scitoolkit | AGENT A IN PROGRESS | Real API not yet bound in Pipeline |
| DA-1 | DFT artifact format registration | Data_analysis | AGENT A IN PROGRESS | Real registry not yet bound in Pipeline |
| DA-2 | Reader and operation registration | Data_analysis | AGENT A IN PROGRESS | Real registry not yet bound in Pipeline |
| DA-3 | DFT provenance/evidence linking | Data_analysis | AGENT A IN PROGRESS | Must retain current Artifact/Analysis Run ownership; PR #4 remains an unmerged dependency |
| HPC-1 | BeiLong adapter mapping | Computation--pipeline | MOCK CONTRACT READY | `pipeline_contracts/adapters.py`, `pipeline_contracts/mocks.py`; real mapping pending read-only confirmation |
| HPC-2 | UCAS adapter mapping | Computation--pipeline | MOCK CONTRACT READY | `pipeline_contracts/adapters.py`, `pipeline_contracts/mocks.py`; real mapping pending read-only confirmation |
| EXT-1 | External tool/license/version inventory | Computation--pipeline | EXISTING BASELINE — RUNTIME/LICENCE VERIFICATION PENDING | `EXTERNAL_TOOL_SELECTION.md`; outside Agent B scope |
| INT-1 | Cross-repository mock contract tests | Computation--pipeline | COMPLETE — MOCK ONLY | `tests/test_contracts.py`, `tests/test_mock_integration.py` |

## Agent B scope and evidence (2026-11-27)

- Branch: `agent-b/pipeline-mock-contracts-20261127`.
- Only `Computation--pipeline` is modified. No upstream Skill source, branch or PR was changed.
- The mocks use opaque synthetic Artifact IDs and `mock://` URIs; no scientific values are generated.
- The HPC mock separates scheduler completion from application success and output integrity. Its hash assertion explicitly does not hash bytes.
- The standard-library test suite contains 10 contract/control-flow tests. Local scratch validation passed; the GitHub Actions run is reported separately after the branch push.
- A passing mock contract is not a real Skill or HPC integration test and is not scientific validation.

## Coordination notes

- `Data_analysis` Artifact, Analysis Run, cache and evidence ownership remains upstream. Do not create another Artifact Store, database, cache, or evidence registry in Pipeline.
- Data_analysis PR #4 was inspected read-only and is open/unmerged. Do not copy its managed Artifact path/stream access implementation or rely on it before its owner-reviewed merge.
- The HPC repositories are private. Do not place hosts, users, account names, keys, paths, connection commands or other operational configuration in this public repository.
- No production DFT/HPC task has been submitted.
