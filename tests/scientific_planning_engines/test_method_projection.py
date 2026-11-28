from pipeline_contracts.scientific_planning.engines import (
    plan_method, to_cp2k_calculation_plan_method,
)


def _complete_fields():
    return {
        "xc_functional": "PBE",
        "software_version": {
            "value": "2025.2",
            "rationale": "Version recorded in the cited software manifest.",
        },
        "dispersion": "D3(BJ)",
        "basis_set": "DZVP-MOLOPT-SR-GTH",
        "pseudopotential": "GTH-PBE",
        "basis_file_name": "BASIS_MOLOPT",
        "potential_file_name": "GTH_POTENTIALS",
        "kind_definitions": {
            "H": {"element": "H", "basis_set": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"}
        },
        "cutoff_ry": 600,
        "rel_cutoff_ry": 60,
        "scf": {"method": "OT", "eps_scf": 1e-6, "max_scf": 100},
        "charge": 0,
        "multiplicity": 1,
        "spin": "closed_shell",
        "uks": False,
        "center_coordinates": True,
        "periodicity": "NONE",
        "poisson_periodicity": "NONE",
        "poisson_solver": "MT",
        "solvation": {
            "implicit": {
                "status": "NOT_APPLICABLE", "value": None,
                "rationale": "Gas-phase model explicitly selected.",
                "source_ref": "owner:solvation-none",
            },
            "explicit": {
                "status": "NOT_APPLICABLE", "value": None,
                "rationale": "No explicit solvent is part of the model.",
                "source_ref": "owner:explicit-solvent-none",
            },
        },
    }


def _context():
    return {
        "schema_version": "1.0",
        "plan_id": "projection-test",
        "title": "CP2K projection test",
        "scientific_question": "Validate the source-backed method projection.",
        "project_root": "./projection-test",
        "structure": {
            "path": "./structure.xyz",
            "format": "xyz",
            "cell": {"a": 18.0, "b": 18.0, "c": 18.0,
                     "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        },
        "calculations": [{
            "id": "relax", "operation": "cp2k.geo_opt", "tool_version": "2025.2",
            "output_files": {"cp2k_output": "cp2k.out",
                             "optimized_structure": "optimized_structure.xyz"},
        }],
        "execution": {"backend": "ucas", "resources": {"profile": "owner-site-profile"}},
        "analysis": {"operation": "dft.artifact.read"},
        "quality_gates": {"geo_opt_converged": {"required": True}},
        "retry_policy": {"infrastructure_retries": 0},
        "metadata": {},
    }


def _planned(
    fields=None, *, runtime_version_verified=True, include_context=True,
    execution_mode="real", runtime_verified_version="2025.2",
):
    source_fields = _complete_fields() if fields is None else fields
    return plan_method({
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "execution_mode": execution_mode,
        "software_version": "2025.2",
        "runtime_version_verified": runtime_version_verified,
        "runtime_verified_version": runtime_verified_version,
        "structure": {"atom_count": 2, "system_type": "molecule",
                      "periodicity": source_fields.get("periodicity")},
        "sources": [{
            "source_kind": "frozen_source",
            "source_ref": "frozen-docx:sha256:source/page-4/table-1",
            "fields": source_fields,
        }],
        "calculation_plan_context": _context() if include_context else None,
    })


def test_all_method_fields_present_but_runtime_version_unverified_is_not_resolved():
    result = _planned(runtime_version_verified=False)

    assert result["missing_fields"] == []
    assert result["conflicting_fields"] == []
    assert result["proposed_fields"] == []
    assert result["status"] == "BLOCKED_RUNTIME_VERSION_UNVERIFIED"
    assert result["ready_for_core_compilation"] is False


def test_method_resolved_status_strictly_means_no_blockers():
    result = _planned()

    assert result["status"] == "METHOD_FIELDS_RESOLVED"
    assert result["blockers"] == []
    assert result["ready_for_core_compilation"] is True


def test_mock_methodplan_projects_full_calculationplan_marked_mock_only():
    planned = _planned(execution_mode="mock", runtime_version_verified=False)

    assert planned["status"] == "METHOD_FIELDS_RESOLVED", planned["blockers"]
    version = planned["fields"]["software_version"]
    assert version["value"] == "2025.2"
    assert version["provenance"] == "frozen_source"
    assert version["source_ref"] == "frozen-docx:sha256:source/page-4/table-1"
    assert version["rationale"] == "Version recorded in the cited software manifest."
    assert version["status"] == "SOURCE_CONFIRMED"
    assert version["approval_required"] is False

    projected = to_cp2k_calculation_plan_method(planned)

    assert projected["status"] == "READY", projected["blockers"]
    assert projected["execution_mode"] == "mock"
    assert projected["planning_scope"] == "MOCK_ONLY"
    assert projected["mock_only"] is True
    assert projected["real_execution_preflight_allowed"] is False
    plan = projected["calculation_plan"]
    assert plan["metadata"]["execution_mode"] == "mock"
    assert plan["metadata"]["planning_scope"] == "MOCK_ONLY"
    assert plan["metadata"]["mock_only"] is True
    assert plan["metadata"]["real_execution_preflight_allowed"] is False
    assert plan["metadata"]["runtime_verification_required_before_real_preflight"] is True
    assert plan["metadata"]["software_version_evidence"]["source_ref"] == version["source_ref"]


def test_mock_projection_blocks_when_software_version_has_no_source_ref():
    fields = _complete_fields()
    fields.pop("software_version")
    planned = _planned(fields, execution_mode="mock", runtime_version_verified=False)

    assert planned["status"] == "BLOCKED_MISSING_METHOD_FIELDS"
    assert "software_version" in planned["missing_fields"]
    projected = to_cp2k_calculation_plan_method(planned)
    assert projected["status"] == "BLOCKED"
    assert projected["calculation_plan"] is None


def test_explicit_na_with_source_and_rationale_is_accepted():
    fields = _complete_fields()
    fields["dispersion"] = {
        "status": "NOT_APPLICABLE", "value": None,
        "rationale": "The source method explicitly specifies no dispersion correction.",
        "source_ref": "paper:methods:dispersion-policy",
    }
    result = _planned(fields)

    assert result["status"] == "METHOD_FIELDS_RESOLVED"
    assert result["fields"]["dispersion"]["status"] == "NOT_APPLICABLE"
    assert result["fields"]["dispersion"]["source_ref"] == "paper:methods:dispersion-policy"


def test_plain_none_is_missing_and_not_interpreted_as_no_dispersion():
    fields = _complete_fields()
    fields["dispersion"] = None
    result = _planned(fields)

    assert result["fields"]["dispersion"]["status"] == "MISSING"
    assert "dispersion" in result["missing_fields"]
    assert result["status"] == "BLOCKED_MISSING_METHOD_FIELDS"


def test_na_without_source_or_rationale_is_not_accepted():
    fields = _complete_fields()
    fields["dispersion"] = {
        "status": "NOT_APPLICABLE", "value": None, "rationale": ""
    }
    result = _planned(fields)

    assert result["fields"]["dispersion"]["status"] == "MISSING"
    assert "dispersion" in result["missing_fields"]


def test_cp2k_projection_maps_required_method_and_uses_existing_validator():
    planned = _planned()
    assert planned["status"] == "METHOD_FIELDS_RESOLVED", planned["blockers"]

    result = to_cp2k_calculation_plan_method(planned)

    assert result["status"] == "READY", result["blockers"]
    assert result["validation"]["status"] == "PASS"
    assert set(result["method"]) == {
        "xc", "basis_set", "pseudopotential", "cutoff_ry", "scf", "charge",
        "multiplicity", "kind_definitions", "basis_file_name", "potential_file_name",
        "rel_cutoff_ry", "poisson_solver", "cell_periodicity", "poisson_periodicity",
        "uks", "center_coordinates",
    }
    assert result["method"]["xc"] == "PBE"
    assert result["method"]["cell_periodicity"] == "NONE"
    assert result["method"]["poisson_periodicity"] == "NONE"
    assert result["method"]["scf"] == {"method": "OT", "eps_scf": 1e-6, "max_scf": 100}
    assert result["field_provenance"]["cell_periodicity"]["source_field"] == "periodicity"
    assert result["preserved_fields"]["dispersion"]["value"] == "D3(BJ)"
    assert result["preserved_fields"]["spin"]["value"] == "closed_shell"
    assert result["preserved_fields"]["solvation.implicit"]["status"] == "NOT_APPLICABLE"


def test_required_plan_field_na_blocks_projection_instead_of_becoming_a_default():
    fields = _complete_fields()
    fields["basis_set"] = {
        "status": "NOT_APPLICABLE", "value": None,
        "rationale": "Marked not applicable in source.",
        "source_ref": "source:basis-na",
    }
    result = to_cp2k_calculation_plan_method(_planned(fields))

    assert result["status"] == "BLOCKED"
    assert result["method"] is None
    assert any("basis_set: NOT_APPLICABLE cannot satisfy" in item for item in result["blockers"])


def test_periodicity_and_poisson_periodicity_are_not_collapsed():
    fields = _complete_fields()
    fields["periodicity"] = "XY"
    fields["poisson_periodicity"] = "XYZ"
    fields["kpoints"] = "Gamma"
    fields["smearing"] = {
        "status": "NOT_APPLICABLE", "value": None,
        "rationale": "The source method specifies no electronic smearing.",
        "source_ref": "paper:methods:smearing-policy",
    }
    result = to_cp2k_calculation_plan_method(_planned(fields))

    assert result["status"] == "READY", result["blockers"]
    assert result["method"]["cell_periodicity"] == "XY"
    assert result["method"]["poisson_periodicity"] == "XYZ"


def test_projection_blocks_without_full_calculationplan_validation_context():
    result = to_cp2k_calculation_plan_method(_planned(include_context=False))

    assert result["status"] == "BLOCKED"
    assert result["validation"]["status"] == "NOT_RUN"
    assert any("calculation_plan_context is required" in item for item in result["blockers"])


def test_projection_validation_uses_existing_calculationplan_validate():
    fields = _complete_fields()
    fields["cutoff_ry"] = -1
    result = to_cp2k_calculation_plan_method(_planned(fields))

    assert result["status"] == "BLOCKED"
    assert result["validation"]["status"] == "FAIL"
    assert any(
        "CalculationPlan.validate(): method.cutoff_ry must be positive" in item
        for item in result["blockers"]
    )


def test_structure_periodicity_blocker_cannot_coexist_with_resolved_status():
    fields = _complete_fields()
    fields["kpoints"] = "Gamma"
    fields["smearing"] = "Gaussian"
    result = plan_method({
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "software_version": "2025.2",
        "runtime_version_verified": True,
        "runtime_verified_version": "2025.2",
        "structure": {"atom_count": 2, "system_type": "molecule"},
        "sources": [{
            "source_kind": "frozen_source",
            "source_ref": "source:complete-method",
            "fields": fields,
        }],
    })

    assert result["status"] == "BLOCKED_MISSING_METHOD_FIELDS"
    assert "structure.periodicity" in result["missing_fields"]
    assert result["ready_for_core_compilation"] is False
