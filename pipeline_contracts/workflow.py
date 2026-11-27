"""SQLite-backed resumable DAG controller; no hidden worker or scheduler service."""
from __future__ import annotations
import json, sqlite3, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol
from .calculation_plan import CalculationPlan, compile_initial_tasks, compile_energy_task

TASK_STATES = {"PENDING","READY","SUBMITTED","QUEUED","RUNNING","POSTPROCESSING","QC_PASSED","COMPLETED","RETRY_WAIT","BLOCKED","FAILED_PERMANENT","CANCELLED","INTERRUPTED_RECOVERY"}

@dataclass(frozen=True)
class ExecutionResult:
    status: str
    job_id: str | None = None
    scheduler_state: str = "UNKNOWN"
    application_exit_code: int | None = None
    output_artifacts: tuple[Mapping[str, Any], ...] = ()
    converged: bool | None = None
    qc: Mapping[str, Any] = field(default_factory=dict)
    analysis_run_id: str | None = None
    evidence_package_id: str | None = None
    diagnostics: tuple[str, ...] = ()
    state_trace: tuple[str, ...] = ()
    execution_mode: str = "mock"

class JobSubmissionInterrupted(ConnectionError):
    def __init__(self, job_id: str, message: str):
        self.job_id = job_id
        super().__init__(message)

class WorkflowAdapter(Protocol):
    def preflight(self, task: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def execute(self, task: Mapping[str, Any], existing_job_id: str | None = None) -> ExecutionResult: ...
    def analyze(self, task: Mapping[str, Any], artifacts: tuple[Mapping[str, Any], ...]) -> ExecutionResult: ...

class WorkflowStore:
    def __init__(self, path: str | Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self._db=sqlite3.connect(self.path,timeout=30); self._db.row_factory=sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL"); self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_runs(run_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,plan_hash TEXT NOT NULL,plan_json TEXT NOT NULL,status TEXT NOT NULL,execution_mode TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_tasks(run_id TEXT NOT NULL,task_id TEXT NOT NULL,stage_id TEXT NOT NULL,operation TEXT NOT NULL,dependencies_json TEXT NOT NULL,task_json TEXT NOT NULL,status TEXT NOT NULL,job_id TEXT,result_json TEXT,error TEXT,updated_at REAL NOT NULL,PRIMARY KEY(run_id,task_id),FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id));
        CREATE TABLE IF NOT EXISTS workflow_attempts(run_id TEXT NOT NULL,task_id TEXT NOT NULL,attempt_id TEXT NOT NULL,started_at REAL NOT NULL,finished_at REAL,status TEXT NOT NULL,job_id TEXT,diagnostics_json TEXT NOT NULL,PRIMARY KEY(run_id,task_id,attempt_id),FOREIGN KEY(run_id,task_id) REFERENCES workflow_tasks(run_id,task_id));
        CREATE TABLE IF NOT EXISTS workflow_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,task_id TEXT,event TEXT NOT NULL,payload_json TEXT NOT NULL,created_at REAL NOT NULL);
        """)
    def close(self): self._db.close()
    def create_run(self,plan,mode):
        rid="wf-"+uuid.uuid4().hex[:16]; now=time.time()
        self._db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",(rid,plan.plan_id,plan.sha256,json.dumps(plan.as_dict(),sort_keys=True),"PENDING",mode,now,now)); self._db.commit(); return rid
    def add_task(self,rid,task):
        self._db.execute("INSERT OR IGNORE INTO workflow_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,task["task_id"],task["stage_id"],task["operation"],json.dumps(task.get("dependencies",[])),json.dumps(dict(task),sort_keys=True),task.get("status","PENDING"),None,None,None,time.time())); self._db.commit()
    def task(self,rid,tid):
        row=self._db.execute("SELECT * FROM workflow_tasks WHERE run_id=? AND task_id=?",(rid,tid)).fetchone()
        if row is None: raise KeyError(tid)
        return dict(row)
    def tasks(self,rid): return [dict(x) for x in self._db.execute("SELECT * FROM workflow_tasks WHERE run_id=? ORDER BY rowid",(rid,))]
    def update_task(self,rid,tid,status,*,job_id=None,result=None,error=None):
        if status not in TASK_STATES: raise ValueError(f"invalid task state: {status}")
        serialized=json.dumps(result,sort_keys=True) if result is not None else None
        self._db.execute("UPDATE workflow_tasks SET status=?,job_id=COALESCE(?,job_id),result_json=COALESCE(?,result_json),error=?,updated_at=? WHERE run_id=? AND task_id=?",(status,job_id,serialized,error,time.time(),rid,tid))
        self._db.commit(); self.event(rid,tid,status,{"job_id":job_id,"error":error})
    def event(self,rid,tid,event,payload):
        self._db.execute("INSERT INTO workflow_events(run_id,task_id,event,payload_json,created_at) VALUES(?,?,?,?,?)",(rid,tid,event,json.dumps(dict(payload),sort_keys=True),time.time())); self._db.commit()
    def attempt_start(self,rid,tid,job_id=None):
        aid="att-"+uuid.uuid4().hex[:12]
        self._db.execute("INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?)",(rid,tid,aid,time.time(),None,"RUNNING",job_id,"[]")); self._db.commit(); return aid
    def attempt_finish(self,rid,tid,aid,status,job_id,diagnostics):
        self._db.execute("UPDATE workflow_attempts SET finished_at=?,status=?,job_id=?,diagnostics_json=? WHERE run_id=? AND task_id=? AND attempt_id=?",(time.time(),status,job_id,json.dumps(list(diagnostics)),rid,tid,aid)); self._db.commit()
    def run_info(self,rid):
        row=self._db.execute("SELECT * FROM workflow_runs WHERE run_id=?",(rid,)).fetchone()
        if row is None: raise KeyError(rid)
        return dict(row)
    def set_run_status(self,rid,status):
        self._db.execute("UPDATE workflow_runs SET status=?,updated_at=? WHERE run_id=?",(status,time.time(),rid)); self._db.commit()
    def events(self,rid): return [dict(x) for x in self._db.execute("SELECT * FROM workflow_events WHERE run_id=? ORDER BY event_id",(rid,))]

class WorkflowController:
    def __init__(self,store:WorkflowStore,adapter:WorkflowAdapter|None): self.store,self.adapter=store,adapter
    def create(self,plan):
        plan.require_valid(); mode=getattr(self.adapter,"execution_mode","real") if self.adapter else "real"
        rid=self.store.create_run(plan,mode)
        for task in compile_initial_tasks(plan): self.store.add_task(rid,task)
        self.store.event(rid,None,"PLAN_COMPILED",{"plan_hash":plan.sha256}); return rid
    def run(self,rid,plan):
        if self.adapter is None:
            self.store.set_run_status(rid,"UNAVAILABLE"); self.store.event(rid,None,"ADAPTER_UNAVAILABLE",{"message":"No execution adapter injected; no Mock fallback."}); return "UNAVAILABLE"
        self.store.set_run_status(rid,"RUNNING"); processed=set()
        while True:
            row=next((x for x in self.store.tasks(rid) if x["status"]!="COMPLETED" and x["task_id"] not in processed),None)
            if row is None: break
            tid=row["task_id"]; processed.add(tid); task=json.loads(row["task_json"]); deps=json.loads(row["dependencies_json"])
            if any(self.store.task(rid,d)["status"]!="COMPLETED" for d in deps):
                self.store.update_task(rid,tid,"BLOCKED",error="Dependency has not completed."); continue
            pf=self.adapter.preflight(task)
            if not pf.get("ready"):
                self.store.update_task(rid,tid,"BLOCKED",error=str(pf.get("reason","preflight unavailable"))); continue
            existing=row["job_id"]; aid=self.store.attempt_start(rid,tid,existing)
            self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY" if existing else "READY",job_id=existing)
            try:
                result=self.adapter.execute(task,existing_job_id=existing)
                for observed_state in result.state_trace:
                    if observed_state in {"SUBMITTED", "QUEUED", "RUNNING"}:
                        self.store.update_task(rid,tid,observed_state,job_id=result.job_id)
                payload={"status":result.status,"job_id":result.job_id,"scheduler_state":result.scheduler_state,
                    "application_exit_code":result.application_exit_code,"output_artifacts":[dict(x) for x in result.output_artifacts],
                    "converged":result.converged,"qc":dict(result.qc),"analysis_run_id":result.analysis_run_id,
                    "evidence_package_id":result.evidence_package_id,"diagnostics":list(result.diagnostics),"execution_mode":result.execution_mode}
                self.store.update_task(rid,tid,"SUBMITTED" if result.job_id else "READY",job_id=result.job_id,result=payload)
                if result.status!="COMPLETED":
                    state=result.status if result.status in TASK_STATES else "RETRY_WAIT"
                    self.store.update_task(rid,tid,state,job_id=result.job_id,result=payload)
                    self.store.attempt_finish(rid,tid,aid,state,result.job_id,result.diagnostics); self.store.set_run_status(rid,state); return state
                if result.scheduler_state!="COMPLETED" or result.application_exit_code!=0 or not result.output_artifacts:
                    self.store.update_task(rid,tid,"FAILED_PERMANENT",job_id=result.job_id,result=payload,error="Scheduler completion is insufficient: application exit/output check failed.")
                    self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics); self.store.set_run_status(rid,"FAILED"); return "FAILED"
                self.store.update_task(rid,tid,"POSTPROCESSING",job_id=result.job_id,result=payload)
                if task["operation"]=="cp2k.geo_opt":
                    if result.converged is not True:
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",result=payload,error="GEO_OPT convergence gate failed; ENERGY was not created.")
                        self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics); self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    optimized=next((x for x in result.output_artifacts if x.get("kind")=="optimized_structure" and x.get("sha256")),None)
                    if optimized is None:
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",result=payload,error="Optimized structure Artifact/hash missing.")
                        self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics); self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    self.store.update_task(rid,tid,"QC_PASSED",result=payload)
                    nxt=compile_energy_task(plan,task,optimized); self.store.add_task(rid,nxt)
                    self.store.event(rid,tid,"DYNAMIC_TASK_ADDED",{"task_id":nxt["task_id"],"condition":"geo_opt_converged"})
                    self.store.update_task(rid,tid,"COMPLETED",result=payload)
                elif task["operation"]=="cp2k.energy":
                    analysis=self.adapter.analyze(task,result.output_artifacts)
                    if analysis.status!="COMPLETED" or not analysis.analysis_run_id or not analysis.evidence_package_id:
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",result=analysis.__dict__,error="Analysis Run/Evidence Package incomplete.")
                        self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,analysis.diagnostics); self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    self.store.update_task(rid,tid,"COMPLETED",result=analysis.__dict__)
                else:
                    self.store.update_task(rid,tid,"FAILED_PERMANENT",error="No registered executor for operation.")
                self.store.attempt_finish(rid,tid,aid,"COMPLETED",result.job_id,result.diagnostics)
            except JobSubmissionInterrupted as exc:
                self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY",job_id=exc.job_id,error=str(exc))
                self.store.attempt_finish(rid,tid,aid,"INTERRUPTED_RECOVERY",exc.job_id,[str(exc)])
                self.store.set_run_status(rid,"INTERRUPTED_RECOVERY"); return "INTERRUPTED_RECOVERY"
            except (ConnectionError,TimeoutError) as exc:
                self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY",job_id=existing,error=str(exc))
                self.store.attempt_finish(rid,tid,aid,"INTERRUPTED_RECOVERY",existing,[str(exc)])
                self.store.set_run_status(rid,"INTERRUPTED_RECOVERY"); return "INTERRUPTED_RECOVERY"
            except Exception as exc:
                self.store.update_task(rid,tid,"FAILED_PERMANENT",job_id=existing,error=f"{type(exc).__name__}: {exc}")
                self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",existing,[str(exc)])
                self.store.set_run_status(rid,"FAILED"); return "FAILED"
        states=[x["status"] for x in self.store.tasks(rid)]
        final="COMPLETED" if states and all(x=="COMPLETED" for x in states) else "BLOCKED"
        self.store.set_run_status(rid,final); return final
    def resume(self,rid,plan):
        self.store.event(rid,None,"RESUME_REQUESTED",{}); return self.run(rid,plan)
    def report(self,rid):
        info=self.store.run_info(rid); tasks=self.store.tasks(rid)
        counts={s:sum(x["status"]==s for x in tasks) for s in sorted(TASK_STATES)}
        return {"workflow_run_id":rid,"plan_id":info["plan_id"],"plan_sha256":info["plan_hash"],
                "status":info["status"],"execution_mode":info["execution_mode"],"task_counts":counts,
                "tasks":tasks,"events":self.store.events(rid)}

class MockCP2KWorkflowAdapter:
    """Lifecycle simulator only; never executes CP2K or claims scientific data."""
    execution_mode="mock"
    def __init__(self,*,geo_opt_converged=True,interrupt_once=False):
        self.geo_opt_converged=geo_opt_converged; self.interrupt_once=interrupt_once
        self.submissions={}; self.polls={}; self._interrupted=False
    def preflight(self,task): return {"ready":True,"mode":"mock"}
    def execute(self,task,existing_job_id=None):
        tid=task["task_id"]; job=existing_job_id or self.submissions.get(tid)
        if job is None:
            job="mock-"+tid; self.submissions[tid]=job
            if self.interrupt_once and not self._interrupted:
                self._interrupted=True; raise JobSubmissionInterrupted(job,"simulated network loss after durable Job ID")
        self.polls[tid]=self.polls.get(tid,0)+1
        converged=self.geo_opt_converged if task["operation"]=="cp2k.geo_opt" else True
        if task["operation"]=="cp2k.geo_opt":
            arts=({"artifact_id":"mock-"+tid+"-output","sha256":"a"*64,"kind":"cp2k_output"},
                  {"artifact_id":"mock-"+tid+"-structure","sha256":"b"*64,"kind":"optimized_structure"})
        else: arts=({"artifact_id":"mock-"+tid+"-energy","sha256":"c"*64,"kind":"cp2k_output"},)
        return ExecutionResult("COMPLETED",job,"COMPLETED",0,arts,converged,{"converged":converged},state_trace=("SUBMITTED","QUEUED","RUNNING","COMPLETED"),execution_mode="mock")
    def analyze(self,task,artifacts):
        return ExecutionResult("COMPLETED",scheduler_state="NOT_APPLICABLE",application_exit_code=0,
            output_artifacts=({"artifact_id":"mock-derived-"+task["task_id"],"sha256":"d"*64,"kind":"derived"},),
            analysis_run_id="mock-analysis-"+task["task_id"],evidence_package_id="mock-evidence-"+task["task_id"],
            execution_mode="mock")
