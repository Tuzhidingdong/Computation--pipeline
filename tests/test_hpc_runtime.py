from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pipeline_contracts.hpc_runtime import (
    BeiLongHPCAdapter, CommandOutput, SubmissionUnknown, UCASHPCAdapter,
    render_beilong_cp2k_script, render_ucas_cp2k_script,
)
from pipeline_contracts.models import ArtifactRef, HpcState, HpcTaskManifest


class FakeCommandRunner:
    def __init__(self):
        self.calls = []
        self.remote_digest = "0" * 64
        self.remote_digests = {}
        self.sbatch_mode = "success"
        self.scheduler_state = "RUNNING"
        self.reconcile_job = None

    def run(self, argv, *, timeout):
        args = list(argv)
        self.calls.append((args, timeout))
        joined = " ".join(args)
        if "--version" in joined:
            return CommandOutput(0, "CP2K version 2025.2 (Development Version)\\n", "")
        if "sbatch --parsable" in joined:
            if self.sbatch_mode == "lost":
                return CommandOutput(255, "", "connection lost after dispatch")
            return CommandOutput(0, "246810\n", "")
        if "squeue" in joined and "%i|%Z" in joined:
            if self.reconcile_job:
                workdir = self.reconcile_job[1]
                return CommandOutput(0, f"{self.reconcile_job[0]}|{workdir}\n", "")
            return CommandOutput(0, "", "")
        if "squeue" in joined and "-o %T" in joined:
            return CommandOutput(0, self.scheduler_state + "\n", "")
        if "sacct" in joined and "WorkDir" in joined:
            return CommandOutput(0, "", "")
        if "sha256sum" in joined:
            return CommandOutput(0, self.remote_digest + "  file\n", "")
        if args and args[0].lower().endswith(("python", "python.exe")) and "show" in args:
            record = {
                "slurm": {"state": "COMPLETED", "exit_code": "0:0"},
                "application": {"normal_termination": None, "observed_marker": None},
            }
            return CommandOutput(0, json.dumps(record), "")
        return CommandOutput(0, "", "")


def make_files(root: Path):
    ssh = root / "ssh.exe"
    scp = root / "scp.exe"
    record = root / "job_record.py"
    config = root / "config_bscc_a"
    for path in (ssh, scp, record, config):
        path.write_text("test-only placeholder", encoding="utf-8")
    return ssh, scp, record, config


def make_manifest(root: Path, remote_workdir=None):
    data = root / "input.inp"
    script = root / "job.slurm"
    data.write_text("&GLOBAL\\n RUN_TYPE ENERGY\\n&END GLOBAL\\n", encoding="utf-8")
    script.write_bytes(data.read_bytes())
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    script_digest = hashlib.sha256(script.read_bytes()).hexdigest()
    payload = {
        "local_files": [{"path": str(data), "name": "input.inp"}, {"path": str(script), "name": "job.slurm"}],
        "output_files": {"cp2k_output": "cp2k.out"},
        "input_filename": "input.inp",
        "job_script_name": "job.slurm",
        "resources": {
            "module": "cp2k/2025.2-openmpi", "nodes": 1, "ntasks": 4,
            "cpus_per_task": 1, "mem": "8G", "time": "00:30:00",
            "partition": "node", "account": "research",
        },
        "python_executable": "python",
    }
    if remote_workdir:
        payload["remote_workdir"] = remote_workdir
    return HpcTaskManifest(
        task_id="TASK-TEST-1",
        input_artifacts=(ArtifactRef("ART-INPUT", sha256=digest, mock=False),),
        payload=payload,
    ), data, digest, script_digest


class ScriptRenderingTests(unittest.TestCase):
    def test_beilong_privacy_header_is_rebased_to_private_runtime_root(self):
        header = """# BSCC-A Slurm privacy header
#SBATCH --job-name=wcl
#SBATCH --output=/site/private/home/wcl/hpc/logs/wcl-%j.out
#SBATCH --error=/site/private/home/wcl/hpc/logs/wcl-%j.err
umask 077
"""
        script = render_beilong_cp2k_script(
            header,
            allowed_workspace_root="/private/configured/wcl",
            remote_workdir="/private/configured/wcl/hpc/jobs/opaque123",
            resources={
                "module": "cp2k/2025.2", "nodes": 1, "ntasks": 8,
                "cpus_per_task": 1, "mem": "32G", "time": "01:00:00",
                "partition": "cpu", "account": "project",
            },
            module_init_path="/site/modules/module.sh",
            input_name="run.inp", output_name="run.out",
        )
        self.assertIn("#SBATCH --job-name=wcl", script)
        self.assertIn("#SBATCH --output=/private/configured/wcl/hpc/logs/wcl-%j.out", script)
        self.assertIn("#SBATCH --error=/private/configured/wcl/hpc/logs/wcl-%j.err", script)
        self.assertIn("umask 077", script)
        self.assertIn("cd \"$SLURM_SUBMIT_DIR\"", script)
        self.assertNotIn("/site/private/home", script)
        with self.assertRaises(Exception):
            render_beilong_cp2k_script(
                header, allowed_workspace_root="/private/configured/wcl",
                remote_workdir="/tmp/escaped",
                resources={"module":"x","nodes":1,"ntasks":1,"cpus_per_task":1,"mem":"1G",
                           "time":"00:10:00","partition":"cpu","account":"p"},
                module_init_path="/site/modules/module.sh", input_name="run.inp", output_name="run.out",
            )

    def test_ucas_template_is_reused_and_only_declared_resources_are_changed(self):
        template = """#!/usr/bin/env bash
#SBATCH --job-name=cp2k
#SBATCH --partition=node
#SBATCH --account=research
#SBATCH --nodes=1
#SBATCH --ntasks=48
#SBATCH --cpus-per-task=1
#SBATCH --mem=120G
#SBATCH --time=24:00:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
source /etc/profile.d/modules.sh
module use /public/env/modules/apps
module use /public/env/modules/tools
module load cp2k/2025.2-openmpi
INPUT="${1:-cp2k.inp}"
OUTPUT="${2:-cp2k.out}"
mpirun -np "${SLURM_NTASKS}" cp2k.psmp -i "$INPUT" -o "$OUTPUT"
"""
        rendered = render_ucas_cp2k_script(
            template,
            resources={"partition":"fat","account":"research","nodes":1,"ntasks":24,
                       "cpus_per_task":2,"mem":"256G","time":"12:00:00",
                       "module":"cp2k/2025.2-openmpi"},
            input_name="task.inp", output_name="task.out",
        )
        for expected in ("--partition=fat", "--ntasks=24", "--cpus-per-task=2",
                         "--mem=256G", "--time=12:00:00", 'INPUT="task.inp"',
                         'OUTPUT="task.out"', "module load cp2k/2025.2-openmpi"):
            self.assertIn(expected, rendered)


class SkillBackendTests(unittest.TestCase):
    def _beilong(self, root, runner):
        ssh, scp, record, config = make_files(root)
        profile = {
            "alias":"bscc-a", "ssh_executable":str(ssh), "scp_executable":str(scp),
            "ssh_config":str(config), "job_record_script":str(record),
            "remote_root":"/configured/wcl", "allowed_workspace_root":"/configured/wcl", "required_cp2k_version":"2025.2",
            "module_init_path":"/site/modules/module.sh",
            "resource_profile":{"module":"cp2k/2025.2","nodes":1,"ntasks":4,
               "cpus_per_task":1,"mem":"8G","time":"00:30:00","partition":"cpu","account":"account"},
        }
        return BeiLongHPCAdapter(profile, local_project_root=root, command_runner=runner)

    def _ucas(self, root, runner):
        ssh, scp, record, config = make_files(root)
        profile = {
            "alias":"hpc", "ssh_executable":str(ssh), "scp_executable":str(scp),
            "job_record_script":str(record), "remote_root":"/gpfs/project", "required_cp2k_version":"2025.2",
            "resource_profile":{"module":"cp2k/2025.2-openmpi","nodes":1,"ntasks":4,
               "cpus_per_task":1,"mem":"8G","time":"00:30:00","partition":"node","account":"research"},
        }
        return UCASHPCAdapter(profile, local_project_root=root, command_runner=runner)

    def test_beilong_uses_dedicated_ssh_config_for_both_ssh_and_scp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._beilong(root,runner)
            manifest,local,digest,script_digest=make_manifest(root)
            runner.remote_digest=digest
            staged=adapter.stage_inputs(manifest)
            self.assertTrue(staged.stage_reference.startswith("/configured/wcl/hpc/jobs/"))
            calls=[call[0] for call in runner.calls]
            self.assertTrue(any(x[0].endswith("ssh.exe") and "-F" in x and str(root/"config_bscc_a") in x for x in calls))
            self.assertTrue(any(x[0].endswith("scp.exe") and "-F" in x and str(root/"config_bscc_a") in x for x in calls))
            for argv in calls:
                if argv[0].endswith(("ssh.exe","scp.exe")):
                    self.assertIn(str(root/"config_bscc_a"),argv)

    def test_ucas_uses_configured_hpc_alias_without_beilong_config_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            manifest,local,digest,script_digest=make_manifest(root); runner.remote_digest=digest
            adapter.stage_inputs(manifest)
            calls=[call[0] for call in runner.calls]
            ssh_calls=[x for x in calls if x[0].endswith("ssh.exe")]
            scp_calls=[x for x in calls if x[0].endswith("scp.exe")]
            self.assertTrue(ssh_calls); self.assertTrue(scp_calls)
            self.assertTrue(all("hpc" in x for x in ssh_calls))
            self.assertTrue(all(any(str(arg).startswith("hpc:") for arg in x) for x in scp_calls))
            self.assertTrue(all("-F" not in x for x in ssh_calls+scp_calls))

    def test_sbatch_job_id_is_persisted_by_callback_before_job_record_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            manifest,local,digest,script_digest=make_manifest(root); runner.remote_digest=digest
            adapter.stage_inputs(manifest)
            order=[]
            job=adapter.submit(
                manifest,
                on_submission_intent=lambda details: order.append(("intent",details["remote_workdir"])),
                on_job_submitted=lambda job_id,details: order.append(("job",job_id)),
            )
            self.assertEqual(job.job_id,"246810")
            self.assertEqual(order[0][0],"intent")
            self.assertEqual(order[1],("job","246810"))
            record_call=next(i for i,x in enumerate(runner.calls) if "job_record.py" in " ".join(x[0]) and "create" in x[0])
            self.assertGreater(record_call,0)

    def test_lost_sbatch_response_is_reconciled_or_marked_unknown_never_resubmitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            manifest,local,digest,script_digest=make_manifest(root); runner.remote_digest=digest
            staged=adapter.stage_inputs(manifest)
            runner.sbatch_mode="lost"
            with self.assertRaises(SubmissionUnknown):
                adapter.submit(manifest)
            sbatch_calls=sum("sbatch --parsable" in " ".join(x[0]) for x in runner.calls)
            self.assertEqual(sbatch_calls,1)

    def test_lost_sbatch_response_can_reconcile_existing_job_by_opaque_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            manifest,local,digest,script_digest=make_manifest(root); runner.remote_digest=digest
            staged=adapter.stage_inputs(manifest)
            runner.sbatch_mode="lost"
            runner.reconcile_job=("13579",staged.stage_reference)
            job=adapter.submit(manifest)
            self.assertEqual(job.job_id,"13579")
            self.assertEqual(sum("sbatch --parsable" in " ".join(x[0]) for x in runner.calls),1)

    def test_read_only_preflight_checks_declared_cp2k_version_without_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            result=adapter.preflight()
            self.assertTrue(result.ready, result.diagnostics)
            self.assertIn("sha256", result.capabilities)
            self.assertFalse(any("sbatch --parsable" in " ".join(args) for args, _ in runner.calls))
            self.assertTrue(any("--version" in " ".join(args) for args, _ in runner.calls))

    def test_read_only_preflight_rejects_cp2k_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            adapter.config["required_cp2k_version"]="2026.1"
            result=adapter.preflight()
            self.assertFalse(result.ready)
            self.assertTrue(result.diagnostics)

    def test_scheduler_status_is_not_scientific_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=FakeCommandRunner(); adapter=self._ucas(root,runner)
            ref=__import__("pipeline_contracts.models",fromlist=["JobReference"]).JobReference("13579","TASK-TEST-1","ucas")
            runner.scheduler_state="COMPLETED"
            status=adapter.get_status(ref)
            self.assertEqual(status.scheduler_state,"COMPLETED")
            self.assertEqual(status.state,HpcState.AWAITING_VALIDATION)
            self.assertFalse(status.hashes_verified)


if __name__ == "__main__":
    unittest.main()
