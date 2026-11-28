"""Project stages persisted in the existing WorkflowStore SQLite ledger."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import json
import time
import uuid

from .workflow import WorkflowStore
from .calculation_plan import CalculationPlan
from projects.corr_dft_v4_1.model_plugin.approval import verify_approval_record, verify_approval_record_integrity

PROJECT_STAGES = (
    "DOCX_INGEST", "PLAN_COMPILE", "EVIDENCE_REVIEW", "MODEL_GENERATE",
    "MODEL_VALIDATE", "MODEL_REVIEW", "MODEL_APPROVAL", "MODEL_ARTIFACT_FREEZE",
    "CALCULATION_PLAN", "WORKFLOW_EXECUTION", "RESULT_DELIVERY",
)
PROJECT_STATES = {"PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED", "AWAITING_APPROVAL"}


class ProjectLifecycle:
    """Project-stage records share the WorkflowStore database; no second ledger is created."""
    def __init__(self, workflow_store: WorkflowStore):
        self.store = workflow_store
        self.db = workflow_store._db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS project_lifecycle_runs(
          project_run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, manifest_json TEXT,
          status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_lifecycle_tasks(
          project_run_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
          input_json TEXT NOT NULL, output_json TEXT, error TEXT, updated_at REAL NOT NULL,
          PRIMARY KEY(project_run_id, stage),
          FOREIGN KEY(project_run_id) REFERENCES project_lifecycle_runs(project_run_id)
        );
        CREATE TABLE IF NOT EXISTS model_approval_records(
          project_run_id TEXT NOT NULL, candidate_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
          structure_sha256 TEXT NOT NULL, record_json TEXT NOT NULL, created_at REAL NOT NULL,
          PRIMARY KEY(project_run_id, candidate_id),
          FOREIGN KEY(project_run_id) REFERENCES project_lifecycle_runs(project_run_id)
        );
        """)
    def create(self, project_id: str, manifest: Mapping[str, Any]) -> str:
        run_id = "project-" + uuid.uuid4().hex[:16]
        now = time.time()
        payload = json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True)
        self.db.execute("INSERT INTO project_lifecycle_runs VALUES(?,?,?,?,?,?)",
                        (run_id, project_id, payload, "PENDING", now, now))
        for stage in PROJECT_STAGES:
            self.db.execute("INSERT INTO project_lifecycle_tasks VALUES(?,?,?,?,?,?,?)",
                            (run_id, stage, "PENDING", "{}", None, None, now))
        self.store.event(run_id, None, "PROJECT_LIFECYCLE_CREATED",
                         {"project_id": project_id, "stages": list(PROJECT_STAGES)})
        return run_id

    def run_info(self, run_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM project_lifecycle_runs WHERE project_run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json") or "{}")
        return result

    def manifest(self, run_id: str) -> dict:
        return self.run_info(run_id)["manifest"]

    def update_manifest(self, run_id: str, manifest: Mapping[str, Any]) -> None:
        self.db.execute(
            "UPDATE project_lifecycle_runs SET manifest_json=?,updated_at=? WHERE project_run_id=?",
            (json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True), time.time(), run_id),
        )
        self.store.event(run_id, None, "PROJECT_MANIFEST_UPDATED",
                         {"manifest_keys": sorted(manifest.keys())})

    def stages(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM project_lifecycle_tasks WHERE project_run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        if not rows:
            raise KeyError(run_id)
        result = []
        for raw in rows:
            item = dict(raw)
            item["inputs"] = json.loads(item.pop("input_json") or "{}")
            item["outputs"] = json.loads(item.pop("output_json") or "{}")
            result.append(item)
        return result

    def stage(self, run_id: str, name: str) -> dict:
        for item in self.stages(run_id):
            if item["stage"] == name:
                return item
        raise KeyError(f"{run_id}:{name}")

    def transition(self, run_id: str, stage: str, status: str, *,
                   inputs: Mapping[str, Any] | None = None,
                   outputs: Mapping[str, Any] | None = None, error: str | None = None):
        if stage not in PROJECT_STAGES or status not in PROJECT_STATES:
            raise ValueError("unknown project stage or status")
        row = self.db.execute(
            "SELECT stage FROM project_lifecycle_tasks WHERE project_run_id=? AND stage=?",
            (run_id, stage),
        ).fetchone()
        if row is None:
            raise KeyError(f"{run_id}:{stage}")
        stage_index = PROJECT_STAGES.index(stage)
        if stage_index:
            previous = self.db.execute(
                "SELECT status FROM project_lifecycle_tasks WHERE project_run_id=? AND stage=?",
                (run_id, PROJECT_STAGES[stage_index - 1]),
            ).fetchone()
            if previous is None or previous["status"] != "COMPLETED":
                raise RuntimeError(f"{stage} is blocked until {PROJECT_STAGES[stage_index - 1]} completes")
        self.db.execute(
            "UPDATE project_lifecycle_tasks SET status=?,input_json=?,output_json=?,error=?,updated_at=? "
            "WHERE project_run_id=? AND stage=?",
            (status, json.dumps(dict(inputs or {}), ensure_ascii=False),
             json.dumps(dict(outputs or {}), ensure_ascii=False) if outputs is not None else None,
             error, time.time(), run_id, stage),
        )
        run_status = "AWAITING_APPROVAL" if status == "AWAITING_APPROVAL" else (
            "BLOCKED" if status == "BLOCKED" else "FAILED" if status == "FAILED"
            else "COMPLETED" if stage == PROJECT_STAGES[-1] and status == "COMPLETED"
            else "RUNNING"
        )
        self.db.execute("UPDATE project_lifecycle_runs SET status=?,updated_at=? WHERE project_run_id=?",
                        (run_status, time.time(), run_id))
        self.store.event(run_id, stage, status, {"inputs": dict(inputs or {}),
                                                "outputs": dict(outputs or {}), "error": error})

    def freeze_approval(self, run_id: str, record: Mapping[str, Any]):
        if not verify_approval_record_integrity(record):
            raise ValueError("model approval record or Data_analysis ArtifactRef integrity is invalid")
        approval_stage = self.db.execute(
            "SELECT status FROM project_lifecycle_tasks WHERE project_run_id=? AND stage='MODEL_APPROVAL'",
            (run_id,),
        ).fetchone()
        if approval_stage is None or approval_stage["status"] != "AWAITING_APPROVAL":
            raise RuntimeError("model approval can only be frozen from AWAITING_APPROVAL")
        self.db.execute(
            "INSERT INTO model_approval_records VALUES(?,?,?,?,?,?)",
            (run_id, record["candidate_id"], record["artifact_id"], record["structure_sha256"],
             json.dumps(dict(record), sort_keys=True, ensure_ascii=False), time.time()),
        )
        approval_outputs = self.stage(run_id, "MODEL_APPROVAL")["outputs"]
        approval_outputs.update(dict(record))
        self.transition(run_id, "MODEL_APPROVAL", "COMPLETED", outputs=approval_outputs)
        freeze_outputs = self.stage(run_id, "MODEL_ARTIFACT_FREEZE")["outputs"]
        freeze_outputs.update({"artifact_id": record["artifact_id"],
                               "sha256": record["structure_sha256"]})
        self.transition(run_id, "MODEL_ARTIFACT_FREEZE", "COMPLETED", outputs=freeze_outputs)

    def approval(self, run_id: str, candidate_id: str) -> dict:
        row = self.db.execute(
            "SELECT record_json FROM model_approval_records WHERE project_run_id=? AND candidate_id=?",
            (run_id, candidate_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"no frozen approval for candidate {candidate_id}")
        return json.loads(row["record_json"])

    def create_calculation_run(self, run_id: str, candidate_id: str, structure_path: str | Path,
                               plan: CalculationPlan, controller) -> str:
        """Enter the existing CalculationPlan DAG only with the frozen approved model."""
        record = self.approval(run_id, candidate_id)
        if not verify_approval_record(record, structure_path):
            raise ValueError("approved model bytes changed or approval record integrity failed")
        if (plan.structure.get("artifact_id") != record.get("artifact_id")
                or plan.structure.get("sha256") != record.get("structure_sha256")):
            raise ValueError("CalculationPlan must reference the exact approved Artifact ID and SHA-256")
        plan.require_valid()
        workflow_run_id = controller.create(plan)
        self.transition(run_id, "CALCULATION_PLAN", "COMPLETED", outputs={
            "workflow_run_id": workflow_run_id, "plan_id": plan.plan_id,
            "plan_sha256": plan.sha256,
            "model_artifact_id": record["artifact_id"],
            "model_sha256": record["structure_sha256"],
        })
        return workflow_run_id
