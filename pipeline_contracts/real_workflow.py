"""Real CP2K workflow bridge: CST builder → Skill HPC → Data_analysis Artifact/Evidence."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlparse

from .hpc_runtime import (
    BeiLongHPCAdapter, UCASHPCAdapter, HpcRuntimeError, SubmissionUnknown,
    render_beilong_cp2k_script, render_ucas_cp2k_script, sha256_file,
)
from .models import (
    AnalysisRequest, ArtifactRef, CSTTaskRequest, HpcTaskManifest, TaskStatus,
)
from .real_adapters import RealCSTAdapter, RealDataAnalysisAdapter, load_data_analysis_api
from .runtime_config import load_runtime_config, validate_runtime_for_backend
from .workflow import ExecutionResult


class RealWorkflowUnavailable(RuntimeError):
    pass


def _add_source_root(path: str | None) -> None:
    if not path:
        return
    root = Path(path).expanduser().resolve(strict=True)
    candidates = [root, root / "src"]
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _sha(path: Path) -> str:
    return sha256_file(path)


def _atomic_new_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise RealWorkflowUnavailable(f"refusing a symlink output directory: {path.parent}")
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    else:
        temp.unlink(missing_ok=True)


def _source_class_for_structure(suffix: str) -> str:
    return "author_processed" if suffix.lower() in {".xyz", ".cif", ".pdb", ".mol", ".vasp", ".poscar"} else "other"


class RealCP2KWorkflowAdapter:
    """One-process coordinator over existing upstream Python APIs and HPC Skill commands."""

    execution_mode = "real"

    def __init__(
        self,
        plan: Any,
        project_root: str | Path,
        runtime_config: Mapping[str, Any] | str | Path,
        *,
        cst_adapter: Any | None = None,
        data_analysis_adapter: Any | None = None,
        hpc_backend: Any | None = None,
        command_runner: Any | None = None,
    ):
        self.plan = plan
        self.project_root = Path(project_root).expanduser().resolve()
        if isinstance(runtime_config, (str, Path)):
            self.runtime = load_runtime_config(runtime_config)
        else:
            self.runtime = dict(runtime_config)
        data_cfg = dict(self.runtime.get("data_analysis") or {})
        configured_root = Path(data_cfg.get("project_root") or self.project_root).expanduser().resolve()
        if configured_root != self.project_root:
            raise RealWorkflowUnavailable(
                "CLI project_root must match data_analysis.project_root in runtime.local.json"
            )
        self.da_project_root = configured_root
        self.active_project_root = Path(
            self.runtime.get("active_project_root") or self.project_root
        ).expanduser().resolve()
        _add_source_root(data_cfg.get("source_root"))
        _add_source_root((self.runtime.get("chem_scitoolkit") or {}).get("source_root"))

        try:
            self.da_api = load_data_analysis_api()
        except Exception as exc:
            raise RealWorkflowUnavailable(f"Data_analysis API unavailable: {exc}") from exc
        self.register_inputs = getattr(self.da_api, "register_inputs", None)
        if not callable(self.register_inputs):
            raise RealWorkflowUnavailable(
                "Data_analysis API does not expose data_analysis.register.register_inputs()"
            )
        self.cst = cst_adapter or RealCSTAdapter()
        self.da = data_analysis_adapter or RealDataAnalysisAdapter(self.da_project_root, api=self.da_api)
        self.backend_id = str(self.plan.execution.get("backend") or "")
        profile_ref = self.plan.execution.get("resources", {}).get("profile")
        if not profile_ref:
            raise RealWorkflowUnavailable("CalculationPlan execution.resources.profile is required")
        try:
            self.backend_config, self.resources = validate_runtime_for_backend(
                self.runtime, self.backend_id, str(profile_ref)
            )
        except Exception as exc:
            raise RealWorkflowUnavailable(str(exc)) from exc
        method_cfg = dict(self.plan.method)
        local_basis = (self.runtime.get("input_files") or {}).get("basis")
        local_potential = (self.runtime.get("input_files") or {}).get("potential")
        if bool(local_basis) != bool(local_potential):
            raise RealWorkflowUnavailable("runtime input_files must configure both basis and potential files, or neither")
        if local_basis and local_potential:
            basis_path = Path(str(local_basis)).expanduser().resolve(strict=True)
            potential_path = Path(str(local_potential)).expanduser().resolve(strict=True)
            if basis_path.name != str(method_cfg["basis_file_name"]):
                raise RealWorkflowUnavailable("local basis file basename must equal method.basis_file_name")
            if potential_path.name != str(method_cfg["potential_file_name"]):
                raise RealWorkflowUnavailable("local pseudopotential basename must equal method.potential_file_name")
            if not basis_path.is_file() or not potential_path.is_file():
                raise RealWorkflowUnavailable("configured basis/pseudopotential inputs must be regular files")
        elif not self.backend_config.get("remote_cp2k_data_dir"):
            raise RealWorkflowUnavailable(
                "basis/pseudopotential files are not verified: configure both local input_files.basis/potential "
                "or backend remote_cp2k_data_dir in runtime.local.json"
            )
        self.backend_config["resource_profile"] = dict(self.resources)
        self.backend_config["basis_file_name"] = str(method_cfg["basis_file_name"])
        self.backend_config["potential_file_name"] = str(method_cfg["potential_file_name"])
        if hpc_backend is not None:
            self.hpc = hpc_backend
        else:
            common = {
                "local_project_root": self.active_project_root,
                "command_runner": command_runner,
                "command_timeout_seconds": self.backend_config.get("command_timeout_seconds", 45),
            }
            if self.backend_id == "beilong":
                self.hpc = BeiLongHPCAdapter(self.backend_config, **common)
            elif self.backend_id == "ucas":
                self.hpc = UCASHPCAdapter(self.backend_config, **common)
            else:
                raise RealWorkflowUnavailable(
                    f"Unsupported HPC backend {self.backend_id!r}; registered backends: beilong, ucas"
                )
        self._prepared: dict[str, dict[str, Any]] = {}
        self.initial_structure_ref: ArtifactRef | None = None
        self._run_context: dict[str, dict[str, Any]] = {}
        self._preflight_error: str | None = None

    def preflight(self, task: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            if not self.project_root.is_dir():
                raise RealWorkflowUnavailable(f"Data_analysis project root does not exist: {self.project_root}")
            if not self.active_project_root.is_dir():
                raise RealWorkflowUnavailable(
                    f"Active local HPC project root does not exist: {self.active_project_root}"
                )
            hpc = self.hpc.preflight()
            if not hpc.ready:
                detail = "; ".join(x.message for x in hpc.diagnostics) or "HPC read-only preflight did not pass"
                raise RealWorkflowUnavailable(detail)
            # Fail early when the declared stage is not part of this bounded MVP.
            if task.get("operation") not in {"cp2k.geo_opt", "cp2k.energy"}:
                raise RealWorkflowUnavailable(f"no real CP2K executor is registered for {task.get('operation')!r}")
            return {"ready": True, "backend": self.backend_id, "execution_mode": "real"}
        except Exception as exc:
            self._preflight_error = str(exc)
            return {"ready": False, "status": "UNAVAILABLE", "reason": str(exc)}

    def resolve_plan_input(self) -> Mapping[str, Any]:
        """Register/resolve the source structure before DAG identity is finalized."""
        self.initial_structure_ref = self._register_structure()
        return {
            "artifact_id": self.initial_structure_ref.artifact_id,
            "sha256": self.initial_structure_ref.sha256,
            "format_id": self.initial_structure_ref.format_id,
            "uri": self.initial_structure_ref.uri,
        }

    def _register_structure(self) -> ArtifactRef:
        if self.initial_structure_ref is not None:
            return self.initial_structure_ref
        structure = dict(self.plan.structure)
        if structure.get("artifact_id"):
            artifact_id = str(structure["artifact_id"])
            path = Path(self.da.resolve_artifact_path(ArtifactRef(artifact_id=artifact_id)))
            digest = _sha(path)
            self.initial_structure_ref = ArtifactRef(
                artifact_id=artifact_id, sha256=digest,
                format_id=structure.get("format"), uri=path.as_uri(),
                source_system="Data_analysis",
            )
            return self.initial_structure_ref
        raw_path = structure.get("path")
        if not raw_path:
            raise RealWorkflowUnavailable("CalculationPlan structure.path or structure.artifact_id is required")
        supplied_path = Path(str(raw_path)).expanduser()
        if not supplied_path.is_absolute():
            supplied_path = self.project_root / supplied_path
        if supplied_path.is_symlink():
            raise RealWorkflowUnavailable(f"structure input must not be a symlink: {supplied_path}")
        source = supplied_path.resolve(strict=True)
        if not source.is_file():
            raise RealWorkflowUnavailable(f"structure input is not a regular file: {source}")
        managed_originals = (self.da_project_root / "data" / "original_received").resolve()
        try:
            source.relative_to(managed_originals)
        except ValueError:
            pass
        else:
            raise RealWorkflowUnavailable(
                "structure path is already inside Data_analysis original_received. "
                "Because the public Data_analysis API has no path/hash-to-Artifact lookup, "
                "supply its registered Artifact ID in structure.artifact_id to avoid duplicate intake."
            )
        # Public Data_analysis does not expose lookup-by-path/hash. Register the
        # incoming file through its supported intake API and use the returned ID.
        receipt = self.register_inputs(
            str(self.da_project_root), str(source),
            source_class=_source_class_for_structure(source.suffix),
            received_from="Computation--pipeline CalculationPlan input",
        )
        if not isinstance(receipt, Mapping) or receipt.get("failures"):
            raise RealWorkflowUnavailable(
                "Data_analysis register_inputs() failed: " +
                json.dumps(receipt, ensure_ascii=False, default=str)[:1200]
            )
        ids = list(receipt.get("artifact_ids") or [])
        if len(ids) != 1:
            raise RealWorkflowUnavailable(
                f"expected one structure Artifact from register_inputs(), received {len(ids)}"
            )
        artifact_id = str(ids[0])
        resolved = Path(self.da.resolve_artifact_path(ArtifactRef(artifact_id=artifact_id)))
        digest = _sha(resolved)
        self.initial_structure_ref = ArtifactRef(
            artifact_id=artifact_id, sha256=digest,
            format_id=structure.get("format"), uri=resolved.as_uri(),
            source_system="Data_analysis",
        )
        return self.initial_structure_ref

    def _artifact_from_task_input(self, value: Mapping[str, Any]) -> ArtifactRef:
        artifact_id = str(value.get("artifact_id") or "")
        expected_sha = str(value.get("sha256") or "")
        if not artifact_id or not expected_sha:
            raise RealWorkflowUnavailable("real task input must carry a registered Artifact ID and SHA256")
        reference = ArtifactRef(
            artifact_id=artifact_id, sha256=expected_sha,
            format_id=value.get("format_id"), source_system="Data_analysis",
        )
        resolved = Path(self.da.resolve_artifact_path(reference)).expanduser().resolve(strict=True)
        actual = _sha(resolved)
        if actual.lower() != expected_sha.lower():
            raise RealWorkflowUnavailable(f"Artifact {artifact_id} changed after plan compilation; SHA256 mismatch")
        return ArtifactRef(
            artifact_id=artifact_id, sha256=actual, format_id=value.get("format_id"),
            uri=resolved.as_uri(), source_system="Data_analysis",
        )

    def _read_structure(self, artifact: ArtifactRef) -> tuple[list[tuple[str, float, float, float]], dict[str, float]]:
        path = Path(self.da.resolve_artifact_path(artifact))
        try:
            from ase.io import read
        except ImportError as exc:
            raise RealWorkflowUnavailable(
                "ASE is required to read the supplied structure file; install the already-approved ASE dependency"
            ) from exc
        atoms = read(str(path))
        symbols = list(atoms.get_chemical_symbols())
        positions = atoms.get_positions()
        structure_cfg = dict(self.plan.structure)
        method = dict(self.plan.method)
        kind_labels = structure_cfg.get("kind_labels")
        if kind_labels is not None and len(kind_labels) != len(symbols):
            raise RealWorkflowUnavailable("structure.kind_labels length must equal the number of atoms")
        coords = [
            (str(kind_labels[i]) if kind_labels is not None else symbol,
             float(pos[0]), float(pos[1]), float(pos[2]))
            for i, (symbol, pos) in enumerate(zip(symbols, positions))
        ]
        supplied_cell = structure_cfg.get("cell") or {}
        cell_array = atoms.cell.array
        lengths = [float(x) for x in atoms.cell.lengths()]
        angles = [float(x) for x in atoms.cell.angles()]
        cell = {
            "a": float(supplied_cell.get("a", lengths[0])),
            "b": float(supplied_cell.get("b", lengths[1])),
            "c": float(supplied_cell.get("c", lengths[2])),
            "alpha": float(supplied_cell.get("alpha", angles[0])),
            "beta": float(supplied_cell.get("beta", angles[1])),
            "gamma": float(supplied_cell.get("gamma", angles[2])),
        }
        if any(not value or value <= 0 for key, value in cell.items() if key in {"a", "b", "c"}):
            raise RealWorkflowUnavailable(
                "finite CP2K builder needs explicit positive structure.cell a/b/c when the source has no cell"
            )
        kind_defs = method.get("kind_definitions")
        if not isinstance(kind_defs, Mapping):
            raise RealWorkflowUnavailable("method.kind_definitions is required; no basis/pseudopotential is guessed")
        missing = sorted({label for label, *_ in coords}.difference(kind_defs))
        if missing:
            raise RealWorkflowUnavailable("no explicit CP2K KIND definitions for: " + ", ".join(missing))
        return coords, cell

    def _stage_spec(self, task: Mapping[str, Any]) -> dict[str, Any]:
        stage_id = str(task.get("stage_id") or task["operation"].replace(".", "-"))
        stage = next((x for x in self.plan.calculations if str(x.get("id")) == stage_id), None)
        if stage is None:
            raise RealWorkflowUnavailable(f"CalculationPlan has no stage declaration {stage_id!r}")
        return dict(stage)

    def _prepare_task(self, task: Mapping[str, Any], runtime_state: Mapping[str, Any] | None) -> dict[str, Any]:
        cached = self._prepared.get(str(task["task_id"]))
        if cached:
            return cached
        if runtime_state and runtime_state.get("registered_input_artifacts"):
            cached = dict(runtime_state)
            self._prepared[str(task["task_id"])] = cached
            return cached

        stage = self._stage_spec(task)
        input_descriptor = dict(task.get("input") or {})
        if input_descriptor.get("artifact_id"):
            structure = self._artifact_from_task_input(input_descriptor)
            if task["operation"] == "cp2k.geo_opt":
                self.initial_structure_ref = structure
        else:
            structure = self._register_structure()
        structure_path = Path(self.da.resolve_artifact_path(structure))
        atoms, cell = self._read_structure(structure)
        method = dict(self.plan.method)
        kind_defs = dict(method["kind_definitions"])
        stage_type = "GEO_OPT" if task["operation"] == "cp2k.geo_opt" else "ENERGY"
        builder_parameters = {
            "atoms": atoms,
            "cell": cell,
            "kind_definitions": kind_defs,
            "total_charge": int(method["charge"]),
            "multiplicity": int(method["multiplicity"]),
            "uks": method.get("uks"),
            "cell_periodicity": str(method["cell_periodicity"]),
            "poisson_periodicity": str(method["poisson_periodicity"]),
            "poisson_solver": str(method.get("poisson_solver", "MT")),
            "center_coordinates": bool(method.get("center_coordinates", False)),
            "basis_file_name": str(method["basis_file_name"]),
            "potential_file_name": str(method["potential_file_name"]),
            "xc_functional": str(method["xc"]),
            "dispersion_model": method.get("dispersion_model"),
            "dispersion_reference_functional": method.get("dispersion_reference_functional"),
            "dispersion_parameter_file": method.get("dispersion_parameter_file"),
            "cutoff_ry": float(method["cutoff_ry"]),
            "rel_cutoff_ry": float(method.get("rel_cutoff_ry", 50)),
            "run_type": stage_type,
            "scf_method": str(method["scf"]["method"]),
            "eps_scf": float(method["scf"]["eps_scf"]),
            "max_scf": int(method["scf"]["max_scf"]),
            "smearing": method.get("smearing"),
            "added_mos": method.get("added_mos"),
            "mixing": method.get("mixing"),
            "print_sections": list(stage.get("print_sections") or []),
        }
        cst = self.cst.execute(CSTTaskRequest(
            task_id=str(task["task_id"]) + "-build",
            operation="cp2k.build_finite_system",
            input_artifacts=(structure,),
            task_config={"builder_options": {
                "project_name": "cp2k_" + str(task["task_id"]).replace("-", "_")[:32],
                "run_type": stage_type, "functional": str(method["xc"]),
                "cutoff_ry": int(method["cutoff_ry"]), "rel_cutoff_ry": int(method.get("rel_cutoff_ry", 50)),
                "periodic": str(method["cell_periodicity"]),
            }, "arguments": builder_parameters},
        ))
        if cst.status != TaskStatus.SUCCEEDED or not cst.structured_result.get("input_text"):
            raise RealWorkflowUnavailable(
                "RealCSTAdapter could not build CP2K input: " +
                str(cst.error or cst.structured_result.get("adapter_error_code") or cst.status.value)
            )
        input_text = str(cst.structured_result["input_text"])
        if task["operation"] == "cp2k.geo_opt":
            # Insert only a declared output request inside the existing MOTION
            # section; do not create a duplicate top-level MOTION section.
            marker = "&END MOTION"
            position = input_text.upper().rfind(marker)
            if position < 0:
                raise RealWorkflowUnavailable("CST GEO_OPT builder output has no closing &END MOTION")
            trajectory_print = """  &PRINT
    &TRAJECTORY
      FORMAT XYZ
      FILENAME = optimized_structure.xyz
      &EACH
        GEO_OPT 1
      &END EACH
    &END TRAJECTORY
  &END PRINT
"""
            input_text = input_text[:position] + trajectory_print + input_text[position:]
        suffix = uuid.uuid4().hex[:10]
        input_name = "cp2k_" + str(task["task_id"])[:32] + ".inp"
        derived_dir = self.da_project_root / "data" / "derived"
        input_path = derived_dir / input_name
        _atomic_new_file(input_path, input_text.encode("utf-8"))
        api = self.da_api
        derived_input = api.register_derived_artifact(
            str(self.da_project_root), str(input_path),
            source_artifact_ids=[structure.artifact_id],
            format_id="cp2k_input",
            provenance={
                "pipeline_task_id": str(task["task_id"]),
                "operation": str(task["operation"]),
                "method": method,
                "builder": "chem-scitoolkit.CP2KInputBuilder.build_finite_system",
            },
        )
        if not isinstance(derived_input, Mapping) or not derived_input.get("artifact_id") or not derived_input.get("sha256"):
            raise RealWorkflowUnavailable("Data_analysis register_derived_artifact did not return input Artifact ID/SHA256")
        derived_input_ref = ArtifactRef(
            artifact_id=str(derived_input["artifact_id"]), sha256=str(derived_input["sha256"]),
            format_id="cp2k_input", uri=input_path.resolve().as_uri(), source_system="Data_analysis",
        )
        resolved_input = Path(self.da.resolve_artifact_path(derived_input_ref))
        if _sha(resolved_input).lower() != derived_input_ref.sha256.lower():
            raise RealWorkflowUnavailable("registered CP2K input failed Data_analysis SHA256 verification")

        input_check = self.cst.execute(CSTTaskRequest(
            task_id=str(task["task_id"]) + "-input-qc",
            operation="cp2k.validate_input",
            input_artifacts=(derived_input_ref,),
            parameters={"base_dir": str(derived_dir)},
        ))
        if input_check.status != TaskStatus.SUCCEEDED or input_check.structured_result.get("status") != "passed":
            raise RealWorkflowUnavailable(
                "CP2K input lint failed or unavailable: " +
                str(input_check.error or input_check.structured_result)
            )

        runtime_files = dict(self.runtime.get("input_files") or {})
        staged = [
            {"path": str(resolved_input), "name": input_name},
        ]
        for key in ("basis", "potential"):
            supplied = runtime_files.get(key)
            if supplied:
                basis_path = Path(str(supplied)).expanduser().resolve(strict=True)
                staged.append({"path": str(basis_path), "name": basis_path.name})
        output_files = dict(stage.get("output_files") or {})
        if "cp2k_output" not in output_files:
            output_files["cp2k_output"] = "cp2k.out"
        if task["operation"] == "cp2k.geo_opt" and "optimized_structure" not in output_files:
            output_files["optimized_structure"] = "optimized_structure.xyz"
        script_name = "job.slurm"
        script_path = self.active_project_root / ".pipeline" / "staging" / str(task["task_id"]) / script_name
        script_path.parent.mkdir(parents=True, exist_ok=True)
        if self.backend_id == "beilong":
            profile = self.backend_config
            header = Path(str(profile["privacy_header_template"])).read_text(encoding="utf-8")
            script = render_beilong_cp2k_script(
                header, allowed_workspace_root=str(profile["allowed_workspace_root"]),
                remote_workdir=str((runtime_state or {}).get("remote_workdir") or self.hpc._new_remote_workdir(str(task["task_id"]))),
                resources=self.resources, module_init_path=str(profile["module_init_path"]),
                input_name=input_name, output_name=str(output_files["cp2k_output"]),
                cp2k_executable=str(profile.get("cp2k_executable", "cp2k.psmp")),
            )
        else:
            template = Path(str(self.backend_config["slurm_template"])).read_text(encoding="utf-8")
            script = render_ucas_cp2k_script(
                template, resources=self.resources, input_name=input_name,
                output_name=str(output_files["cp2k_output"]),
            )
        _atomic_new_file(script_path, script.encode("utf-8"))
        staged.append({"path": str(script_path), "name": script_name})
        input_refs = (structure, derived_input_ref)
        data = {
            "structure_artifact_id": structure.artifact_id,
            "structure_sha256": structure.sha256,
            "cp2k_input_artifact_id": derived_input_ref.artifact_id,
            "cp2k_input_sha256": derived_input_ref.sha256,
            "registered_input_artifacts": [
                {"artifact_id": ref.artifact_id, "sha256": ref.sha256, "uri": ref.uri, "format_id": ref.format_id}
                for ref in input_refs
            ],
            "local_files": staged,
            "output_files": output_files,
            "input_filename": input_name,
            "job_script_name": script_name,
            "resources": self.resources,
            "python_executable": self.runtime.get("python_executable") or sys.executable,
            "run_type": stage_type,
        }
        self._prepared[str(task["task_id"])] = data
        return data

    def _rehydrate_job_context(self, task, runtime_state, job_id):
        prepared = self._prepare_task(task, runtime_state)
        manifest = self._hpc_manifest(task, prepared)
        workdir = runtime_state.get("remote_workdir") if runtime_state else None
        if not workdir:
            raise SubmissionUnknown("", "persisted HPC Job ID has no persisted remote_workdir; refusing unsafe re-submit")
        self.hpc.attach_task(manifest, str(workdir))
        return prepared, manifest

    def _hpc_manifest(self, task, prepared):
        refs = tuple(ArtifactRef(
            artifact_id=str(item["artifact_id"]), sha256=str(item["sha256"]),
            format_id=item.get("format_id"), uri=item.get("uri"), source_system="Data_analysis",
        ) for item in prepared["registered_input_artifacts"])
        payload = dict(prepared)
        payload["local_files"] = list(prepared["local_files"])
        return HpcTaskManifest(str(task["task_id"]), refs, payload=payload)

    def _register_retrieved(self, role: str, reference: ArtifactRef, job_id: str) -> ArtifactRef:
        parsed = urlparse(reference.uri or "")
        if parsed.scheme != "file":
            raise RealWorkflowUnavailable(f"retrieved {role} does not have a local file URI")
        local_value = unquote(parsed.path)
        if os.name == "nt" and len(local_value) >= 3 and local_value[0] == "/" and local_value[2] == ":":
            local_value = local_value[1:]
        staged_path = Path(local_value)
        if not staged_path.is_file() or _sha(staged_path).lower() != str(reference.sha256).lower():
            raise RealWorkflowUnavailable(f"recovered {role} file failed local SHA256 verification")
        receipt = self.register_inputs(
            str(self.da_project_root), str(staged_path),
            source_class="computational_output",
            received_from=f"{self.backend_id} Slurm Job {job_id} output:{role}",
        )
        ids = list(receipt.get("artifact_ids") or []) if isinstance(receipt, Mapping) else []
        if not isinstance(receipt, Mapping) or receipt.get("failures") or len(ids) != 1:
            raise RealWorkflowUnavailable(
                f"Data_analysis failed to register retrieved {role}: " +
                json.dumps(receipt, ensure_ascii=False, default=str)[:1000]
            )
        artifact_id = str(ids[0])
        resolved = Path(self.da.resolve_artifact_path(ArtifactRef(artifact_id=artifact_id)))
        actual_hash = _sha(resolved)
        if actual_hash.lower() != reference.sha256.lower():
            raise RealWorkflowUnavailable(f"registered {role} Artifact SHA does not match retrieved bytes")
        return ArtifactRef(
            artifact_id=artifact_id, sha256=actual_hash,
            format_id="cp2k_output" if role == "cp2k_output" else "extxyz",
            uri=resolved.as_uri(), source_system="Data_analysis",
        )

    def execute(
        self,
        task: Mapping[str, Any],
        existing_job_id: str | None = None,
        *,
        runtime_state: Mapping[str, Any] | None = None,
        on_submission_intent: Callable[[Mapping[str, Any]], None] | None = None,
        on_job_submitted: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> ExecutionResult:
        from .hpc_runtime import SubmissionUnknown
        try:
            prepared = self._prepare_task(task, runtime_state)
            manifest = self._hpc_manifest(task, prepared)
            if existing_job_id:
                prepared, manifest = self._rehydrate_job_context(task, {**prepared, **dict(runtime_state or {})}, existing_job_id)
                job = __import__("pipeline_contracts.models", fromlist=["JobReference"]).JobReference(
                    str(existing_job_id), str(task["task_id"]), self.backend_id
                )
            else:
                # If the persisted run already contains a submission intent but no Job
                # ID, reconcile that intent; never create another remote directory or sbatch.
                intent = dict(runtime_state or {})
                if intent.get("submission_intent") or intent.get("remote_workdir"):
                    workdir = str(intent.get("remote_workdir") or "")
                    if not workdir:
                        raise SubmissionUnknown("", "submission intent has no recoverable remote work directory")
                    self.hpc.attach_task(manifest, workdir)
                    found = self.hpc.reconcile_submission(workdir, str(intent.get("submission_time") or ""))
                    if not found:
                        raise SubmissionUnknown(workdir, "submission could not be reconciled; no duplicate sbatch attempted")
                    job = __import__("pipeline_contracts.models", fromlist=["JobReference"]).JobReference(
                        found, str(task["task_id"]), self.backend_id
                    )
                    if on_job_submitted:
                        on_job_submitted(found, {**intent, "remote_workdir": workdir})
                else:
                    staged = self.hpc.stage_inputs(manifest)
                    prepared["remote_workdir"] = staged.stage_reference
                    self._prepared[str(task["task_id"])] = prepared
                    details = {
                        "remote_workdir": staged.stage_reference,
                        "submission_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                        "input_hashes": {
                            Path(item["name"]).name: _sha(Path(item["path"]))
                            for item in prepared["local_files"]
                        },
                        "backend_id": self.backend_id,
                        "registered_input_artifacts": prepared["registered_input_artifacts"],
                        "local_files": prepared["local_files"],
                        "output_files": prepared["output_files"],
                        "input_filename": prepared["input_filename"],
                        "job_script_name": prepared["job_script_name"],
                        "resources": prepared["resources"],
                    }
                    if on_submission_intent:
                        on_submission_intent(details)
                    job = self.hpc.submit(
                        manifest, on_submission_intent=None, on_job_submitted=on_job_submitted
                    )
            self.hpc.attach_task(manifest, str(prepared.get("remote_workdir") or (runtime_state or {}).get("remote_workdir")))
            status = self.hpc.get_status(job)
            if status.state in {__import__("pipeline_contracts.models", fromlist=["HpcState"]).HpcState.SUBMITTED,
                                 __import__("pipeline_contracts.models", fromlist=["HpcState"]).HpcState.QUEUED,
                                 __import__("pipeline_contracts.models", fromlist=["HpcState"]).HpcState.RUNNING,
                                 __import__("pipeline_contracts.models", fromlist=["HpcState"]).HpcState.UNKNOWN}:
                normalized = {
                    "submitted": "SUBMITTED", "queued": "QUEUED", "running": "RUNNING",
                    "unknown": "INTERRUPTED_RECOVERY",
                }.get(status.state.value, "INTERRUPTED_RECOVERY")
                return ExecutionResult(
                    status=normalized, job_id=job.job_id, scheduler_state=status.scheduler_state,
                    output_artifacts=(), diagnostics=tuple(x.message for x in status.diagnostics),
                    execution_mode="real", runtime={
                        "remote_workdir": prepared.get("remote_workdir") or (runtime_state or {}).get("remote_workdir"),
                        **prepared,
                    },
                )
            record = self.hpc.get_record(job)
            if record.scheduler_state != "COMPLETED":
                return ExecutionResult(
                    status="FAILED_PERMANENT", job_id=job.job_id,
                    scheduler_state=record.scheduler_state,
                    application_exit_code=record.application_exit_code,
                    diagnostics=("Slurm terminated without COMPLETED state",),
                    execution_mode="real",
                )
            if record.application_exit_code not in (0, None):
                return ExecutionResult(
                    status="FAILED_PERMANENT", job_id=job.job_id,
                    scheduler_state=record.scheduler_state,
                    application_exit_code=record.application_exit_code,
                    diagnostics=("Slurm reports a non-zero CP2K application exit code",),
                    execution_mode="real",
                )
            output_roles = list(prepared["output_files"])
            staged_refs = self.hpc.retrieve_selected_outputs(job, output_roles)
            integrity = self.hpc.verify_hashes(staged_refs)
            if not integrity.verified:
                raise RealWorkflowUnavailable("retrieved CP2K output failed SHA256: " + "; ".join(integrity.failures))
            by_role = dict(zip(output_roles, staged_refs))
            if "cp2k_output" not in by_role:
                raise RealWorkflowUnavailable("CalculationPlan output_files must declare cp2k_output")
            output_ref = self._register_retrieved("cp2k_output", by_role["cp2k_output"], job.job_id)
            cst = self.cst.execute(CSTTaskRequest(
                task_id=str(task["task_id"]) + "-output-qc",
                operation="cp2k.validate_output",
                input_artifacts=(output_ref,),
                parameters={"run_type": prepared["run_type"]},
                upstream_job_reference=job.job_id,
            ))
            if cst.status != TaskStatus.SUCCEEDED:
                self.hpc.update_application_record(job.job_id, success=False, marker="CP2K_OUTPUT_VALIDATION_FAILED")
                return ExecutionResult(
                    status="FAILED_PERMANENT", job_id=job.job_id,
                    scheduler_state=record.scheduler_state, application_exit_code=record.application_exit_code,
                    output_artifacts=({"artifact_id": output_ref.artifact_id, "sha256": output_ref.sha256, "kind": "cp2k_output"},),
                    diagnostics=(cst.error or "CST CP2K output validation failed",), execution_mode="real",
                )
            validation = cst.structured_result
            if validation.get("program_normal_termination") is not True or validation.get("scf_converged") is not True:
                self.hpc.update_application_record(job.job_id, success=False, marker="CP2K_NORMAL_TERMINATION_OR_SCF_FAILED")
                return ExecutionResult(
                    status="FAILED_PERMANENT", job_id=job.job_id,
                    scheduler_state=record.scheduler_state, application_exit_code=record.application_exit_code,
                    output_artifacts=({"artifact_id": output_ref.artifact_id, "sha256": output_ref.sha256, "kind": "cp2k_output"},),
                    diagnostics=("CP2K normal termination or SCF convergence was not confirmed",), execution_mode="real",
                )
            outputs = [{"artifact_id": output_ref.artifact_id, "sha256": output_ref.sha256, "kind": "cp2k_output"}]
            converged = True
            if task["operation"] == "cp2k.geo_opt":
                if validation.get("geometry_optimization_completed") is not True:
                    self.hpc.update_application_record(job.job_id, success=False, marker="GEO_OPT_NOT_CONVERGED")
                    return ExecutionResult(
                        status="FAILED_PERMANENT", job_id=job.job_id,
                        scheduler_state=record.scheduler_state, application_exit_code=record.application_exit_code,
                        output_artifacts=tuple(outputs), converged=False,
                        diagnostics=("CP2K output did not report GEOMETRY OPTIMIZATION COMPLETED",), execution_mode="real",
                    )
                if "optimized_structure" not in by_role:
                    raise RealWorkflowUnavailable("GEO_OPT requires a declared optimized_structure output")
                structure_ref = self._register_retrieved("optimized_structure", by_role["optimized_structure"], job.job_id)
                outputs.append({"artifact_id": structure_ref.artifact_id, "sha256": structure_ref.sha256, "kind": "optimized_structure"})
                converged = True
            self.hpc.update_application_record(
                job.job_id, success=True, marker="PROGRAM ENDED AT; CST OUTPUT CHECK PASSED",
                result_files=[str(Path(ref.uri.removeprefix("file://"))) for ref in staged_refs],
            )
            return ExecutionResult(
                status="COMPLETED", job_id=job.job_id, scheduler_state=record.scheduler_state,
                application_exit_code=0, output_artifacts=tuple(outputs), converged=converged,
                qc={"cst": dict(validation), "scientific_qc": "not_assessed"},
                diagnostics=(), execution_mode="real", runtime={**prepared, "remote_workdir": prepared.get("remote_workdir"), "job_id": job.job_id},
            )
        except SubmissionUnknown:
            raise
        except (ConnectionError, TimeoutError):
            raise
        except Exception as exc:
            return ExecutionResult(
                status="FAILED_PERMANENT", job_id=existing_job_id,
                diagnostics=(f"{type(exc).__name__}: {exc}",), execution_mode="real",
            )

    def analyze(self, task: Mapping[str, Any], artifacts: tuple[Mapping[str, Any], ...]) -> ExecutionResult:
        try:
            cp2k_output = next((x for x in artifacts if x.get("kind") == "cp2k_output"), None)
            if cp2k_output is None:
                raise RealWorkflowUnavailable("Data_analysis requires the registered CP2K output Artifact")
            artifact = ArtifactRef(
                artifact_id=str(cp2k_output["artifact_id"]), sha256=str(cp2k_output["sha256"]),
                format_id="cp2k_output", source_system="Data_analysis",
            )
            context = self._prepared.get(str(task["task_id"]), {})
            structure_id = context.get("structure_artifact_id")
            structure_sha = context.get("structure_sha256")
            request = AnalysisRequest(
                task_id=str(task["task_id"]) + "-analysis",
                operation="dft.artifact.read",
                input_artifacts=(artifact,),
                analysis_task={
                    "operation_id": self.plan.analysis.get("operation", "dft.artifact.read"),
                    "question": self.plan.scientific_question,
                },
                parameters={
                    "reader_id": self.plan.analysis.get("reader_id", "cp2k-output-tools"),
                    "format_id": "cp2k_output",
                },
                structure_metadata={
                    "structure_artifact_id": structure_id,
                    "structure_sha256": structure_sha,
                    "environment": {"cp2k_version": str(task.get("tool_version"))},
                },
                upstream_job_reference=str(task.get("_upstream_job_reference") or ""),
            )
            outcome = self.da.analyze(request)
            successful = outcome.status in {TaskStatus.SUCCEEDED, TaskStatus.WARNING}
            if not successful or not outcome.analysis_run_id or not outcome.evidence_package:
                raise RealWorkflowUnavailable(outcome.error or "Data_analysis did not return Analysis Run and Evidence Package")
            return ExecutionResult(
                status="COMPLETED",
                output_artifacts=tuple({
                    "artifact_id": x.artifact_id, "sha256": x.sha256, "kind": "analysis_derived"
                } for x in outcome.output_artifacts),
                analysis_run_id=outcome.analysis_run_id,
                evidence_package_id=outcome.evidence_package.get("evidence_package_id"),
                execution_mode="real",
                qc={"qc_status": outcome.qc_status, "warnings": list(outcome.warnings)},
            )
        except Exception as exc:
            return ExecutionResult(
                status="FAILED_PERMANENT", diagnostics=(f"{type(exc).__name__}: {exc}",),
                execution_mode="real",
            )


class UnavailableWorkflowAdapter:
    execution_mode = "real"

    def __init__(self, reason: str):
        self.reason = reason

    def preflight(self, task: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"ready": False, "status": "UNAVAILABLE", "reason": self.reason}

    def execute(self, task: Mapping[str, Any], existing_job_id: str | None = None, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult("UNAVAILABLE", job_id=existing_job_id, diagnostics=(self.reason,), execution_mode="real")

    def analyze(self, task: Mapping[str, Any], artifacts: tuple[Mapping[str, Any], ...]) -> ExecutionResult:
        return ExecutionResult("UNAVAILABLE", diagnostics=(self.reason,), execution_mode="real")


def build_real_workflow_adapter(
    plan: Any,
    project_root: str | Path,
    runtime_config: Mapping[str, Any] | str | Path,
    **injections: Any,
) -> RealCP2KWorkflowAdapter | UnavailableWorkflowAdapter:
    """Build a real-mode adapter or an explicit UNAVAILABLE adapter; never fall back to Mock."""
    try:
        adapter = RealCP2KWorkflowAdapter(plan, project_root, runtime_config, **injections)
        return adapter
    except Exception as exc:
        return UnavailableWorkflowAdapter(str(exc))
