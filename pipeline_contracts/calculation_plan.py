"""Versioned calculation plans and deterministic CP2K task compilation."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PLAN_SCHEMA_VERSION = "1.0"
ALLOWED_OPERATIONS = {"cp2k.geo_opt", "cp2k.energy", "dft.artifact.read"}
REQUIRED_METHOD = {"xc", "basis_set", "pseudopotential", "cutoff_ry", "scf", "charge", "multiplicity"}

class PlanValidationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues)
        super().__init__("; ".join(issues))

def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class CalculationPlan:
    schema_version: str
    plan_id: str
    title: str
    scientific_question: str
    project_root: str
    structure: Mapping[str, Any]
    method: Mapping[str, Any]
    calculations: tuple[Mapping[str, Any], ...]
    execution: Mapping[str, Any]
    analysis: Mapping[str, Any]
    quality_gates: Mapping[str, Any]
    retry_policy: Mapping[str, Any]
    metadata: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CalculationPlan":
        if not isinstance(raw, Mapping):
            raise PlanValidationError(["plan root must be a mapping"])
        return cls(str(raw.get("schema_version", "")), str(raw.get("plan_id", "")),
                   str(raw.get("title", "")), str(raw.get("scientific_question", "")),
                   str(raw.get("project_root", "")), dict(raw.get("structure") or {}),
                   dict(raw.get("method") or {}), tuple(dict(x) for x in raw.get("calculations", [])),
                   dict(raw.get("execution") or {}), dict(raw.get("analysis") or {}),
                   dict(raw.get("quality_gates") or {}), dict(raw.get("retry_policy") or {}),
                   dict(raw.get("metadata") or {}))

    @classmethod
    def load(cls, path: str | Path) -> "CalculationPlan":
        source = Path(path); content = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".json": raw = json.loads(content)
        else:
            try: import yaml
            except ImportError as exc:
                raise PlanValidationError(["YAML input requires PyYAML; JSON is supported without dependencies"]) from exc
            raw = yaml.safe_load(content)
        return cls.from_mapping(raw)

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "plan_id": self.plan_id, "title": self.title,
                "scientific_question": self.scientific_question, "project_root": self.project_root,
                "structure": dict(self.structure), "method": dict(self.method),
                "calculations": [dict(x) for x in self.calculations], "execution": dict(self.execution),
                "analysis": dict(self.analysis), "quality_gates": dict(self.quality_gates),
                "retry_policy": dict(self.retry_policy), "metadata": dict(self.metadata)}

    @property
    def sha256(self) -> str: return canonical_hash(self.as_dict())

    def validate(self) -> list[str]:
        issues = []
        for key, value in (("plan_id", self.plan_id), ("title", self.title),
                           ("scientific_question", self.scientific_question), ("project_root", self.project_root)):
            if not value.strip(): issues.append(f"{key} is required")
        if self.schema_version != PLAN_SCHEMA_VERSION: issues.append(f"schema_version must be {PLAN_SCHEMA_VERSION!r}")
        if not (self.structure.get("path") or self.structure.get("artifact_id")):
            issues.append("structure.path or structure.artifact_id is required")
        missing = sorted(REQUIRED_METHOD - set(self.method))
        if missing: issues.append("missing scientific method fields: " + ", ".join(missing))
        try:
            if float(self.method.get("cutoff_ry", 1)) <= 0: issues.append("method.cutoff_ry must be positive")
            if int(self.method.get("multiplicity", 1)) < 1: issues.append("method.multiplicity must be >= 1")
        except (TypeError, ValueError): issues.append("method.cutoff_ry and multiplicity must be numeric")
        if not self.calculations: issues.append("at least one calculation stage is required")
        names = [str(x.get("id", "")) for x in self.calculations]
        if len(set(names)) != len(names) or any(not x for x in names):
            issues.append("calculation stage IDs must be non-empty and unique")
        for stage in self.calculations:
            if stage.get("operation") not in ALLOWED_OPERATIONS:
                issues.append(f"unsupported operation {stage.get('operation')!r}; registered: {sorted(ALLOWED_OPERATIONS)}")
            if stage.get("operation") in {"cp2k.geo_opt", "cp2k.energy"} and not stage.get("tool_version"):
                issues.append(f"{stage.get('id')}: CP2K tool_version is required")
        if not self.execution.get("backend"): issues.append("execution.backend alias is required")
        if not isinstance(self.execution.get("resources"), Mapping) or not self.execution.get("resources"):
            issues.append("execution.resources reference is required")
        if not self.analysis.get("operation"): issues.append("analysis.operation is required")
        if "geo_opt_converged" not in self.quality_gates: issues.append("quality_gates.geo_opt_converged rule is required")
        try:
            if int(self.retry_policy.get("infrastructure_retries", 0)) < 0: issues.append("retry_policy.infrastructure_retries cannot be negative")
        except (TypeError, ValueError): issues.append("retry_policy.infrastructure_retries must be an integer")
        return issues

    def require_valid(self):
        issues = self.validate()
        if issues: raise PlanValidationError(issues)

def compile_initial_tasks(plan: CalculationPlan) -> list[dict[str, Any]]:
    """Only GEO_OPT is materialized initially; ENERGY is created after QC passes."""
    plan.require_valid()
    stage = next((x for x in plan.calculations if x.get("operation") == "cp2k.geo_opt"), None)
    if stage is None: raise PlanValidationError(["MVP requires a cp2k.geo_opt stage"])
    params = {"method": dict(plan.method), "stage": dict(stage), "resources": dict(plan.execution["resources"])}
    task_id = "geo-opt-" + canonical_hash({"plan": plan.sha256, "parameters": params})[:16]
    return [{"task_id": task_id, "stage_id": str(stage["id"]), "operation": "cp2k.geo_opt",
             "dependencies": [], "input": dict(plan.structure), "parameters": params,
             "parameter_hash": canonical_hash(params), "input_hash": canonical_hash(plan.structure),
             "tool_version": str(stage["tool_version"]), "backend": str(plan.execution["backend"]),
             "resources": dict(plan.execution["resources"]),
             "expected_outputs": list(stage.get("outputs", ["cp2k_output", "optimized_structure"])),
             "status": "PENDING"}]

def compile_energy_task(plan: CalculationPlan, geo_task: Mapping[str, Any],
                        optimized_artifact: Mapping[str, Any]) -> dict[str, Any]:
    stage = next((x for x in plan.calculations if x.get("operation") == "cp2k.energy"), None)
    if stage is None: raise PlanValidationError(["converged GEO_OPT has no declared cp2k.energy stage"])
    params = {"method": dict(plan.method), "stage": dict(stage), "resources": dict(plan.execution["resources"])}
    source = {"artifact_id": optimized_artifact["artifact_id"], "sha256": optimized_artifact["sha256"]}
    task_id = "energy-" + canonical_hash({"input": source, "parameters": params})[:16]
    return {"task_id": task_id, "stage_id": str(stage["id"]), "operation": "cp2k.energy",
            "dependencies": [str(geo_task["task_id"])], "input": source, "parameters": params,
            "parameter_hash": canonical_hash(params), "input_hash": canonical_hash(source),
            "tool_version": str(stage["tool_version"]), "backend": str(plan.execution["backend"]),
            "resources": dict(plan.execution["resources"]),
            "expected_outputs": list(stage.get("outputs", ["cp2k_output", "energy"])), "status": "PENDING"}
