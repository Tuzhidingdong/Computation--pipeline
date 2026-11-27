"""Local-only real execution configuration. No secrets belong in the repository."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class RuntimeConfigError(RuntimeError):
    pass


def _resolve(value: str | None, *, base: Path) -> Path | None:
    if not value:
        return None
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    return (path if path.is_absolute() else base / path).resolve()


def load_runtime_config(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise RuntimeConfigError(
            f"Real execution configuration not found: {source}. "
            "Create .pipeline/runtime.local.json from .pipeline/runtime.local.example.json."
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"Cannot read runtime configuration {source}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise RuntimeConfigError("runtime config must be a JSON object with schema_version='1.0'")
    payload["_config_path"] = str(source)
    payload["_config_dir"] = str(source.parent)
    base = source.parent

    for key in ("active_project_root", "python_executable"):
        if payload.get(key):
            resolved = _resolve(payload[key], base=base)
            payload[key] = str(resolved)

    data = payload.setdefault("data_analysis", {})
    if not isinstance(data, dict):
        raise RuntimeConfigError("data_analysis must be an object")
    for key in ("source_root", "project_root"):
        if data.get(key):
            data[key] = str(_resolve(data[key], base=base))

    cst = payload.setdefault("chem_scitoolkit", {})
    if not isinstance(cst, dict):
        raise RuntimeConfigError("chem_scitoolkit must be an object")
    if cst.get("source_root"):
        cst["source_root"] = str(_resolve(cst["source_root"], base=base))

    backends = payload.setdefault("hpc_backends", {})
    if not isinstance(backends, dict):
        raise RuntimeConfigError("hpc_backends must be an object")
    for backend_name, profile in backends.items():
        if not isinstance(profile, dict):
            raise RuntimeConfigError(f"hpc_backends.{backend_name} must be an object")
        for key in (
            "ssh_executable", "scp_executable", "ssh_config", "skill_root",
            "job_record_script", "slurm_template", "privacy_header_template",
        ):
            if profile.get(key):
                profile[key] = str(_resolve(profile[key], base=base))
    return payload


def validate_runtime_for_backend(
    config: Mapping[str, Any], backend_id: str, resource_profile: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    backend = dict((config.get("hpc_backends") or {}).get(backend_id) or {})
    if not backend:
        raise RuntimeConfigError(f"No local runtime profile configured for HPC backend {backend_id!r}")
    if backend.get("enabled") is not True:
        raise RuntimeConfigError(f"HPC backend {backend_id!r} is not enabled in local runtime config")
    resources = dict((config.get("resource_profiles") or {}).get(resource_profile) or {})
    if not resources:
        raise RuntimeConfigError(
            f"Resource profile {resource_profile!r} is not defined in local runtime config"
        )
    required_backend = ("ssh_executable", "scp_executable", "alias", "remote_root", "skill_root", "job_record_script")
    missing = [key for key in required_backend if not backend.get(key)]
    if backend_id == "beilong" and not backend.get("ssh_config"):
        missing.append("ssh_config")
    if missing:
        raise RuntimeConfigError(
            f"HPC backend {backend_id!r} is missing local setting(s): {', '.join(missing)}"
        )
    for field in ("nodes", "ntasks", "cpus_per_task", "mem", "time", "partition", "module"):
        if not resources.get(field):
            raise RuntimeConfigError(
                f"Resource profile {resource_profile!r} is missing required field {field!r}"
            )
    if backend_id == "ucas" and not (resources.get("account") or backend.get("account")):
        raise RuntimeConfigError("UCAS resource profile/backend requires an explicit Slurm account")
    if backend_id == "beilong" and not (resources.get("account") or backend.get("account")):
        raise RuntimeConfigError("BeiLong resource profile/backend requires an explicit Slurm account")
    return backend, resources
