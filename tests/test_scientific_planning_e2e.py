from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from pipeline_contracts.cli import main as cli_main
from pipeline_contracts.project_pipeline import ProjectPipeline
from pipeline_contracts.scientific_planning.bundle import canonical_sha256
from pipeline_contracts.scientific_planning.contracts import validate_bundle
from pipeline_contracts.scientific_planning.intent_compiler import compile_model_recipe
from pipeline_contracts.scientific_planning.plugin_registry import engine_planning, MODEL_PLUGIN_REGISTRY, run_structure_plugin
from pipeline_contracts.calculation_plan import PlanValidationError


_CURRENT_API = None


class PlanningFakeDataAnalysis:
    """Test double implementing the existing Data_analysis Artifact/Evidence API."""
    def __init__(self):
        self.files = {}
        self.registered = []
        self.analysis_runs = {}
        self.evidence_packages = {}

    def resolve_artifact_path(self, project_root, artifact_id):
        return str(self.files[artifact_id])

    def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids,
                                  format_id, provenance, **metadata):
        path = Path(file_path).resolve(strict=True)
        digest = _sha(path)
        artifact_id = f"planning-artifact-{len(self.registered) + 1}"
        root = Path(project_root).resolve()
        record_path = root / "mock_data_analysis_registry" / f"{artifact_id}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "artifact_id": artifact_id, "sha256": digest, "format_id": format_id,
            "source_artifact_ids": list(source_artifact_ids),
            "source_locator": {"stored_path": path.as_uri()},
            "artifact": {"artifact_id": artifact_id, "sha256": digest, "format_id": format_id},
            "provenance": dict(provenance), "metadata": dict(metadata),
        }
        record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        self.files[artifact_id] = path
        self.registered.append(record)
        return {**record, "record_path": str(record_path)}

    def create_dft_analysis_run_from_project(self, *, project_root, input_artifact_ids,
            output_artifacts, operation_id, operation_version, parameters, software,
            persist, status, structure_artifact_id, structure_sha256, approved_model_sha256,
            upstream_job_reference, parser_id, parser_version, units, assumptions, warnings,
            qc_status, environment):
        run_id = f"planning-analysis-{len(self.analysis_runs) + 1}"
        record = {
            "analysis_run_id": run_id, "input_artifact_ids": list(input_artifact_ids),
            "output_artifact_ids": [item["artifact_id"] for item in output_artifacts],
            "output_hashes": {
                item["artifact_id"]: item["sha256"] for item in output_artifacts
            },
            "operation_id": operation_id, "operation_version": operation_version,
            "parameters": dict(parameters), "software": dict(software), "persist": bool(persist),
            "status": status, "structure_artifact_id": structure_artifact_id,
            "structure_sha256": structure_sha256, "approved_model_sha256": approved_model_sha256,
            "upstream_job_reference": upstream_job_reference, "parser_id": parser_id,
            "parser_version": parser_version, "units": dict(units), "assumptions": list(assumptions),
            "warnings": list(warnings), "qc_status": qc_status, "environment": dict(environment),
        }
        self.analysis_runs[run_id] = record
        root = Path(project_root).resolve()
        record_path = root / "mock_data_analysis_registry" / f"{run_id}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        return {"analysis_run": record, "record_path": str(record_path)}

    def build_evidence_package(self, *, dft_analysis_runs, question):
        evidence_id = f"planning-evidence-{len(self.evidence_packages) + 1}"
        record = {"evidence_package_id": evidence_id,
                  "dft_analysis_runs": list(dft_analysis_runs), "question": question}
        self.evidence_packages[evidence_id] = record
        return record


def build_test_integration(*, project_root, run_root):
    return {"data_analysis_api": _CURRENT_API}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_docx(path: Path):
    text = "research_note: synthetic planning integration fixture"
    import xml.sax.saxutils as saxutils
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>' + saxutils.escape(text) + '</w:t></w:r></w:p>'
        '<w:sectPr/></w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def _write_extxyz(path: Path, *, cell=20.0, pbc="F F F", atoms=None):
    atoms = atoms or [("Cu", (0.0, 0.0, 0.0)), ("O", (2.0, 0.0, 0.0))]
    lines = [
        str(len(atoms)),
        f'Lattice="{cell} 0 0 0 {cell} 0 0 0 {cell}" Properties=species:S:1:pos:R:3 pbc="{pbc}"',
    ]
    lines.extend(f"{symbol} {x} {y} {z}" for symbol, (x, y, z) in atoms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_cli(args, allowed=(0, 2)):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli_main(args)
    if code not in allowed:
        raise AssertionError(f"CLI exited {code}: {output.getvalue()}")
    return json.loads(output.getvalue()), code


def _profile_fields():
    return {
        "xc_functional": "PBE",
        "dispersion": "NONE",
        "basis_set": "DZVP-MOLOPT-SR-GTH",
        "pseudopotential": "GTH-PBE",
        "basis_file_name": "BASIS_MOLOPT",
        "potential_file_name": "GTH_POTENTIALS",
        "kind_definitions": {
            "Cu": {"element": "Cu", "basis_set": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"},
            "O": {"element": "O", "basis_set": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"},
        },
        "cutoff_ry": 400,
        "rel_cutoff_ry": 60,
        "scf": {"method": "OT", "eps_scf": 1e-6, "max_scf": 120},
        "charge": 0,
        "multiplicity": 1,
        "spin": "SINGLET",
        "uks": False,
        "center_coordinates": True,
        "poisson_solver": "MT",
        "poisson_periodicity": "NONE",
        "solvation": {"implicit": "NONE", "explicit": "NONE"},
        "software_version": "2025.2",
        "kpoints": {"value": None, "rationale": "Molecular structure is explicitly non-periodic; k-points do not apply.",
                    "status": "NOT_APPLICABLE"},
        "smearing": {"value": None, "rationale": "Molecular structure is explicitly non-periodic; smearing does not apply.",
                     "status": "NOT_APPLICABLE"},
    }


def _make_profile(path: Path, structure_artifact_id: str, structure_sha: str, *, omit_multiplicity=False):
    fields = _profile_fields()
    if omit_multiplicity:
        fields.pop("multiplicity")
    profile = {
        "scientific_planning": {
            "title": "Synthetic Mock planning E2E",
            "intent": {
                "research_question": "Does the explicit Mock planning chain preserve source and Artifact identity?",
                "research_goal": {
                    "research_object": "A synthetic Cu-O molecular test structure",
                    "comparison": "GEO_OPT geometry followed by single-point ENERGY",
                    "target_conclusion": "Verify provenance and planning integration only",
                },
                "requested_observables": ["optimized_geometry", "single_point_energy"],
                "requested_task_families": ["ELECTRONIC_STRUCTURE"],
                "constraints": [],
            },
            "model": {
                "model_type": "MOLECULE",
                "system_type": "molecule",
                "electronic_state": {"charge": 0, "multiplicity": None if omit_multiplicity else 1,
                                     "spin_label": "SINGLET"},
                "structure_artifact": {
                    "artifact_id": structure_artifact_id,
                    "sha256": structure_sha,
                },
                "target_definition": {
                    "scientific_role": "synthetic integration fixture",
                    "model_origin": "SUPPLIED",
                },
                "topology": {
                    "representation": "explicit_bond_graph",
                    "atoms": [
                        {"atom_id": "Cu1", "element": "Cu"},
                        {"atom_id": "O1", "element": "O"},
                    ],
                    "bonds": [{"atom1": "Cu1", "atom2": "O1", "kind": "coordination"}],
                },
                "validation_contract": {"source": "synthetic test profile"},
            },
            "method": {
                "engine": "cp2k",
                "software_version": "2025.2",
                "runtime_version_verified": False,
                "approved": True,
                "approved_profile_fields": fields,
            },
            "task_type": "cp2k.geo_opt",
            "execution": {
                "backend": "mock",
                "resource_profile": {
                    "profile_id": "synthetic-mock-resource-profile-v1",
                    "verified": True,
                    "source_ref": "approved-resource-profile",
                    "engine": "cp2k",
                    "task_type": "cp2k.geo_opt",
                    "uncertainty": "TEST_ONLY_NOT_A_PERFORMANCE_PREDICTION",
                    "allocation": {
                        "nodes": 1, "cpu_cores": 1, "mpi_ranks": 1, "openmp_threads": 1,
                        "gpu_count": 0, "memory_gb": 2, "walltime_seconds": 300, "scratch_gb": 1,
                    },
                },
            },
            "runtime": {
                "calculations": [
                    {"id": "relax", "operation": "cp2k.geo_opt", "tool_version": "2025.2",
                     "output_files": {"cp2k_output": "geo_opt.out",
                                      "optimized_structure": "optimized.extxyz"}},
                    {"id": "energy", "operation": "cp2k.energy", "tool_version": "2025.2",
                     "depends_on": ["relax"],
                     "output_files": {"cp2k_output": "energy.out"}},
                ],
                "analysis": {"operation": "dft.artifact.read", "reader_id": "synthetic-mock-reader"},
                "retry_policy": {"infrastructure_retries": 0},
            },
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path

def _setup_project(tmp_path: Path, *, omit_multiplicity=False):
    global _CURRENT_API
    api = PlanningFakeDataAnalysis()
    root = tmp_path
    structure_path = _write_extxyz(root / "data" / "input_structure.extxyz")
    artifact_id = "registered-structure-001"
    api.files[artifact_id] = structure_path.resolve()
    profile_path = root / "project_profile.json"
    _make_profile(profile_path, artifact_id, _sha(structure_path), omit_multiplicity=omit_multiplicity)

    state_db = root / "state.sqlite"
    output_root = root / "project_runs"
    source_docx = _write_docx(root / "planning-e2e.docx")
    started, _ = _run_cli([
        "project", "start", str(source_docx), "--project-id", "synthetic-planning-e2e",
        "--compiler", "generic", "--state-db", str(state_db), "--output-root", str(output_root),
    ])
    run_id = started["project_run_id"]
    reviewed, _ = _run_cli([
        "project", "review", run_id, "--state-db", str(state_db), "--output-root", str(output_root),
    ])
    evidence_ids = [item["evidence_id"] for item in reviewed["evidence"]]
    _run_cli([
        "project", "confirm", run_id, "--state-db", str(state_db), "--output-root", str(output_root),
        *sum((["--evidence-id", item] for item in evidence_ids), []),
        "--confirmed-by", "synthetic-test-owner", "--rationale", "Confirm test-only source note",
        "--changes", json.dumps({"decision": "confirm synthetic fixture source only"}),
    ])
    _CURRENT_API = api
    return api, state_db, output_root, run_id, profile_path, root / "data"


class ScientificPlanningE2ETests(unittest.TestCase):
    def test_e2e_1_plan_approve_and_run_existing_mock_geo_opt_qc_energy_analysis_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, state_db, output_root, run_id, profile_path, data_root = _setup_project(root)
            try:
                factory = f"{__name__}:build_test_integration"
                planned, code = _run_cli([
                    "project", "plan", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root), "--project-profile", str(profile_path),
                    "--integration-factory", factory, "--data-analysis-project-root", str(data_root),
                ])
                self.assertEqual(code, 0)
                self.assertEqual(planned["planning_status"], "READY")
                self.assertFalse(planned["calculation_plan_created"])
                self.assertFalse(planned["workflow_created"])
                bundle_path = Path(planned["files"]["planning_bundle.json"])
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                validate_bundle(bundle)
                example_target = os.environ.get("PLANNING_BUNDLE_EXAMPLE_PATH")
                if example_target:
                    example_path = Path(example_target)
                    example_path.parent.mkdir(parents=True, exist_ok=True)
                    example_path.write_text(
                        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                artifact_ref = bundle["model_recipes"][0]["input_artifact_refs"][0]
                self.assertEqual(artifact_ref["object_id"], "registered-structure-001")
                self.assertEqual(artifact_ref["sha256"], _sha(data_root / "input_structure.extxyz"))
                self.assertEqual(bundle["execution_plan"]["backend"]["backend_id"], "mock")
                resource_profile = bundle["execution_plan"]["resource_profile"]
                self.assertEqual(resource_profile["status"], "MOCK_ONLY")
                self.assertFalse(resource_profile["verified_profile"])
                self.assertFalse(resource_profile["real_execution_preflight_allowed"])
                for field in (
                    "nodes", "cpu_cores", "mpi_ranks", "openmp_threads", "gpu_count",
                    "gpu_model", "memory_bytes", "walltime_seconds", "scratch_bytes",
                ):
                    self.assertEqual(resource_profile["values"][field]["status"], "NOT_APPLICABLE")
                    self.assertIsNone(resource_profile["values"][field]["value"])
                self.assertEqual(bundle["method_plan"]["execution_mode"], "mock")
                self.assertFalse(bundle["method_plan"]["runtime_version_verified"])
                self.assertFalse(bundle["method_plan"]["real_execution_preflight_allowed"])
                method_fields = bundle["method_plan"]["agent_a_field_records"]
                required_source_fields = (
                    "xc_functional", "basis_set", "pseudopotential", "basis_file_name",
                    "potential_file_name", "kind_definitions", "cutoff_ry", "rel_cutoff_ry",
                    "scf.method", "scf.eps_scf", "scf.max_scf", "charge", "multiplicity",
                    "uks", "poisson_solver", "cell_periodicity", "poisson_periodicity",
                    "center_coordinates", "software_version",
                )
                for field_name in required_source_fields:
                    self.assertIn(field_name, method_fields)
                    record = method_fields[field_name]
                    for key in ("value", "provenance", "source_ref", "rationale",
                                "applicability", "uncertainty", "approval_required", "status"):
                        self.assertIn(key, record)
                    self.assertTrue(record["source_ref"])
                self.assertEqual(method_fields["cell_periodicity"]["source_ref"],
                                 "artifact-" + artifact_ref["sha256"][:16])
                self.assertEqual(method_fields["poisson_periodicity"]["value"], "NONE")

                repeated, repeated_code = _run_cli([
                    "project", "plan", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root), "--project-profile", str(profile_path),
                    "--integration-factory", factory, "--data-analysis-project-root", str(data_root),
                ])
                self.assertEqual(repeated_code, 0)
                self.assertTrue(repeated["idempotent_reuse"])
                self.assertEqual(repeated["bundle_sha256"], planned["bundle_sha256"])

                # A newly supplied independent runtime observation changes the
                # frozen Planning input fingerprint and cannot reuse the old Bundle.
                fingerprint_guard = ProjectPipeline(state_db, output_root)
                try:
                    with self.assertRaisesRegex(FileExistsError, "planning input changed"):
                        fingerprint_guard.plan_scientific(
                            run_id, profile_path=profile_path, data_analysis_api=api,
                            data_analysis_project_root=data_root,
                            runtime_verified_version="2025.2",
                        )
                finally:
                    fingerprint_guard.close()

                original_profile_text = profile_path.read_text(encoding="utf-8")
                changed_profile = json.loads(original_profile_text)
                changed_profile["scientific_planning"]["title"] += " source-changed"
                profile_path.write_text(
                    json.dumps(changed_profile, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                guard = ProjectPipeline(state_db, output_root)
                try:
                    with self.assertRaisesRegex(FileExistsError, "changed after"):
                        guard.plan_scientific(
                            run_id, profile_path=profile_path, data_analysis_api=api,
                            data_analysis_project_root=data_root,
                        )
                    unchanged_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        unchanged_bundle["planning_metadata"]["object_sha256"],
                        planned["bundle_sha256"],
                    )
                finally:
                    guard.close()
                    profile_path.write_text(original_profile_text, encoding="utf-8")

                candidate_id = planned["candidate_id"]
                approved, _ = _run_cli([
                    "project", "approve", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root), "--candidate-id", candidate_id,
                    "--approver", "synthetic-test-owner", "--approve",
                ])
                self.assertEqual(approved["approval_status"], "APPROVED")
                self.assertEqual(approved["artifact_id"], "registered-structure-001")

                completed, _ = _run_cli([
                    "project", "resume", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root), "--mode", "mock",
                    "--integration-factory", factory,
                ])
                self.assertEqual(completed["status"], "COMPLETED")
                self.assertEqual([item["status"] for item in completed["stages"]], ["COMPLETED"] * 11)
                report, _ = _run_cli([
                    "project", "report", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root),
                ])
                self.assertEqual(report["project_status"], "COMPLETED")
                self.assertEqual(
                    [item["operation"] for item in report["workflow"]["tasks"]],
                    ["cp2k.geo_opt", "cp2k.energy"],
                )
                geo_payload = json.loads(report["workflow"]["tasks"][0]["result_json"])
                self.assertEqual(geo_payload["qc"]["qc_evidence_mode"],
                                 "MOCK_ADAPTER_SYNTHETIC_EVIDENCE_NOT_SCIENTIFIC_VALIDATION")
                self.assertIn("agent_a_qc", geo_payload["qc"])
                energy_payload = json.loads(report["workflow"]["tasks"][1]["result_json"])
                self.assertTrue(energy_payload["analysis_run_id"])
                self.assertTrue(energy_payload["evidence_package_id"])
                self.assertEqual(report["scientific_planning_bundle"]["planning_metadata"]["object_sha256"],
                                 planned["bundle_sha256"])
                calculation_plan = json.loads((output_root / run_id / "calculation_plan.json").read_text(encoding="utf-8"))
                self.assertEqual(calculation_plan["structure"]["artifact_id"], "registered-structure-001")
                self.assertEqual(calculation_plan["structure"]["sha256"], _sha(data_root / "input_structure.extxyz"))
                self.assertEqual(calculation_plan["execution"]["backend"], "mock")
                self.assertIn("method_parameter_provenance", calculation_plan["metadata"])
                from pipeline_contracts.calculation_plan import CalculationPlan
                runtime_plan_sha = CalculationPlan.from_mapping(calculation_plan).sha256
                frozen_plan = report["scientific_calculation_plan"]
                self.assertEqual(frozen_plan["runtime_projection"]["payload_sha256"], runtime_plan_sha)
                self.assertEqual(frozen_plan["sha256"], frozen_plan["planning_metadata"]["object_sha256"])
                self.assertEqual(calculation_plan["metadata"]["execution_mode"], "mock")
                self.assertEqual(calculation_plan["metadata"]["planning_scope"], "MOCK_ONLY")
                self.assertFalse(calculation_plan["metadata"]["real_execution_preflight_allowed"])
                mock_resources = calculation_plan["execution"]["resources"]
                self.assertEqual(mock_resources["planning_scope"], "MOCK_ONLY")
                self.assertTrue(mock_resources["mock_only"])
                self.assertFalse(mock_resources["real_execution_preflight_allowed"])
                self.assertIsNone(mock_resources["allocation"])
                self.assertFalse(mock_resources["resource_estimate_available"])
                self.assertEqual(frozen_plan["approval_refs"][0]["object_id"], approved["candidate_id"])
                self.assertEqual(len(api.analysis_runs), 1)
                self.assertEqual(len(api.evidence_packages), 1)
                self.assertTrue(api.registered)

                # Export a complete, immutable synthetic E2E example only after
                # approval, CalculationPlan freeze, Mock execution and final report.
                # The original pre-approval PlanningBundle is copied unchanged.
                if example_target:
                    example_root = Path(example_target).parent
                    example_root.mkdir(parents=True, exist_ok=True)
                    object_root = example_root / "planning_objects"
                    object_root.mkdir(parents=True, exist_ok=True)
                    for object_name, object_path in planned["files"].items():
                        source_path = Path(object_path)
                        self.assertTrue(source_path.is_file(), object_path)
                        shutil.copy2(source_path, object_root / source_path.name)

                    approval_path = output_root / run_id / "approval" / "approval_record.json"
                    final_plan_path = output_root / run_id / "calculation_plan.json"
                    self.assertTrue(approval_path.is_file())
                    self.assertTrue(final_plan_path.is_file())
                    example_documents = {
                        "approval_record.json": json.loads(approval_path.read_text(encoding="utf-8")),
                        "scientific_calculation_plan.json": frozen_plan,
                        "calculation_plan.json": calculation_plan,
                        "mock_resume_result.json": completed,
                        "final_report.json": report,
                    }
                    for name, document in example_documents.items():
                        (example_root / name).write_text(
                            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    example_manifest = {
                        "example_type": "SYNTHETIC_E2E_FULL_MOCK_CLOSED_LOOP",
                        "project_run_id": run_id,
                        "bundle_id": bundle["bundle_id"],
                        "planning_bundle_sha256": planned["bundle_sha256"],
                        "calculation_plan_id": calculation_plan["plan_id"],
                        "calculation_plan_sha256": runtime_plan_sha,
                        "frozen_calculation_plan_sha256": frozen_plan["sha256"],
                        "model_approval_candidate_id": approved["candidate_id"],
                        "approved_structure_artifact_id": approved["artifact_id"],
                        "approved_structure_sha256": approved["structure_sha256"],
                        "workflow_run_id": completed.get("workflow_run_id"),
                        "workflow_operations": [item["operation"] for item in report["workflow"]["tasks"]],
                        "project_status": report["project_status"],
                        "execution_mode": "mock",
                        "qc_evidence_mode": geo_payload["qc"]["qc_evidence_mode"],
                        "analysis_run_id": energy_payload["analysis_run_id"],
                        "evidence_package_id": energy_payload["evidence_package_id"],
                    }
                    (example_root / "example_manifest.json").write_text(
                        json.dumps(example_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
            finally:
                _CURRENT_API = None

    def test_e2e_2_missing_electronic_state_blocks_without_calculation_plan_or_workflow_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, state_db, output_root, run_id, profile_path, data_root = _setup_project(
                root, omit_multiplicity=True
            )
            try:
                pipeline = ProjectPipeline(state_db, output_root)
                try:
                    planned = pipeline.plan_scientific(
                        run_id, profile_path=profile_path, data_analysis_api=api,
                        data_analysis_project_root=data_root,
                    )
                    self.assertEqual(planned["planning_status"], "BLOCKED")
                    multiplicity_gap = next(
                        item for item in planned["missing_items"]
                        if item["field_path"] == "model_recipe.electronic_state.multiplicity"
                    )
                    self.assertTrue(multiplicity_gap["related_evidence_refs"])
                    self.assertTrue(any(
                        ref["locator"]["kind"] in {"paragraph", "table"}
                        and "word/document.xml#" in ref["locator"]["value"]
                        for ref in multiplicity_gap["related_evidence_refs"]
                    ))
                    run_count = pipeline.store._db.execute(
                        "SELECT COUNT(*) AS n FROM workflow_runs"
                    ).fetchone()["n"]
                    self.assertEqual(run_count, 0)
                    self.assertEqual(
                        pipeline.lifecycle.stage(run_id, "MODEL_GENERATE")["status"], "BLOCKED"
                    )
                    run_root = pipeline._run_root(run_id)
                    self.assertFalse((run_root / "calculation_plan.json").exists())
                    self.assertFalse((run_root / "model_spec_bundle.json").exists())
                    self.assertFalse((run_root / "model_pipeline_result.json").exists())
                    self.assertFalse(pipeline.lifecycle.stage(run_id, "CALCULATION_PLAN")["outputs"])
                finally:
                    pipeline.close()
            finally:
                _CURRENT_API = None

    def test_e2e_3_real_packmol_and_ase_idpp_preserve_states_and_artifact_sha(self):
        if shutil.which("packmol") is None:
            self.fail("Packmol must be installed in the contract-test runner; this E2E is not a mock")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            solute = _write_extxyz(root / "solute.extxyz", atoms=[("Cu", (6.0, 6.0, 6.0))])
            solvent = _write_extxyz(root / "water.extxyz", cell=5.0,
                                    atoms=[("O", (0.0, 0.0, 0.0)), ("H", (0.96, 0.0, 0.0)),
                                           ("H", (-0.24, 0.93, 0.0))])
            solute_spec = {"path": str(solute), "sha256": _sha(solute),
                           "artifact_id": "registered-solute-001", "artifact_sha256": _sha(solute)}
            solvent_spec = {"path": str(solvent), "sha256": _sha(solvent),
                            "artifact_id": "registered-water-001", "artifact_sha256": _sha(solvent)}
            invalid_dir = root / "invalid-packmol-output"
            invalid = MODEL_PLUGIN_REGISTRY.invoke("build_explicit_solvent_box", {"recipe": {"solvents": []}},
                                           invalid_dir)
            self.assertEqual(invalid["status"], "NEEDS_DECISION")
            self.assertFalse(invalid_dir.exists())

            packed_dir = root / "packmol-output"
            packed = run_structure_plugin("build_explicit_solvent_box", {
                "recipe": {
                    "solute": solute_spec,
                    "solvents": [{"id": "water", **solvent_spec, "count": 2}],
                    "box": {"bounds_angstrom": [[0, 0, 0], [12, 12, 12]],
                            "pbc": [False, False, False]},
                    "distance_tolerance_angstrom": 2.0, "random_seed": 20261128,
                    "output_format": "extxyz",
                    "validation": {"minimum_inter_molecular_distance_angstrom": 1.0},
                    "timeout_seconds": 120,
                }
            }, packed_dir)
            self.assertEqual(packed["status"], "VALIDATED_INITIAL_STRUCTURE")
            self.assertEqual(packed["equilibration_status"], "PACKED_NOT_EQUILIBRATED")
            packed_artifact = next(item for item in packed["artifacts"]
                                   if item["path"].endswith("structure.extxyz"))
            packed_path = packed_dir / packed_artifact["path"]
            packed_sha = _sha(packed_path)
            self.assertEqual(packed_artifact["sha256"], packed_sha)

            api = PlanningFakeDataAnalysis()
            registered = api.register_derived_artifact(
                str(root), packed_path, source_artifact_ids=["registered-solute-001", "registered-water-001"],
                format_id="extxyz", provenance={"plugin": "explicit_solvent_packmol",
                                                "equilibration_status": "PACKED_NOT_EQUILIBRATED"},
            )
            loaded = run_structure_plugin("load_structure_model", {"source": {
                "path": str(packed_path), "sha256": packed_sha,
                "artifact_id": registered["artifact_id"], "artifact_sha256": packed_sha,
            }})
            recipe, gaps = compile_model_recipe({
                "model": {
                    "model_type": "EXPLICIT_SOLVENT",
                    "electronic_state": {"charge": 0, "multiplicity": 1, "spin_label": "SINGLET"},
                    "target_definition": {"scientific_role": "explicit solvent preparation fixture",
                                          "model_origin": "GENERATED"},
                    "structure_artifact": {"artifact_id": registered["artifact_id"], "sha256": packed_sha},
                    "topology": {"representation": "explicit_molecule_instances",
                                 "molecule_id_array": "molecule_id",
                                 "molecule_type_array": "molecule_type"},
                    "validation_contract": {"equilibration_status": "PACKED_NOT_EQUILIBRATED"},
                },
                "structure_plugin": {"operation": "build_explicit_solvent_box"},
            }, loaded, [{
                "evidence_id": "artifact-" + packed_sha[:16], "source_type": "artifact",
                "source_sha256": packed_sha, "locator": {"kind": "file", "value": "packed"},
            }], {}, plugin_result=packed)
            self.assertFalse(gaps)
            self.assertEqual(recipe["input_artifact_refs"][0]["object_id"], registered["artifact_id"])
            self.assertEqual(recipe["input_artifact_refs"][0]["sha256"], packed_sha)
            self.assertEqual(recipe["validation_contract"]["equilibration_status"],
                             "PACKED_NOT_EQUILIBRATED")
            self.assertEqual(recipe["plugin_id"], packed["plugin"])
            self.assertEqual(
                recipe["plugin_version"], packed["packmol"]["version"]["version"]
            )
            self.assertEqual(
                recipe["validation_contract"]["structure_plugin"]["plugin_provenance"]["packmol_version"],
                packed["provenance"]["packmol_version"],
            )
            self.assertEqual(recipe["input_artifact_refs"][0]["sha256"], packed_sha)
            self.assertEqual(len(recipe["source_artifact_refs"]), 2)
            self.assertEqual(
                {item["object_id"] for item in recipe["source_artifact_refs"]},
                {"registered-solute-001", "registered-water-001"},
            )
            self.assertEqual(
                recipe["construction_steps"][0]["parameters"]["plugin_execution"]["output_artifacts"],
                packed["artifacts"],
            )
            self.assertNotEqual(recipe["status"], "APPROVED")

            initial = _write_extxyz(root / "initial.extxyz", cell=10.0,
                                    atoms=[("H", (1.0, 1.0, 1.0)), ("H", (2.0, 1.0, 1.0))])
            final = _write_extxyz(root / "final.extxyz", cell=10.0,
                                  atoms=[("H", (1.0, 1.0, 1.0)), ("H", (2.0, 2.0, 1.0))])
            neb_invalid_dir = root / "invalid-neb-output"
            neb_invalid = run_structure_plugin("build_neb_initial_path", {
                "initial_structure": {"path": str(initial), "sha256": _sha(initial)},
                "final_structure": {"path": str(final), "sha256": _sha(final)},
                "recipe": {},
            }, neb_invalid_dir)
            self.assertEqual(neb_invalid["status"], "NEEDS_DECISION")
            self.assertFalse(neb_invalid_dir.exists())

            neb_dir = root / "neb-output"
            neb = run_structure_plugin("build_neb_initial_path", {
                "initial_structure": {"path": str(initial), "sha256": _sha(initial),
                                      "artifact_id": "registered-neb-initial",
                                      "artifact_sha256": _sha(initial)},
                "final_structure": {"path": str(final), "sha256": _sha(final),
                                    "artifact_id": "registered-neb-final",
                                    "artifact_sha256": _sha(final)},
                "recipe": {
                    "atom_mapping_initial_to_final": [0, 1], "number_of_images": 3,
                    "endpoint_context": {
                        "initial": {"charge": 0, "spin_multiplicity": 1, "method_fingerprint": {
                            "engine": "synthetic-no-calculator",
                            "xc": "PBE", "basis": "TEST_ONLY", "fingerprint_version": 1,
                        }, "constraints": []},
                        "final": {"charge": 0, "spin_multiplicity": 1, "method_fingerprint": {
                            "engine": "synthetic-no-calculator",
                            "xc": "PBE", "basis": "TEST_ONLY", "fingerprint_version": 1,
                        }, "constraints": []},
                    },
                    "idpp": {"steps": 5, "fmax_angstrom_per_step": 0.1, "mic": False},
                    "validation": {"minimum_pair_distance_angstrom": 0.5},
                },
            }, neb_dir)
            self.assertEqual(neb["status"], "INITIAL_PATH_READY_FOR_REVIEW", neb)
            path_artifact = next(item for item in neb["artifacts"]
                                 if item["path"].endswith("initial_path.extxyz"))
            path_file = neb_dir / path_artifact["path"]
            path_sha = _sha(path_file)
            self.assertEqual(path_artifact["sha256"], path_sha)
            path_registered = api.register_derived_artifact(
                str(root), path_file, source_artifact_ids=["registered-neb-initial", "registered-neb-final"],
                format_id="extxyz", provenance={"plugin": "ase_idpp",
                                                "status": "INITIAL_PATH_READY_FOR_REVIEW"},
            )
            path_mapping = run_structure_plugin("load_structure_model", {"source": {
                "path": str(path_file), "sha256": path_sha,
                "artifact_id": path_registered["artifact_id"], "artifact_sha256": path_sha,
            }})
            path_recipe, path_gaps = compile_model_recipe({
                "model": {
                    "model_type": "TRANSITION_STATE_PATH",
                    "electronic_state": {"charge": 0, "multiplicity": 1, "spin_label": "SINGLET"},
                    "target_definition": {"scientific_role": "initial path generation fixture",
                                          "model_origin": "GENERATED"},
                    "structure_artifact": {"artifact_id": path_registered["artifact_id"], "sha256": path_sha},
                    "topology": {"representation": "explicit_atom_mapping",
                                 "mapping": [0, 1]},
                    "validation_contract": {"plugin_status": "INITIAL_PATH_READY_FOR_REVIEW"},
                },
                "structure_plugin": {"operation": "build_neb_initial_path"},
            }, path_mapping, [{
                "evidence_id": "artifact-" + path_sha[:16], "source_type": "artifact",
                "source_sha256": path_sha, "locator": {"kind": "file", "value": "initial-path"},
            }], {}, plugin_result=neb)
            self.assertFalse(path_gaps)
            self.assertEqual(path_recipe["input_artifact_refs"][0]["object_id"],
                             path_registered["artifact_id"])
            self.assertEqual(path_recipe["input_artifact_refs"][0]["sha256"], path_sha)
            self.assertEqual(
                {item["object_id"] for item in path_recipe["source_artifact_refs"]},
                {"registered-neb-initial", "registered-neb-final"},
            )
            self.assertEqual(path_recipe["plugin_id"], neb["plugin"])
            self.assertEqual(path_recipe["plugin_version"], neb["interpolation"]["ase_version"])
            self.assertEqual(path_recipe["validation_contract"]["structure_plugin"]["status"],
                             "INITIAL_PATH_READY_FOR_REVIEW")
            self.assertNotEqual(path_recipe["status"], "APPROVED")

            neb_route = engine_planning({
                "engine": "cp2k", "task_type": "cp2k.neb",
                "software_version": "2025.2", "runtime_version_verified": False,
            })["capability_route"]
            self.assertEqual(neb_route["integration_status"], "PLANNABLE_ONLY")
            self.assertFalse(neb_route["can_enter_real_preflight"])
            self.assertFalse((root / "workflow_runs").exists())


    def test_e2e_4_unregistered_backend_blocks_schema_valid_bundle_without_runtime(self):
        global _CURRENT_API
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, state_db, output_root, run_id, profile_path, data_root = _setup_project(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["scientific_planning"]["execution"]["backend"] = "orca"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            try:
                factory = f"{__name__}:build_test_integration"
                planned, _ = _run_cli([
                    "project", "plan", run_id, "--state-db", str(state_db),
                    "--output-root", str(output_root), "--project-profile", str(profile_path),
                    "--integration-factory", factory,
                    "--data-analysis-project-root", str(data_root),
                ])
                self.assertEqual(planned["planning_status"], "BLOCKED")
                self.assertFalse(planned["workflow_created"])
                self.assertFalse(planned["calculation_plan_created"])
                self.assertIsNone(planned["candidate_id"])
                self.assertTrue(any(
                    item.get("code") == "EXECUTION_BACKEND_UNREGISTERED"
                    for item in planned["missing_items"]
                ))

                bundle = json.loads(
                    Path(planned["files"]["planning_bundle.json"]).read_text(encoding="utf-8")
                )
                method_plan = bundle["method_plan"]
                execution_plan = bundle["execution_plan"]
                self.assertEqual(bundle["planning_metadata"]["planning_status"], "BLOCKED")
                self.assertIsNone(execution_plan["backend"])
                self.assertEqual(execution_plan["planning_metadata"]["planning_status"], "BLOCKED")
                self.assertNotIn("execution_mode", method_plan)
                self.assertNotIn("planning_scope", method_plan)
                self.assertNotIn("execution_mode", execution_plan)
                self.assertNotIn("planning_scope", execution_plan)
                self.assertFalse(method_plan["real_execution_preflight_allowed"])
                self.assertFalse(execution_plan["real_execution_preflight_allowed"])
                self.assertFalse((root / "workflow_runs").exists())
            finally:
                _CURRENT_API = None


    def test_e2e_5_real_preflight_requires_source_backed_software_version(self):
        global _CURRENT_API
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api, state_db, output_root, run_id, profile_path, data_root = _setup_project(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            method = profile["scientific_planning"]["method"]
            method["approved"] = False
            method.pop("approved_profile_fields", None)
            profile["scientific_planning"]["execution"]["backend"] = "cp2k"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            pipeline = ProjectPipeline(state_db, output_root)
            try:
                planned = pipeline.plan_scientific(
                    run_id, profile_path=profile_path, data_analysis_api=api,
                    data_analysis_project_root=data_root,
                    runtime_verified_version="2025.2",
                )
                bundle = json.loads(
                    Path(planned["files"]["planning_bundle.json"]).read_text(encoding="utf-8")
                )
                method_plan = bundle["method_plan"]
                execution_plan = bundle["execution_plan"]
                route = method_plan["parameters"]["software_compatibility"]["value"]

                # The declared version and observed runtime string match, but the
                # declared version has no resolved source ref: the gate must remain closed.
                self.assertEqual(method_plan["agent_a_field_records"]["software_version"]["status"], "MISSING")
                self.assertFalse(route["software_version_source_backed"])
                self.assertFalse(route["can_enter_real_preflight"])
                self.assertFalse(method_plan["real_execution_preflight_allowed"])
                self.assertFalse(execution_plan["real_execution_preflight_allowed"])
                self.assertEqual(bundle["planning_metadata"]["planning_status"], "BLOCKED")
                self.assertFalse(planned["workflow_created"])
                self.assertFalse(planned["calculation_plan_created"])
            finally:
                pipeline.close()
                _CURRENT_API = None


if __name__ == "__main__":
    unittest.main()
