"""Skill-backed Slurm runtime adapters. SSH/SCP and Slurm remain owned by the upstream Skills."""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .models import (
    ArtifactRef, ContractError, HashVerification, HpcJobRecord, HpcPreflight,
    HpcStageResult, HpcState, HpcStatus, HpcTaskManifest, JobReference,
)


class HpcRuntimeError(RuntimeError):
    pass


class SubmissionUnknown(HpcRuntimeError):
    def __init__(self, remote_workdir: str, message: str):
        self.remote_workdir = remote_workdir
        super().__init__(message)


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class SubprocessCommandRunner:
    """Small injectable wrapper; every process has a timeout and bounded diagnostics."""
    def run(self, argv: Sequence[str], *, timeout: int) -> CommandOutput:
        try:
            result = subprocess.run(
                list(argv), capture_output=True, text=True, timeout=timeout,
                check=False, encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HpcRuntimeError(f"Command failed to start or timed out: {type(exc).__name__}: {exc}") from exc
        return CommandOutput(result.returncode, result.stdout[-12000:], result.stderr[-4000:])


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_token(value: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", str(value)):
        raise ContractError(f"{name} must be a plain filename/token")
    return str(value)


def _remote_path(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or any(c.isspace() for c in value):
        raise ContractError(f"{name} must be an absolute remote path without whitespace")
    parsed = PurePosixPath(value)
    if ".." in parsed.parts or "." in parsed.parts:
        raise ContractError(f"{name} contains an unsafe path component")
    return str(parsed)


def _remote_join(root: str, *parts: str) -> str:
    return _remote_path(root.rstrip("/") + "/" + "/".join(_safe_token(x, "remote path component") for x in parts),
                        "remote path")


def _quoted(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(item)) for item in command)


def _parse_job_id(value: str) -> str:
    first = value.strip().splitlines()[0].strip() if value.strip() else ""
    job_id = first.split(";", 1)[0]
    if not re.fullmatch(r"[0-9]+(?:_[0-9]+)?", job_id):
        raise HpcRuntimeError(f"sbatch returned an unrecognized Job ID: {first[:200]!r}")
    return job_id


def render_ucas_cp2k_script(
    template_text: str,
    *,
    resources: Mapping[str, Any],
    input_name: str,
    output_name: str,
    cp2k_data_dir: str | None = None,
) -> str:
    """Adapt the installed UCAS CP2K template while keeping its module/launcher body."""
    _safe_token(input_name, "input filename")
    _safe_token(output_name, "output filename")
    directives = {
        "job-name": "cp2k",
        "partition": str(resources["partition"]),
        "account": str(resources["account"]),
        "nodes": str(resources["nodes"]),
        "ntasks": str(resources["ntasks"]),
        "cpus-per-task": str(resources["cpus_per_task"]),
        "mem": str(resources["mem"]),
        "time": str(resources["time"]),
        "output": "slurm-%j.out",
        "error": "slurm-%j.err",
    }
    if resources.get("qos"):
        directives["qos"] = str(resources["qos"])
    lines = template_text.splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*#SBATCH\s+--([a-zA-Z0-9-]+)(?:=|\s+)(.*)$", line)
        if match and match.group(1) in directives:
            key = match.group(1)
            lines[index] = f"#SBATCH --{key}={directives[key]}"
            seen.add(key)
    missing = [key for key in directives if key not in seen]
    insertion = next((i + 1 for i, line in enumerate(lines) if line.startswith("#SBATCH")), 1)
    for key in missing:
        lines.insert(insertion, f"#SBATCH --{key}={directives[key]}")
        insertion += 1
    lines = [
        f'INPUT="{input_name}"' if re.match(r"^INPUT=", line) else
        f'OUTPUT="{output_name}"' if re.match(r"^OUTPUT=", line) else line
        for line in lines
    ]
    if cp2k_data_dir:
        data_dir = _remote_path(cp2k_data_dir, "remote CP2K data directory")
        insertion = next((i + 1 for i, line in enumerate(lines) if line.startswith("module load ")), None)
        if insertion is None:
            raise ContractError("UCAS template lacks a CP2K module load line")
        lines.insert(insertion, f"export CP2K_DATA_DIR={shlex.quote(data_dir)}")
    script = "\n".join(lines).rstrip() + "\n"
    if "#SBATCH --job-name=cp2k" not in script:
        raise ContractError("UCAS batch template did not retain a generic job name")
    return script


def render_beilong_cp2k_script(
    privacy_header: str,
    *,
    allowed_workspace_root: str,
    remote_workdir: str,
    resources: Mapping[str, Any],
    module_init_path: str,
    input_name: str,
    output_name: str,
    cp2k_executable: str = "cp2k.psmp",
    cp2k_data_dir: str | None = None,
) -> str:
    """Apply the upstream BSCC-A privacy header and its wcl directory rules."""
    root = _remote_path(allowed_workspace_root, "BeiLong allowed workspace")
    workdir = _remote_path(remote_workdir, "BeiLong job directory")
    if not (workdir.startswith(root.rstrip("/") + "/")):
        raise ContractError("BeiLong job directory must remain below the configured wcl workspace")
    _safe_token(input_name, "input filename")
    _safe_token(output_name, "output filename")
    module_parts = str(resources["module"]).split("/")
    if not module_parts or any(not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", part) for part in module_parts):
        raise ContractError("module name must be a slash-delimited safe module specifier")
    _safe_token(cp2k_executable, "CP2K executable")
    header_lines = []
    for line in privacy_header.splitlines():
        if re.match(r"^#SBATCH\s+--output=", line):
            line = f"#SBATCH --output={root}/hpc/logs/wcl-%j.out"
        elif re.match(r"^#SBATCH\s+--error=", line):
            line = f"#SBATCH --error={root}/hpc/logs/wcl-%j.err"
        header_lines.append(line)
    header = "\n".join(header_lines)
    if not re.search(r"(?m)^#SBATCH\s+--job-name=wcl\s*$", header):
        raise ContractError("BeiLong privacy header must set #SBATCH --job-name=wcl exactly")
    for key in ("output", "error"):
        match = re.search(rf"(?m)^#SBATCH\s+--{key}=(.+)$", header)
        if not match or not match.group(1).startswith(root.rstrip("/") + "/hpc/logs/"):
            raise ContractError(f"BeiLong privacy header must place Slurm {key} below wcl/hpc/logs")
    directives = [
        f"#SBATCH --nodes={resources['nodes']}",
        f"#SBATCH --ntasks={resources['ntasks']}",
        f"#SBATCH --cpus-per-task={resources['cpus_per_task']}",
        f"#SBATCH --mem={resources['mem']}",
        f"#SBATCH --time={resources['time']}",
        f"#SBATCH --partition={resources['partition']}",
        f"#SBATCH --account={resources['account']}",
    ]
    if resources.get("qos"):
        directives.append(f"#SBATCH --qos={resources['qos']}")
    data_dir = _remote_path(cp2k_data_dir, "remote CP2K data directory") if cp2k_data_dir else None
    cp2k_data_export = f"export CP2K_DATA_DIR={shlex.quote(data_dir)}" if data_dir else 'export CP2K_DATA_DIR="$SLURM_SUBMIT_DIR"'
    body = f"""
set -euo pipefail
umask 077
cd "$SLURM_SUBMIT_DIR"
MODULE_INIT={shlex.quote(module_init_path)}
test -r "$MODULE_INIT"
source "$MODULE_INIT"
module load {shlex.quote(str(resources['module']))}
{cp2k_data_export}
export OMP_NUM_THREADS="{int(resources['cpus_per_task'])}"
export OMP_PLACES=cores
export OMP_PROC_BIND=close
mpirun -np "{int(resources['ntasks'])}" {shlex.quote(cp2k_executable)} -i {shlex.quote(input_name)} -o {shlex.quote(output_name)}
"""
    return header.rstrip() + "\n" + "\n".join(directives) + "\n" + body.lstrip()


class SkillSlurmBackend:
    """Common execution mechanics; concrete classes preserve each Skill's connection rules."""

    backend_id = "abstract"
    job_name = "cp2k"

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        local_project_root: str | Path,
        command_runner: Any | None = None,
        command_timeout_seconds: int = 45,
    ):
        self.config = dict(config)
        self.local_project_root = Path(local_project_root).expanduser().resolve()
        self.runner = command_runner or SubprocessCommandRunner()
        self.command_timeout = max(5, min(int(command_timeout_seconds), 300))
        self.alias = str(self.config["alias"])
        self.ssh_executable = str(self.config["ssh_executable"])
        self.scp_executable = str(self.config["scp_executable"])
        self.remote_root = _remote_path(str(self.config["remote_root"]), "remote_root")
        self.job_record_script = Path(str(self.config["job_record_script"])).expanduser().resolve()
        self._task_context: dict[str, dict[str, Any]] = {}

    def _argv_prefix(self, executable: str, *, ssh: bool) -> list[str]:
        return [executable]

    def _ssh(self, command: Sequence[str], *, timeout: int | None = None) -> CommandOutput:
        remote = _quoted(command)
        argv = self._argv_prefix(self.ssh_executable, ssh=True) + [
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", self.alias, remote,
        ]
        result = self.runner.run(argv, timeout=timeout or self.command_timeout)
        if result.returncode:
            detail = (result.stderr or result.stdout or "no remote diagnostic").strip()[-1600:]
            raise HpcRuntimeError(f"{self.backend_id} SSH command failed ({result.returncode}): {detail}")
        return result

    def _scp(self, source: str, destination: str, *, timeout: int | None = None) -> CommandOutput:
        argv = self._argv_prefix(self.scp_executable, ssh=False) + [source, destination]
        result = self.runner.run(argv, timeout=timeout or self.command_timeout)
        if result.returncode:
            detail = (result.stderr or result.stdout or "no transfer diagnostic").strip()[-1600:]
            raise HpcRuntimeError(f"{self.backend_id} SCP failed ({result.returncode}): {detail}")
        return result

    def _run_local(self, argv: Sequence[str], *, timeout: int | None = None) -> CommandOutput:
        result = self.runner.run(argv, timeout=timeout or self.command_timeout)
        if result.returncode:
            detail = (result.stderr or result.stdout or "no local diagnostic").strip()[-1600:]
            raise HpcRuntimeError(f"{self.backend_id} Skill command failed ({result.returncode}): {detail}")
        return result

    def _new_remote_workdir(self, task_id: str) -> str:
        token = uuid.uuid4().hex[:24]
        if self.backend_id == "beilong":
            return _remote_join(self.remote_root, "hpc", "jobs", token)
        return _remote_join(self.remote_root, "pipeline-runs", token)

    def preflight(self) -> HpcPreflight:
        try:
            for local_path, label in (
                (Path(self.ssh_executable), "SSH executable"),
                (Path(self.scp_executable), "SCP executable"),
                (self.job_record_script, "upstream Job Record script"),
            ):
                if not local_path.is_file():
                    raise HpcRuntimeError(f"{label} is not a file: {local_path}")
            self._read_only_preflight()
            return HpcPreflight(
                backend_id=self.backend_id, ready=True,
                capabilities=("stage_inputs", "submit", "get_status", "get_record", "selective_retrieve", "sha256"),
            )
        except Exception as exc:
            from .models import Diagnostic, DiagnosticSeverity
            return HpcPreflight(
                backend_id=self.backend_id, ready=False,
                diagnostics=(Diagnostic("HPC_PREFLIGHT_UNAVAILABLE", str(exc)[:1200], DiagnosticSeverity.ERROR),),
            )

    def _read_only_preflight(self) -> None:
        raise NotImplementedError

    def attach_task(self, manifest: HpcTaskManifest, remote_workdir: str) -> None:
        root = _remote_path(remote_workdir, "remote_workdir")
        self._validate_remote_workdir(root)
        output_files = dict(manifest.payload.get("output_files") or {})
        for role, filename in output_files.items():
            _safe_token(str(role), "output role")
            _safe_token(str(filename), "output filename")
        self._task_context[manifest.task_id] = {
            "manifest": manifest, "remote_workdir": root, "output_files": output_files,
            "input_hashes": dict(manifest.payload.get("input_hashes") or {}),
            "local_files": list(manifest.payload.get("local_files") or []),
        }

    def _validate_remote_workdir(self, path: str) -> None:
        if not path.startswith(self.remote_root.rstrip("/") + "/"):
            raise ContractError("remote work directory is outside the configured remote root")
        if self.backend_id == "beilong":
            allowed = _remote_path(str(self.config.get("allowed_workspace_root") or ""), "allowed_workspace_root")
            if not path.startswith(allowed.rstrip("/") + "/"):
                raise ContractError("BeiLong remote work directory escapes the configured wcl workspace")

    def stage_inputs(self, task_manifest: HpcTaskManifest) -> HpcStageResult:
        local_files = list(task_manifest.payload.get("local_files") or [])
        if not local_files:
            raise ContractError("stage_inputs requires explicit local_files; recursive staging is disabled")
        remote_workdir = str(task_manifest.payload.get("remote_workdir") or self._new_remote_workdir(task_manifest.task_id))
        self._validate_remote_workdir(remote_workdir)
        local_hashes: dict[str, str] = {}
        for item in local_files:
            if not isinstance(item, Mapping) or set(item).difference({"path", "name"}):
                raise ContractError("local_files entries must contain only path and name")
            supplied = Path(str(item.get("path") or "")).expanduser()
            if supplied.is_symlink():
                raise ContractError(f"staged input must not be a symlink: {supplied}")
            source = supplied.resolve(strict=True)
            if not source.is_file():
                raise ContractError(f"staged input is not a regular file: {source}")
            name = _safe_token(str(item.get("name") or source.name), "staged filename")
            local_hashes[name] = sha256_file(source)
        remote_directories = [remote_workdir]
        if self.backend_id == "beilong":
            allowed = str(self.config["allowed_workspace_root"]).rstrip("/")
            remote_directories.append(allowed + "/hpc/logs")
        mkdir_script = "umask 077 && mkdir -p -- " + " ".join(shlex.quote(x) for x in remote_directories) + " && chmod 700 " + " ".join(shlex.quote(x) for x in remote_directories)
        self._ssh(["bash", "-lc", mkdir_script])
        for item in local_files:
            source = str(Path(str(item["path"])).expanduser().resolve(strict=True))
            name = _safe_token(str(item.get("name") or Path(source).name), "staged filename")
            remote_file = remote_workdir + "/" + name
            self._ssh(["test", "!", "-e", remote_file])
            self._scp(source, f"{self.alias}:{remote_file}")
            remote_hash_output = self._ssh(["sha256sum", "--", remote_file]).stdout.strip()
            remote_hash = remote_hash_output.split()[0].lower() if remote_hash_output else ""
            if remote_hash != local_hashes[name]:
                raise HpcRuntimeError(f"SHA-256 mismatch after uploading {name}; job was not submitted")
        self.attach_task(task_manifest, remote_workdir)
        self._task_context[task_manifest.task_id]["input_hashes"] = local_hashes
        return HpcStageResult(task_manifest.task_id, task_manifest.input_artifacts, remote_workdir)

    def submit(
        self,
        task_manifest: HpcTaskManifest,
        *,
        on_submission_intent: Callable[[Mapping[str, Any]], None] | None = None,
        on_job_submitted: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> JobReference:
        context = self._task_context.get(task_manifest.task_id)
        if context is None:
            raise ContractError("stage_inputs must complete before submit")
        workdir = context["remote_workdir"]
        job_script = _safe_token(str(task_manifest.payload.get("job_script_name") or "job.slurm"), "job script name")
        job_name = self.job_name
        details = {
            "backend_id": self.backend_id, "remote_workdir": workdir,
            "input_hashes": dict(context["input_hashes"]), "submission_time": datetime.now(timezone.utc).isoformat(),
            "job_name": job_name,
        }
        if on_submission_intent:
            on_submission_intent(details)
        command = ["bash", "-lc", "cd " + shlex.quote(workdir) + " && umask 077 && sbatch --parsable " + shlex.quote(job_script)]
        try:
            output = self._ssh(command).stdout
            job_id = _parse_job_id(output)
        except Exception as exc:
            reconciled = self._reconcile_submission(workdir, str(details["submission_time"]))
            if reconciled:
                job_id = reconciled
            else:
                raise SubmissionUnknown(
                    workdir,
                    "The sbatch response was lost and no matching job could be reconciled by its unique working directory. "
                    "The workflow is SUBMISSION_UNKNOWN; do not resubmit.",
                ) from exc
        if on_job_submitted:
            on_job_submitted(job_id, details)
        try:
            self._create_upstream_job_record(task_manifest, job_id, context)
        except Exception as exc:
            # The Job ID is already durable. Record creation trouble must not
            # cause another sbatch or be misclassified as a scientific failure.
            context["job_record_warning"] = f"{type(exc).__name__}: {exc}"
        return JobReference(job_id, task_manifest.task_id, self.backend_id)

    def _reconcile_submission(self, workdir: str, submission_time: str) -> str | None:
        try:
            live = self._ssh(["squeue", "--noheader", "--format=%i|%Z"]).stdout
            for line in live.splitlines():
                fields = line.split("|", 1)
                if len(fields) == 2 and fields[1].strip().rstrip("/") == workdir.rstrip("/"):
                    return _parse_job_id(fields[0])
            started = submission_time[:19].replace("T", " ")
            completed = self._ssh([
                "sacct", "-n", "-P", "-S", started, "--format=JobIDRaw,WorkDir",
            ]).stdout
            for line in completed.splitlines():
                fields = line.strip().split("|")
                if len(fields) >= 2 and fields[1].strip().rstrip("/") == workdir.rstrip("/"):
                    return _parse_job_id(fields[0])
        except Exception:
            return None
        return None

    def _create_upstream_job_record(
        self, task_manifest: HpcTaskManifest, job_id: str, context: Mapping[str, Any]
    ) -> None:
        payload = dict(task_manifest.payload)
        resources = dict(payload.get("resources") or {})
        local_files = list(context["local_files"])
        local_primary = next(
            (str(x["path"]) for x in local_files if x.get("name") == payload.get("input_filename")),
            str(local_files[0]["path"]),
        )
        local_script = next(
            (str(x["path"]) for x in local_files if x.get("name") == payload.get("job_script_name")),
            "",
        )
        if not local_script:
            raise HpcRuntimeError("local staged job script was not supplied; refusing incomplete Skill Job Record")
        argv = [
            str(payload.get("python_executable") or sys.executable), str(self.job_record_script), "create",
            "--project-root", str(self.local_project_root), "--job-id", job_id,
            "--software", "CP2K", "--module", str(resources["module"]),
            "--primary-input", local_primary, "--script", local_script,
            "--remote-dir", str(context["remote_workdir"]), "--partition", str(resources["partition"]),
            "--nodes", str(resources["nodes"]), "--ntasks", str(resources["ntasks"]),
            "--cpus-per-task", str(resources["cpus_per_task"]), "--mem", str(resources["mem"]),
            "--time", str(resources["time"]), "--account", str(resources["account"]),
            "--purpose", str(payload.get("job_record_purpose") or "production"),
            "--connection-alias", self.alias,
        ]
        if resources.get("qos"):
            argv.extend(["--qos", str(resources["qos"])])
        for item in local_files:
            if str(item.get("path")) != local_primary and str(item.get("path")) != local_script:
                argv.extend(["--input", str(item["path"])])
        # Job-ID persistence in SQLite has already completed. A local record error is
        # reported as a warning but must never cause another sbatch submission.
        result = self.runner.run(argv, timeout=self.command_timeout)
        if result.returncode:
            raise HpcRuntimeError(
                "Slurm job was submitted and its Job ID persisted, but the upstream Job Record create command failed: "
                + (result.stderr or result.stdout)[-1200:]
            )

    def get_status(self, job_reference: JobReference) -> HpcStatus:
        self._require_backend(job_reference)
        live = self._ssh(["squeue", "-h", "-j", job_reference.job_id, "-o", "%T"]).stdout.strip()
        if live:
            scheduler = live.splitlines()[0].strip().upper().split()[0]
        else:
            accounting = self._ssh([
                "sacct", "-X", "-n", "-P", "-j", job_reference.job_id,
                "--format=JobIDRaw,State,ExitCode,Elapsed",
            ]).stdout
            scheduler = "UNKNOWN"
            for line in accounting.splitlines():
                fields = line.strip().split("|")
                if len(fields) >= 3 and fields[0] == job_reference.job_id:
                    scheduler = fields[1].split()[0].split("+")[0].upper()
                    break
        state_map = {
            "SUBMITTED": HpcState.SUBMITTED,
            "PENDING": HpcState.QUEUED,
            "CONFIGURING": HpcState.QUEUED,
            "RUNNING": HpcState.RUNNING,
            "COMPLETING": HpcState.RUNNING,
            "RESV_DEL_HOLD": HpcState.QUEUED,
            "REQUEUED": HpcState.QUEUED,
            "SUSPENDED": HpcState.RUNNING,
            "COMPLETED": HpcState.AWAITING_VALIDATION,
            "FAILED": HpcState.FAILED,
            "CANCELLED": HpcState.FAILED,
            "TIMEOUT": HpcState.FAILED,
            "OUT_OF_MEMORY": HpcState.FAILED,
            "NODE_FAIL": HpcState.FAILED,
        }
        state = state_map.get(scheduler, HpcState.UNKNOWN)
        return HpcStatus(
            job_reference=job_reference, state=state, scheduler_state=scheduler,
            application_state="unknown", hashes_verified=False,
        )

    def get_record(self, job_reference: JobReference) -> HpcJobRecord:
        self._require_backend(job_reference)
        context = self._task_context.get(job_reference.task_id)
        show_argv = [
            str(self.config.get("python_executable") or sys.executable),
            str(self.job_record_script), "show",
            "--project-root", str(self.local_project_root), "--job-id", job_reference.job_id,
        ]
        # sbatch acceptance and durable Job ID persistence happen before local
        # Job Record creation. If the process stopped in that small window,
        # reconstruct the record from the stored task context, not by resubmitting.
        probe = self.runner.run(show_argv, timeout=self.command_timeout)
        if probe.returncode != 0 and context is not None:
            self._create_upstream_job_record(context["manifest"], job_reference.job_id, context)
        self._sync_upstream_job_record(job_reference.job_id)
        record_output = self._run_local(show_argv)
        try:
            record = __import__("json").loads(record_output.stdout)
        except Exception as exc:
            raise HpcRuntimeError(f"Upstream Job Record show did not return JSON: {exc}") from exc
        scheduler = str(record.get("slurm", {}).get("state", "UNKNOWN")).split()[0].upper()
        app = record.get("application", {})
        normal = app.get("normal_termination")
        raw_exit = str(record.get("slurm", {}).get("exit_code") or "")
        exit_code = None
        if raw_exit:
            first = raw_exit.split(":", 1)[0]
            if first.isdigit():
                exit_code = int(first)
        return HpcJobRecord(
            job_reference=job_reference, scheduler_state=scheduler,
            application_state="succeeded" if normal is True else "failed" if normal is False else "unknown",
            application_exit_code=exit_code,
            completion_evidence=app.get("observed_marker"),
        )

    def _sync_upstream_job_record(self, job_id: str) -> None:
        argv = [
            str(self.config.get("python_executable") or sys.executable),
            str(self.job_record_script), "sync", "--project-root", str(self.local_project_root),
            "--job-id", job_id, "--connection-alias", self.alias,
        ]
        self._append_sync_options(argv)
        self._run_local(argv)

    def _append_sync_options(self, argv: list[str]) -> None:
        return None

    def retrieve_selected_outputs(
        self, job_reference: JobReference, output_selection: Sequence[str]
    ) -> tuple[ArtifactRef, ...]:
        self._require_backend(job_reference)
        context = self._task_context.get(job_reference.task_id)
        if context is None:
            raise ContractError("task context is required for selective output retrieval")
        output_files = context["output_files"]
        missing = [role for role in output_selection if role not in output_files]
        if missing:
            raise ContractError("undeclared output role(s): " + ", ".join(missing))
        workdir = context["remote_workdir"]
        stage_dir = self.local_project_root / ".pipeline" / "staging" / hashlib.sha256(job_reference.task_id.encode()).hexdigest()[:16] / "retrieved"
        stage_dir.mkdir(parents=True, exist_ok=True)
        refs: list[ArtifactRef] = []
        for role in output_selection:
            filename = _safe_token(str(output_files[role]), "output filename")
            filename = filename.replace("JOB_ID", job_reference.job_id)
            remote_file = workdir + "/" + filename
            remote_line = self._ssh(["sha256sum", "--", remote_file]).stdout.strip()
            expected = remote_line.split()[0].lower() if remote_line else ""
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise HpcRuntimeError(f"remote output {filename} did not return a valid SHA-256")
            target = stage_dir / filename
            if target.exists() and sha256_file(target) != expected:
                target = stage_dir / f"{target.stem}.{job_reference.job_id}{target.suffix}"
            if not target.exists():
                self._scp(f"{self.alias}:{remote_file}", str(target))
            actual = sha256_file(target)
            if actual != expected:
                raise HpcRuntimeError(f"downloaded output SHA-256 mismatch for {filename}")
            refs.append(ArtifactRef(
                artifact_id=f"staged-{job_reference.job_id}-{role}",
                sha256=actual, format_id=None, uri=target.resolve().as_uri(),
                source_system=f"HPC:{self.backend_id}",
            ))
        return tuple(refs)

    def verify_hashes(self, manifest: Sequence[ArtifactRef]) -> HashVerification:
        checked: list[str] = []
        failures: list[str] = []
        for artifact in manifest:
            parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(artifact.uri or "")
            if parsed.scheme != "file":
                failures.append(f"{artifact.artifact_id}: no local file URI")
                continue
            local_value = __import__("urllib.parse", fromlist=["unquote"]).unquote(parsed.path)
            if os.name == "nt" and len(local_value) >= 3 and local_value[0] == "/" and local_value[2] == ":":
                local_value = local_value[1:]
            local = Path(local_value)
            try:
                digest = sha256_file(local)
                if artifact.sha256 is None or digest.lower() != artifact.sha256.lower():
                    failures.append(f"{artifact.artifact_id}: local SHA-256 mismatch")
                else:
                    checked.append(artifact.artifact_id)
            except OSError as exc:
                failures.append(f"{artifact.artifact_id}: {exc}")
        return HashVerification(not failures, tuple(checked), tuple(failures), "sha256_local_and_remote")

    def update_application_record(
        self, job_id: str, *, success: bool, marker: str, result_files: Sequence[str] = ()
    ) -> None:
        argv = [
            str(self.config.get("python_executable") or sys.executable), str(self.job_record_script), "update",
            "--project-root", str(self.local_project_root), "--job-id", job_id,
            "--application-ok", "yes" if success else "no", "--marker", marker,
        ]
        for path in result_files:
            argv.extend(["--result", str(path)])
        self._run_local(argv)

    def cancel(self, job_reference: JobReference) -> None:
        self._require_backend(job_reference)
        self._ssh(["scancel", job_reference.job_id])

    def _require_backend(self, job_reference: JobReference) -> None:
        if job_reference.backend_id != self.backend_id:
            raise ContractError(f"JobReference backend {job_reference.backend_id!r} does not match {self.backend_id!r}")


class BeiLongHPCAdapter(SkillSlurmBackend):
    backend_id = "beilong"
    job_name = "wcl"

    def __init__(self, config: Mapping[str, Any], **kwargs):
        super().__init__(config, **kwargs)
        self.ssh_config = Path(str(self.config["ssh_config"])).expanduser().resolve()
        self.allowed_workspace_root = _remote_path(str(self.config.get("allowed_workspace_root") or ""), "allowed_workspace_root")
        if not self.remote_root.startswith(self.allowed_workspace_root.rstrip("/") + "/") and self.remote_root != self.allowed_workspace_root:
            raise ContractError("BeiLong remote_root must be equal to or below allowed_workspace_root")

    def _argv_prefix(self, executable: str, *, ssh: bool) -> list[str]:
        return [executable, "-F", str(self.ssh_config)]

    def _read_only_preflight(self) -> None:
        if not self.ssh_config.is_file():
            raise HpcRuntimeError(f"Dedicated BSCC-A SSH config not found: {self.ssh_config}")
        module_init = str(self.config.get("module_init_path") or "")
        if not module_init:
            raise HpcRuntimeError("BeiLong runtime config must supply module_init_path")
        resources = dict(self.config.get("resource_profile") or {})
        module_name = str(resources.get("module") or "")
        executable = str(self.config.get("cp2k_executable") or "cp2k.psmp")
        work_parts = [
            f"test -d {shlex.quote(self.allowed_workspace_root)}",
            f"test -r {shlex.quote(module_init)}",
            f"source {shlex.quote(module_init)} >/dev/null 2>&1",
            f"module load {shlex.quote(module_name)} >/dev/null 2>&1",
            "command -v sbatch >/dev/null",
            "command -v squeue >/dev/null",
            "command -v sacct >/dev/null",
            f"command -v {shlex.quote(executable)} >/dev/null",
        ]
        data_dir = str(self.config.get("remote_cp2k_data_dir") or "")
        if data_dir:
            data_dir = _remote_path(data_dir, "remote_cp2k_data_dir")
            for key in ("basis_file_name", "potential_file_name"):
                filename = _safe_token(str(self.config[key]), key)
                work_parts.append(f"test -r {shlex.quote(data_dir + '/' + filename)}")
        self._ssh(["bash", "-lc", " && ".join(work_parts)])

    def _append_sync_options(self, argv: list[str]) -> None:
        argv.extend(["--ssh-config", str(self.ssh_config), "--ssh-executable", self.ssh_executable])


class UCASHPCAdapter(SkillSlurmBackend):
    backend_id = "ucas"
    job_name = "cp2k"

    def _read_only_preflight(self) -> None:
        resources = dict(self.config.get("resource_profile") or {})
        module_name = str(resources.get("module") or "")
        executable = str(self.config.get("cp2k_executable") or "cp2k.psmp")
        work_parts = [
            "source /etc/profile.d/modules.sh",
            "module use /public/env/modules/apps",
            "module use /public/env/modules/tools",
            f"module load {shlex.quote(module_name)}",
            "command -v sbatch >/dev/null",
            "command -v squeue >/dev/null",
            "command -v sacct >/dev/null",
            f"command -v {shlex.quote(executable)} >/dev/null",
        ]
        data_dir = str(self.config.get("remote_cp2k_data_dir") or "")
        if data_dir:
            data_dir = _remote_path(data_dir, "remote_cp2k_data_dir")
            for key in ("basis_file_name", "potential_file_name"):
                filename = _safe_token(str(self.config[key]), key)
                work_parts.append(f"test -r {shlex.quote(data_dir + '/' + filename)}")
        self._ssh(["bash", "-lc", " && ".join(work_parts)])

    def _append_sync_options(self, argv: list[str]) -> None:
        return None
