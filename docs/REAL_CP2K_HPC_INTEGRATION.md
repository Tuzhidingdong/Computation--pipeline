# Real CP2K → HPC Skill → Data_analysis integration

## Scope and execution boundary

This adapter path is intended for the bounded GEO_OPT → ENERGY workflow:

1. Resolve or intake the source structure through the public Data_analysis API and verify its registered SHA-256.
2. Read the structure with ASE and call the installed chem-scitoolkit CP2KInputBuilder.build_finite_system().
3. Validate the generated input with validate_cp2k_input() / cp2klint.
4. Write a unique local derived input under data/derived/, register it with register_derived_artifact() using the structure Artifact ID as its parent, and resolve it again through Data_analysis.
5. Stage the input, local basis/pseudopotential files, and Slurm script through the selected HPC Skill adapter. Compare local and remote SHA-256 before submission.
6. Persist the submission intent and opaque remote work directory in SQLite, then call the Skill's documented sbatch command. Persist the returned Slurm Job ID immediately.
7. Query the same Job ID, selectively retrieve only the declared outputs/logs, verify local hashes, and register retrieved source files through register_inputs().
8. Invoke chem-scitoolkit.validate_cp2k_output(). GEO_OPT is allowed to add ENERGY only when normal termination, SCF convergence, CP2K version and geometry-optimization completion are confirmed and the optimized-structure Artifact is registered.
9. Run the existing RealDataAnalysisAdapter against the registered CP2K output. It creates the Data_analysis Analysis Run, normalized derived output and Evidence Package using the existing DFT API.

No Artifact registry, parser, evidence database, SSH client or Slurm implementation is duplicated in Computation--pipeline.

**No live HPC connection or calculation was executed during this development phase.** CI uses injected subprocess runners and fake CST/HPC/Data_analysis APIs. Passing CI demonstrates the adapter contract and control flow, not the availability of the user's local installations, credentials, queues or scientific results.

## Local runtime configuration

The repository contains .pipeline/runtime.local.example.json. Copy it into the Data_analysis project:

~~~powershell
$ProjectRoot = "D:\path\to\your\Data_analysis_project"
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot ".pipeline") | Out-Null
Copy-Item ".pipeline\runtime.local.example.json" (Join-Path $ProjectRoot ".pipeline\runtime.local.json")
notepad (Join-Path $ProjectRoot ".pipeline\runtime.local.json")
~~~

.pipeline/runtime.local.json is Git-ignored. Do not commit it. Do not put credentials, private SSH host configuration or personal cluster directories into the example file or public plan.

The important settings are:

| Runtime field | Meaning |
|---|---|
| active_project_root | Local working Project root used for .pipeline/staging/ and the Skill-owned local Job Record files. This can differ from the Data_analysis project root. |
| data_analysis.project_root | Existing Data_analysis project root. It must exactly match CalculationPlan.project_root. |
| data_analysis.source_root | Local checkout/environment path exposing the approved data_analysis Python package. |
| chem_scitoolkit.source_root | Local checkout/environment path exposing my_sci_toolkit. |
| python_executable | Python interpreter used to invoke the upstream Job Record scripts. |
| hpc_backends.ucas / hpc_backends.beilong | Only the selected backend needs enabled: true; each contains its local Skill paths, executable paths and connection alias. |
| resource_profiles | Explicit nodes, tasks, CPUs/task, memory, time, partition, account and module. The plan selects one profile by name. |
| input_files.basis / input_files.potential | Local regular files for the exact basis_file_name and potential_file_name in the CalculationPlan. Both must be present in the same local directory so cp2klint --base-dir can resolve them. They are also staged to the remote task directory. |

The local basis/pseudopotential files are mandatory in this MVP. The generated CP2K input refers to the declared file names, not guessed installation paths.

### UCAS_hpc

Configure only the UCAS block:

- alias must be the existing SSH alias hpc.
- ssh_executable and scp_executable point to the installed Windows OpenSSH binaries.
- skill_root points to the local UCAS_hpc checkout; job_record_script and slurm_template must resolve inside that Skill root.
- remote_root, Account, Partition, module and resources must reflect the currently approved UCAS project configuration.
- The existing cp2k-2025.2-openmpi.slurm template is used as the base and only the declared task resources, input and output names are adapted.

The adapter does not add a custom -F SSH config for UCAS; it uses the pre-existing hpc alias as required by that Skill.

### BeiLong_HPC

Configure only the BeiLong block:

- alias must be bscc-a.
- ssh_config must point to the dedicated config_bscc_a; both SSH and SCP are invoked with -F config_bscc_a.
- skill_root, job_record_script, privacy_header_template, module_init_path and allowed_workspace_root point to the local Skill checkout and the user's locally configured permitted workspace.
- The Slurm job name remains exactly wcl. Logs remain generic and are retrieved from the Skill-defined hpc/logs/ directory.
- Each task gets an opaque remote work directory below the configured permitted workspace. The adapter rejects remote destinations outside that boundary.

Do not place the actual SSH config, credentials or private remote root into Git.

## Read-only preflight

From the repository working directory, run:

~~~powershell
$Plan = ".\examples\cp2k_geo_opt_energy_plan.json"
$Runtime = "D:\path\to\Data_analysis_project\.pipeline\runtime.local.json"

python -m pipeline_contracts.cli validate $Plan
python -m pipeline_contracts.cli preflight $Plan --runtime-config $Runtime
~~~

preflight performs local checks for the Data_analysis/CST APIs, structure file, ASE, cp2klint, configured Skill scripts/templates and the selected HPC backend. Its remote checks load the declared module and inspect the CP2K executable/version and the availability of Slurm commands. It does not call sbatch, create a job record, stage inputs, cancel jobs or retrieve output.

For a separate read-only connection check, substitute only values from the private runtime file.

UCAS:

~~~powershell
$SSH = "C:\Windows\System32\OpenSSH\ssh.exe"
& $SSH hpc "bash -lc 'source /etc/profile.d/modules.sh && module use /public/env/modules/apps && module use /public/env/modules/tools && module load cp2k/2025.2-openmpi && command -v cp2k.psmp && cp2k.psmp --version && command -v sbatch && command -v squeue && command -v sacct'"
~~~

BeiLong:

~~~powershell
$SSH = "C:\Windows\System32\OpenSSH\ssh.exe"
$Config = "$HOME\.ssh\config_bscc_a"
& $SSH -F $Config bscc-a "bash -lc 'test -d <configured_allowed_workspace_root> && test -r <configured_module_init_path> && source <configured_module_init_path> && module load <configured_cp2k_module> && command -v cp2k.psmp && cp2k.psmp --version && command -v sbatch && command -v squeue && command -v sacct'"
~~~

These checks read configuration and executable/version information only. They do not submit a job. Replace the angle-bracket placeholders with values already approved for that account; do not guess a remote path, module or resource profile.

## Approved execution commands

Only after the CalculationPlan and resource request have been reviewed and the read-only preflight is ready:

~~~powershell
python -m pipeline_contracts.cli plan $Plan
python -m pipeline_contracts.cli run $Plan --runtime-config $Runtime
~~~

--mock must be explicitly requested to run the simulator. Real mode never falls back to Mock.

Monitor a saved run:

~~~powershell
python -m pipeline_contracts.cli status WORKFLOW_RUN_ID --state-db STATE_DB_PATH
python -m pipeline_contracts.cli report WORKFLOW_RUN_ID --state-db STATE_DB_PATH --output workflow_report.json
python -m pipeline_contracts.cli resume WORKFLOW_RUN_ID --state-db STATE_DB_PATH --runtime-config $Runtime
~~~

## Recovery and status semantics

- A durable submission intent (opaque remote work directory, input byte hashes and timestamp) is written before sbatch.
- A Job ID is saved as soon as the submit command returns it, before the Skill Job Record is created or synchronized.
- A known Job ID is queried again on resume; it is never resubmitted by ordinary resume.
- If the sbatch response is lost, the adapter uses the backend's permitted Slurm work-directory reconciliation. If it cannot establish whether the job exists, it records SUBMISSION_UNKNOWN and stops. It does not issue another sbatch.
- Slurm COMPLETED is not sufficient. Allocation exit code 0, CP2K normal termination, SCF convergence, matching CP2K version and task-specific GEO_OPT completion are checked separately.
- FAILED_PERMANENT, FAILED_INFRASTRUCTURE and CANCELLED are terminal for ordinary resume. RETRY_WAIT also remains idle on ordinary resume. No scientific parameter is automatically changed.
- No automatic retry loop or explicit retry CLI operation is implemented in this MVP. RETRY_WAIT is not re-executed by ordinary resume.

## Artifact custody and known Data_analysis API boundary

- A plan that supplies structure.artifact_id is resolved and byte-hash-verified through resolve_artifact_path().
- An external source file is registered through register_inputs(), and the returned Artifact ID is resolved again before CST consumes the structure.
- Data_analysis' current public API does not expose a lookup-by-path/SHA function returning an existing Artifact ID. Therefore a path already inside data/original_received/ must be supplied as its existing structure.artifact_id; the adapter refuses to re-intake a managed original path. It does not inspect registry JSON.
- A new CP2K input is written under data/derived/ using a task-specific, collision-safe local filename and registered with its real parent structure Artifact ID. The uploaded HPC filename remains generic (input.inp).
- HPC output/log files are first staged under the local Project's .pipeline/staging/ area, outside Data_analysis storage. They are hash-verified, then passed to register_inputs() and resolved by their returned Artifact IDs.
- Analysis Run and Evidence Package creation remains owned by the official Data_analysis DFT provenance/evidence APIs.

## Verification and limitations

Current GitHub Actions evidence: 72 tests, 70 passed, 2 optional live upstream source tests skipped; compileall passed. The suite injects command runners and fake upstream APIs. It does not authenticate to either real cluster.

Not live-verified in this phase:
- the user's Windows paths, SSH aliases/configuration and credentials;
- the current cluster account/QoS/partition policy and module availability;
- a real sbatch / squeue / sacct lifecycle or real SCP transfers;
- the installed Data_analysis DFT reader selection and actual Evidence Package contents on the user's project;
- CP2K convergence or scientific validity for any actual system.

No production DFT/AIMD job was submitted by GitHub Actions or during this development work.
