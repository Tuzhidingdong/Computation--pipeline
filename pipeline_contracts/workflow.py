"""SQLite-backed resumable workflow controller with submission intent and process lock."""
from __future__ import annotations
import inspect, json, os, sqlite3, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol
from .calculation_plan import CalculationPlan, compile_initial_tasks, compile_energy_task
from .hpc_runtime import SubmissionUnknown

TASK_STATES={"PENDING","READY","SUBMITTING","SUBMITTED","QUEUED","RUNNING","POSTPROCESSING","QC_PASSED","COMPLETED","RETRY_WAIT","BLOCKED","FAILED_PERMANENT","FAILED_INFRASTRUCTURE","CANCELLED","INTERRUPTED_RECOVERY","SUBMISSION_UNKNOWN","UNAVAILABLE"}

@dataclass(frozen=True)
class ExecutionResult:
    status: str
    job_id: str|None=None
    scheduler_state: str="UNKNOWN"
    application_exit_code: int|None=None
    output_artifacts: tuple[Mapping[str,Any],...]=()
    converged: bool|None=None
    qc: Mapping[str,Any]=field(default_factory=dict)
    analysis_run_id: str|None=None
    evidence_package_id: str|None=None
    diagnostics: tuple[str,...]=()
    state_trace: tuple[str,...]=()
    execution_mode: str="mock"
    runtime: Mapping[str,Any]=field(default_factory=dict)

class JobSubmissionInterrupted(ConnectionError):
    def __init__(self,job_id,message):
        self.job_id=job_id
        super().__init__(message)

class WorkflowAdapter(Protocol):
    def preflight(self,task:Mapping[str,Any])->Mapping[str,Any]: ...
    def execute(self,task:Mapping[str,Any],existing_job_id:str|None=None,**kwargs:Any)->ExecutionResult: ...
    def analyze(self,task:Mapping[str,Any],artifacts:tuple[Mapping[str,Any],...])->ExecutionResult: ...

class WorkflowStore:
    """SQLite control ledger; artifact/evidence data remain upstream-owned."""
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self._db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        self._db.row_factory=sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL"); self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_runs(run_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,plan_hash TEXT NOT NULL,plan_json TEXT NOT NULL,status TEXT NOT NULL,execution_mode TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_tasks(run_id TEXT NOT NULL,task_id TEXT NOT NULL,stage_id TEXT NOT NULL,operation TEXT NOT NULL,dependencies_json TEXT NOT NULL,task_json TEXT NOT NULL,status TEXT NOT NULL,job_id TEXT,result_json TEXT,error TEXT,updated_at REAL NOT NULL,PRIMARY KEY(run_id,task_id),FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id));
        CREATE TABLE IF NOT EXISTS workflow_attempts(run_id TEXT NOT NULL,task_id TEXT NOT NULL,attempt_id TEXT NOT NULL,started_at REAL NOT NULL,finished_at REAL,status TEXT NOT NULL,job_id TEXT,diagnostics_json TEXT NOT NULL,PRIMARY KEY(run_id,task_id,attempt_id),FOREIGN KEY(run_id,task_id) REFERENCES workflow_tasks(run_id,task_id));
        CREATE TABLE IF NOT EXISTS workflow_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,task_id TEXT,event TEXT NOT NULL,payload_json TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_locks(run_id TEXT PRIMARY KEY,owner_token TEXT NOT NULL,owner_pid INTEGER NOT NULL,acquired_at REAL NOT NULL,FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id));
        """)
    def close(self): self._db.close()
    def create_run(self,plan,mode):
        rid="wf-"+uuid.uuid4().hex[:16]; now=time.time()
        self._db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",(rid,plan.plan_id,plan.sha256,json.dumps(plan.as_dict(),sort_keys=True,ensure_ascii=False),"PENDING",mode,now,now))
        return rid
    def add_task(self,rid,task):
        self._db.execute("INSERT OR IGNORE INTO workflow_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",(rid,task["task_id"],task["stage_id"],task["operation"],json.dumps(task.get("dependencies",[])),json.dumps(dict(task),sort_keys=True,ensure_ascii=False),task.get("status","PENDING"),None,None,None,time.time()))
    def task(self,rid,tid):
        row=self._db.execute("SELECT * FROM workflow_tasks WHERE run_id=? AND task_id=?",(rid,tid)).fetchone()
        if row is None: raise KeyError(tid)
        return dict(row)
    def tasks(self,rid): return [dict(x) for x in self._db.execute("SELECT * FROM workflow_tasks WHERE run_id=? ORDER BY rowid",(rid,))]
    def event(self,rid,tid,event,payload):
        self._db.execute("INSERT INTO workflow_events(run_id,task_id,event,payload_json,created_at) VALUES(?,?,?,?,?)",(rid,tid,event,json.dumps(dict(payload),sort_keys=True,ensure_ascii=False),time.time()))
    def update_task(self,rid,tid,status,*,job_id=None,result=None,error=None,merge_result=False):
        if status not in TASK_STATES: raise ValueError(f"invalid task state: {status}")
        serialized=None
        if result is not None:
            value=dict(result)
            if merge_result:
                old=self._db.execute("SELECT result_json FROM workflow_tasks WHERE run_id=? AND task_id=?",(rid,tid)).fetchone()
                previous=json.loads(old["result_json"]) if old and old["result_json"] else {}
                previous.update(value); value=previous
            serialized=json.dumps(value,sort_keys=True,ensure_ascii=False)
        self._db.execute("UPDATE workflow_tasks SET status=?,job_id=COALESCE(?,job_id),result_json=COALESCE(?,result_json),error=?,updated_at=? WHERE run_id=? AND task_id=?",(status,job_id,serialized,error,time.time(),rid,tid))
        self.event(rid,tid,status,{"job_id":job_id,"error":error})
    def persist_submission_intent(self,rid,tid,details):
        self.update_task(rid,tid,"SUBMITTING",result={"submission_intent":True,**dict(details),"execution_mode":"real"},merge_result=True)
        self.event(rid,tid,"SUBMISSION_INTENT_DURABLE",dict(details))
    def persist_job_id(self,rid,tid,job_id,details):
        self.update_task(rid,tid,"SUBMITTED",job_id=job_id,result={"job_id":job_id,"submission_intent":True,**dict(details),"execution_mode":"real"},merge_result=True)
        self.event(rid,tid,"HPC_JOB_ID_DURABLE",{"job_id":job_id,**dict(details)})
    def attempt_start(self,rid,tid,job_id=None):
        aid="att-"+uuid.uuid4().hex[:12]
        self._db.execute("INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?)",(rid,tid,aid,time.time(),None,"RUNNING",job_id,"[]"))
        return aid
    def attempt_finish(self,rid,tid,aid,status,job_id,diagnostics):
        self._db.execute("UPDATE workflow_attempts SET finished_at=?,status=?,job_id=?,diagnostics_json=? WHERE run_id=? AND task_id=? AND attempt_id=?",(time.time(),status,job_id,json.dumps(list(diagnostics)),rid,tid,aid))
    def run_info(self,rid):
        row=self._db.execute("SELECT * FROM workflow_runs WHERE run_id=?",(rid,)).fetchone()
        if row is None: raise KeyError(rid)
        return dict(row)
    def set_run_status(self,rid,status):
        self._db.execute("UPDATE workflow_runs SET status=?,updated_at=? WHERE run_id=?",(status,time.time(),rid))
    def events(self,rid): return [dict(x) for x in self._db.execute("SELECT * FROM workflow_events WHERE run_id=? ORDER BY event_id",(rid,))]
    @staticmethod
    def _pid_alive(pid):
        try: os.kill(pid,0)
        except ProcessLookupError: return False
        except (PermissionError,OSError): return True
        return True
    def acquire_run_lock(self,rid):
        token=uuid.uuid4().hex; self._db.execute("BEGIN IMMEDIATE")
        try:
            row=self._db.execute("SELECT owner_pid FROM workflow_locks WHERE run_id=?",(rid,)).fetchone()
            if row and self._pid_alive(int(row["owner_pid"])):
                self._db.execute("ROLLBACK"); return None
            if row: self._db.execute("DELETE FROM workflow_locks WHERE run_id=?",(rid,))
            self._db.execute("INSERT INTO workflow_locks VALUES(?,?,?,?)",(rid,token,os.getpid(),time.time()))
            self._db.execute("COMMIT"); return token
        except Exception:
            self._db.execute("ROLLBACK"); raise
    def release_run_lock(self,rid,token):
        self._db.execute("DELETE FROM workflow_locks WHERE run_id=? AND owner_token=?",(rid,token))

class WorkflowController:
    def __init__(self,store:WorkflowStore,adapter:WorkflowAdapter|None): self.store,self.adapter=store,adapter
    def create(self,plan):
        plan.require_valid()
        mode=getattr(self.adapter,"execution_mode","real") if self.adapter else "real"
        input_identity=None
        resolution_error=None
        resolver=getattr(self.adapter,"resolve_plan_input",None)
        if callable(resolver):
            try:
                input_identity=resolver()
            except Exception as exc:
                resolution_error=f"{type(exc).__name__}: {exc}"
        rid=self.store.create_run(plan,mode)
        tasks=compile_initial_tasks(plan,input_identity=input_identity)
        for task in tasks:
            self.store.add_task(rid,task)
        self.store.event(rid,None,"PLAN_COMPILED",{"plan_hash":plan.sha256,"input_identity":input_identity})
        if resolution_error:
            self.store.update_task(rid,tasks[0]["task_id"],"UNAVAILABLE",error=resolution_error)
            self.store.set_run_status(rid,"UNAVAILABLE")
            self.store.event(rid,tasks[0]["task_id"],"INPUT_ARTIFACT_UNAVAILABLE",{"reason":resolution_error})
        return rid
    @staticmethod
    def _decode_runtime(row):
        try: return json.loads(row.get("result_json") or "{}")
        except (TypeError,json.JSONDecodeError): return {}
    @staticmethod
    def _execute(adapter,task,job,runtime,on_intent,on_job):
        method=adapter.execute
        try:
            params=inspect.signature(method).parameters
            accepts_kwargs=any(p.kind==inspect.Parameter.VAR_KEYWORD for p in params.values())
        except (TypeError,ValueError): params,accepts_kwargs={},False
        kwargs={}
        for key,val in (("runtime_state",runtime),("on_submission_intent",on_intent),("on_job_submitted",on_job)):
            if accepts_kwargs or key in params: kwargs[key]=val
        return method(task,existing_job_id=job,**kwargs)
    def run(self,rid,plan):
        if self.store.run_info(rid)["status"]=="UNAVAILABLE":
            return "UNAVAILABLE"
        if self.adapter is None:
            self.store.set_run_status(rid,"UNAVAILABLE"); self.store.event(rid,None,"ADAPTER_UNAVAILABLE",{"message":"No real adapter injected; no Mock fallback."}); return "UNAVAILABLE"
        lock=self.store.acquire_run_lock(rid)
        if lock is None:
            self.store.event(rid,None,"RUN_LOCKED",{"pid":os.getpid()}); return "LOCKED"
        try:
            self.store.set_run_status(rid,"RUNNING"); processed=set()
            while True:
                row=next((x for x in self.store.tasks(rid) if x["status"]!="COMPLETED" and x["task_id"] not in processed),None)
                if row is None: break
                tid=row["task_id"]; processed.add(tid); state=row["status"]
                if state in {"FAILED_PERMANENT","FAILED_INFRASTRUCTURE","CANCELLED","RETRY_WAIT"}:
                    final = {
                        "FAILED_PERMANENT": "FAILED",
                        "FAILED_INFRASTRUCTURE": "FAILED_INFRASTRUCTURE",
                        "CANCELLED": "CANCELLED",
                        "RETRY_WAIT": "RETRY_WAIT",
                    }[state]
                    self.store.set_run_status(rid,final); return final
                task=json.loads(row["task_json"]); deps=json.loads(row["dependencies_json"])
                if any(self.store.task(rid,d)["status"]!="COMPLETED" for d in deps):
                    self.store.update_task(rid,tid,"BLOCKED",error="Dependency has not completed."); continue
                preflight=self.adapter.preflight(task)
                if not preflight.get("ready"):
                    reason=str(preflight.get("reason") or preflight.get("status") or "real runtime unavailable")
                    outcome="UNAVAILABLE" if str(preflight.get("status","")).upper()=="UNAVAILABLE" else "BLOCKED"
                    self.store.update_task(rid,tid,outcome,error=reason); self.store.set_run_status(rid,outcome)
                    self.store.event(rid,tid,"PREFLIGHT_BLOCKED",{"reason":reason}); return outcome
                runtime=self._decode_runtime(row); existing=row.get("job_id")
                aid=self.store.attempt_start(rid,tid,existing)
                def on_intent(details): self.store.persist_submission_intent(rid,tid,details)
                def on_job(job_id,details): self.store.persist_job_id(rid,tid,job_id,details)
                self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY" if existing or state in {"SUBMITTING","SUBMISSION_UNKNOWN"} else "READY",job_id=existing)
                try:
                    result=self._execute(self.adapter,task,existing,runtime,on_intent,on_job)
                    for observed in result.state_trace:
                        if observed in {"SUBMITTED","QUEUED","RUNNING"}:
                            self.store.update_task(rid,tid,observed,job_id=result.job_id)
                    payload={"status":result.status,"job_id":result.job_id,"scheduler_state":result.scheduler_state,
                        "application_exit_code":result.application_exit_code,"output_artifacts":[dict(x) for x in result.output_artifacts],
                        "converged":result.converged,"qc":dict(result.qc),"analysis_run_id":result.analysis_run_id,
                        "evidence_package_id":result.evidence_package_id,"diagnostics":list(result.diagnostics),
                        "execution_mode":result.execution_mode,**dict(result.runtime)}
                    if result.job_id and not existing: on_job(result.job_id,payload)
                    if result.status in {"SUBMITTED","QUEUED","RUNNING","SUBMISSION_UNKNOWN","INTERRUPTED_RECOVERY","RETRY_WAIT","BLOCKED","UNAVAILABLE","FAILED_INFRASTRUCTURE","CANCELLED"}:
                        self.store.update_task(rid,tid,result.status,job_id=result.job_id,result=payload,error="; ".join(result.diagnostics) or None,merge_result=True)
                        self.store.attempt_finish(rid,tid,aid,result.status,result.job_id,result.diagnostics)
                        self.store.set_run_status(rid,result.status); return result.status
                    if result.status!="COMPLETED":
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",job_id=result.job_id,result=payload,error="; ".join(result.diagnostics) or result.status,merge_result=True)
                        self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics)
                        self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    if result.scheduler_state!="COMPLETED" or result.application_exit_code!=0 or not result.output_artifacts:
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",job_id=result.job_id,result=payload,error="Scheduler completion is insufficient: app exit code/output verification missing.",merge_result=True)
                        self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics)
                        self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    self.store.update_task(rid,tid,"POSTPROCESSING",job_id=result.job_id,result=payload,merge_result=True)
                    if task["operation"]=="cp2k.geo_opt":
                        if result.converged is not True:
                            self.store.update_task(rid,tid,"FAILED_PERMANENT",result=payload,error="GEO_OPT convergence gate failed; ENERGY not created.",merge_result=True)
                            self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics)
                            self.store.set_run_status(rid,"FAILED"); return "FAILED"
                        optimized=next((x for x in result.output_artifacts if x.get("kind")=="optimized_structure" and x.get("sha256")),None)
                        if optimized is None:
                            self.store.update_task(rid,tid,"FAILED_PERMANENT",result=payload,error="Optimized structure Artifact/SHA256 missing.",merge_result=True)
                            self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,result.diagnostics)
                            self.store.set_run_status(rid,"FAILED"); return "FAILED"
                        self.store.update_task(rid,tid,"QC_PASSED",result=payload,merge_result=True)
                        nxt=compile_energy_task(plan,task,optimized); self.store.add_task(rid,nxt)
                        self.store.event(rid,tid,"DYNAMIC_TASK_ADDED",{"task_id":nxt["task_id"],"condition":"geo_opt_converged","parent_artifact_id":optimized["artifact_id"],"parent_sha256":optimized["sha256"]})
                        self.store.update_task(rid,tid,"COMPLETED",result=payload,merge_result=True)
                    elif task["operation"]=="cp2k.energy":
                        analysis_task=dict(task); analysis_task["_upstream_job_reference"]=result.job_id
                        analysis=self.adapter.analyze(analysis_task,result.output_artifacts)
                        if analysis.status!="COMPLETED" or not analysis.analysis_run_id or not analysis.evidence_package_id:
                            self.store.update_task(rid,tid,"FAILED_PERMANENT",result=analysis.__dict__,error="Data_analysis Analysis Run/Evidence incomplete.")
                            self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",result.job_id,analysis.diagnostics)
                            self.store.set_run_status(rid,"FAILED"); return "FAILED"
                        self.store.update_task(rid,tid,"COMPLETED",result=analysis.__dict__)
                    else:
                        self.store.update_task(rid,tid,"FAILED_PERMANENT",error="No registered workflow executor.")
                        self.store.set_run_status(rid,"FAILED"); return "FAILED"
                    self.store.attempt_finish(rid,tid,aid,"COMPLETED",result.job_id,result.diagnostics)
                except SubmissionUnknown as exc:
                    self.store.update_task(rid,tid,"SUBMISSION_UNKNOWN",result={"submission_intent":True,"remote_workdir":exc.remote_workdir,"execution_mode":"real"},error=str(exc),merge_result=True)
                    self.store.attempt_finish(rid,tid,aid,"SUBMISSION_UNKNOWN",existing,[str(exc)])
                    self.store.set_run_status(rid,"SUBMISSION_UNKNOWN"); return "SUBMISSION_UNKNOWN"
                except JobSubmissionInterrupted as exc:
                    self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY",job_id=exc.job_id,error=str(exc))
                    self.store.attempt_finish(rid,tid,aid,"INTERRUPTED_RECOVERY",exc.job_id,[str(exc)])
                    self.store.set_run_status(rid,"INTERRUPTED_RECOVERY"); return "INTERRUPTED_RECOVERY"
                except (ConnectionError,TimeoutError) as exc:
                    self.store.update_task(rid,tid,"INTERRUPTED_RECOVERY",job_id=existing,error=str(exc))
                    self.store.attempt_finish(rid,tid,aid,"INTERRUPTED_RECOVERY",existing,[str(exc)])
                    self.store.set_run_status(rid,"INTERRUPTED_RECOVERY"); return "INTERRUPTED_RECOVERY"
                except Exception as exc:
                    message=f"{type(exc).__name__}: {exc}"
                    self.store.update_task(rid,tid,"FAILED_PERMANENT",job_id=existing,error=message)
                    self.store.attempt_finish(rid,tid,aid,"FAILED_PERMANENT",existing,[message])
                    self.store.set_run_status(rid,"FAILED"); return "FAILED"
            states=[x["status"] for x in self.store.tasks(rid)]
            final="COMPLETED" if states and all(x=="COMPLETED" for x in states) else "BLOCKED"
            self.store.set_run_status(rid,final); return final
        finally:
            self.store.release_run_lock(rid,lock)
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
                self._interrupted=True; raise JobSubmissionInterrupted(job,"simulated connection loss after durable Job ID")
        self.polls[tid]=self.polls.get(tid,0)+1
        converged=self.geo_opt_converged if task["operation"]=="cp2k.geo_opt" else True
        if task["operation"]=="cp2k.geo_opt":
            artifacts=({"artifact_id":"mock-"+tid+"-output","sha256":"a"*64,"kind":"cp2k_output"},
                       {"artifact_id":"mock-"+tid+"-structure","sha256":"b"*64,"kind":"optimized_structure"})
        else: artifacts=({"artifact_id":"mock-"+tid+"-energy","sha256":"c"*64,"kind":"cp2k_output"},)
        return ExecutionResult("COMPLETED",job,"COMPLETED",0,artifacts,converged,{"converged":converged},
            state_trace=("SUBMITTED","QUEUED","RUNNING","COMPLETED"),execution_mode="mock")
    def analyze(self,task,artifacts):
        return ExecutionResult("COMPLETED",scheduler_state="NOT_APPLICABLE",application_exit_code=0,
            output_artifacts=({"artifact_id":"mock-derived-"+task["task_id"],"sha256":"d"*64,"kind":"derived"},),
            analysis_run_id="mock-analysis-"+task["task_id"],evidence_package_id="mock-evidence-"+task["task_id"],
            execution_mode="mock")
