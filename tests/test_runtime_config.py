from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_contracts.runtime_config import load_runtime_config, validate_runtime_for_backend, RuntimeConfigError


class RuntimeConfigTests(unittest.TestCase):
    def test_local_asset_and_skill_paths_resolve_relative_to_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "UCAS_hpc"
            skill_file = skill / ".agents" / "skills" / "hpc-remote-workflow" / "scripts" / "hpc_job_record.py"
            template = skill / ".agents" / "skills" / "hpc-remote-workflow" / "templates" / "slurm" / "cp2k.slurm"
            for path in (skill_file, template):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# test only\n", encoding="utf-8")
            basis = root / "basis" / "BASIS_MOLOPT"
            potential = root / "basis" / "GTH_POTENTIALS"
            basis.parent.mkdir()
            basis.write_text("basis", encoding="utf-8")
            potential.write_text("potential", encoding="utf-8")
            ssh = root / "ssh.exe"
            scp = root / "scp.exe"
            ssh.write_text("", encoding="utf-8")
            scp.write_text("", encoding="utf-8")
            config = root / ".pipeline" / "runtime.local.json"
            config.parent.mkdir()
            config.write_text(json.dumps({
                "schema_version": "1.0",
                "active_project_root": "../active",
                "python_executable": "",
                "data_analysis": {"source_root": "", "project_root": ".."},
                "chem_scitoolkit": {"source_root": ""},
                "hpc_backends": {
                    "beilong": {"module_init_path": "/cluster/modules/module.sh"},
                    "ucas": {
                        "enabled": True, "alias": "hpc", "ssh_executable": "../ssh.exe",
                        "scp_executable": "../scp.exe", "skill_root": "../UCAS_hpc",
                        "job_record_script": "../UCAS_hpc/" + skill_file.relative_to(skill).as_posix(),
                        "slurm_template": "../UCAS_hpc/" + template.relative_to(skill).as_posix(),
                        "remote_root": "/remote/project", "account": "research",
                    }
                },
                "resource_profiles": {
                    "ucas-cpu": {"nodes": 1, "ntasks": 4, "cpus_per_task": 1, "mem": "8G",
                                 "time": "1:00:00", "partition": "node", "account": "research",
                                 "module": "cp2k/2025.2-openmpi"}
                },
                "input_files": {"basis": "../basis/BASIS_MOLOPT", "potential": "../basis/GTH_POTENTIALS"},
            }), encoding="utf-8")
            payload = load_runtime_config(config)
            self.assertEqual(Path(payload["input_files"]["basis"]), basis.resolve())
            self.assertEqual(Path(payload["input_files"]["potential"]), potential.resolve())
            self.assertEqual(Path(payload["hpc_backends"]["ucas"]["skill_root"]), skill.resolve())
            self.assertEqual(payload["hpc_backends"]["beilong"]["module_init_path"], "/cluster/modules/module.sh")
            backend, resources = validate_runtime_for_backend(payload, "ucas", "ucas-cpu")
            self.assertEqual(resources["account"], "research")
            self.assertEqual(Path(backend["job_record_script"]), skill_file.resolve())

    def test_runtime_config_rejects_skill_script_outside_configured_skill_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            skill.mkdir()
            outside = root / "outside.py"
            outside.write_text("", encoding="utf-8")
            with self.assertRaises(RuntimeConfigError):
                validate_runtime_for_backend({
                    "hpc_backends": {"ucas": {
                        "enabled": True, "alias": "hpc", "ssh_executable": "ssh",
                        "scp_executable": "scp", "remote_root": "/remote",
                        "skill_root": str(skill), "job_record_script": str(outside),
                        "slurm_template": str(outside), "account": "research",
                    }},
                    "resource_profiles": {"test": {
                        "nodes": 1, "ntasks": 1, "cpus_per_task": 1, "mem": "1G",
                        "time": "1:00:00", "partition": "node", "account": "research",
                        "module": "cp2k/2025.2",
                    }},
                }, "ucas", "test")


if __name__ == "__main__":
    unittest.main()
