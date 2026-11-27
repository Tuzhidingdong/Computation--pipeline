# Real Skills Integration — Agent B Handoff Checklist

**Status:** Pending Agent A upstream implementation and owner review  
**Prepared:** 2026-11-27

1. **chem-scitoolkit:** Read the actual Agent A branch/PR and its tests. Confirm the callable functions, signatures, accepted input artifact forms, normalized output fields, dependency/version and failure semantics. Bind `CSTAdapter.execute()` to those verified calls. Do not guess function names from the provisional `operation` values and do not copy CST algorithms into Pipeline.
2. **Data_analysis:** Inspect the actual DA-1/DA-2/DA-3 implementation and tests. Reuse its Artifact, Analysis Run, SHA-256, cache and Evidence records. Confirm how its reader/operation registry accepts an Artifact ID and returns an Analysis Run ID, outputs, warnings and QC. Do not create a second Artifact Store, DB, cache or evidence package implementation.
3. **Data_analysis PR #4:** Recheck PR #4's final merged state before binding managed references. If merged, use the merged read-only Artifact resolver/stream API and `scientific-evidence-export` contract exactly as implemented; preserve managed source bytes in place and pass only verified references. If still open/unmerged, do not depend on its branch code or replicate it in Pipeline.
4. **BeiLong_HPC:** Through authorized read-only inspection, map the Pipeline HPC Protocol to the Skill's actual preflight, staging, submission, scheduler status, job record, selective retrieval and checksum functions. Keep connection details and paths private. No production submission.
5. **UCAS_hpc:** Perform the same read-only mapping separately; do not assume its command syntax, remote path conventions or job-record schema match BeiLong_HPC.
6. **Status normalization:** Confirm which source fields prove scheduler completion, application success, output completeness and checksum validity. Preserve raw status/record evidence. Scheduler `COMPLETED` alone must remain `awaiting_validation`.
7. **Swap mocks for real adapters:** Keep contract tests unchanged where possible. Add narrow compatibility tests for actual upstream adapters and use synthetic fixtures only. Mock artifacts must never enter a real run.
8. **Acceptance boundary:** Do not mark CST/DA/HPC scientific integration complete until the matching real upstream PRs are reviewed/merged and the corresponding adapter tests run. No production DFT/AIMD/Slurm run is part of this handoff.
