from pipeline_contracts.scientific_planning.engines import plan_method, route_capability


def _request(sources):
    return {
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "software_version": "2025.2",
        "structure": {"atom_count": 6, "system_type": "molecule", "periodicity": "NONE"},
        "sources": sources,
    }


def test_missing_method_parameters_are_not_filled_with_defaults():
    result = plan_method(_request([]))

    assert result["status"] == "BLOCKED_MISSING_METHOD_FIELDS"
    assert result["parameter_defaults_applied"] is False
    assert result["ready_for_core_compilation"] is False
    assert result["fields"]["xc_functional"]["value"] is None
    assert result["fields"]["xc_functional"]["status"] == "MISSING"
    assert result["fields"]["dispersion"]["value"] is None
    assert result["fields"]["solvation.implicit"]["value"] is None
    assert "cutoff_ry" in result["missing_fields"]


def test_frozen_source_parameters_map_exactly_with_provenance():
    source = {
        "source_kind": "frozen_docx",
        "source_ref": "docx:sha256:abc123/page-7/table-2",
        "fields": {
            "xc_functional": {"value": "PBE", "rationale": "Source method table"},
            "cutoff_ry": {"value": 500, "uncertainty": "EXACT_SOURCE_VALUE"},
            "scf": {"method": "OT", "eps_scf": 1e-6, "max_scf": 150},
        },
    }
    result = plan_method(_request([source]))

    xc = result["fields"]["xc_functional"]
    assert xc["value"] == "PBE"
    assert xc["provenance"] == "frozen_source"
    assert xc["source_ref"] == source["source_ref"]
    assert result["fields"]["cutoff_ry"]["value"] == 500
    assert result["fields"]["cutoff_ry"]["uncertainty"] == "EXACT_SOURCE_VALUE"
    assert result["fields"]["scf.method"]["value"] == "OT"
    assert result["fields"]["scf.eps_scf"]["value"] == 1e-6
    assert result["fields"]["scf.max_scf"]["value"] == 150


def test_user_explicit_source_has_precedence_over_frozen_source():
    result = plan_method(_request([
        {"source_kind": "frozen_source", "source_ref": "paper:p1", "fields": {"xc_functional": "SCAN"}},
        {"source_kind": "user_explicit", "source_ref": "owner:decision-7", "fields": {"xc_functional": "PBE"}},
    ]))

    field = result["fields"]["xc_functional"]
    assert field["value"] == "PBE"
    assert field["source_ref"] == "owner:decision-7"


def test_approved_profile_can_select_a_method_value():
    result = plan_method(_request([
        {"source_kind": "approved_profile", "approved": True, "source_ref": "profile:rev-4",
         "fields": {"dispersion": {"value": "D3(BJ)", "rationale": "Approved project method policy"}}},
        {"source_kind": "candidate", "source_ref": "candidate:1",
         "fields": {"dispersion": {"value": "D4", "rationale": "Alternative for comparison"}}},
    ]))

    field = result["fields"]["dispersion"]
    assert field["value"] == "D3(BJ)"
    assert field["status"] == "APPROVED_POLICY"
    assert field["provenance"] == "approved_profile"


def test_unapproved_multiple_choices_remain_proposed_not_selected():
    result = plan_method(_request([
        {"source_kind": "candidate", "source_ref": "comparison:PBE", "fields": {"xc_functional": "PBE"}},
        {"source_kind": "candidate", "source_ref": "comparison:SCAN", "fields": {"xc_functional": "SCAN"}},
    ]))

    field = result["fields"]["xc_functional"]
    assert field["status"] == "PROPOSED"
    assert field["value"] is None
    assert {item["value"] for item in field["candidates"]} == {"PBE", "SCAN"}
    assert "xc_functional" in result["proposed_fields"]


def test_conflicting_same_priority_source_values_are_not_silently_resolved():
    result = plan_method(_request([
        {"source_kind": "user_explicit", "source_ref": "decision:A", "fields": {"charge": 0}},
        {"source_kind": "user_explicit", "source_ref": "decision:B", "fields": {"charge": 1}},
    ]))

    assert result["fields"]["charge"]["status"] == "CONFLICT"
    assert result["fields"]["charge"]["value"] is None
    assert "charge" in result["conflicting_fields"]


def test_null_field_does_not_satisfy_a_required_method_parameter():
    result = plan_method(_request([
        {"source_kind": "user_explicit", "source_ref": "user:explicit-no-value",
         "fields": {"cutoff_ry": None}},
    ]))

    assert result["fields"]["cutoff_ry"]["status"] == "MISSING"
    assert result["fields"]["cutoff_ry"]["value"] is None
    assert "cutoff_ry" in result["missing_fields"]


def test_unverified_runtime_version_blocks_final_method_compilation():
    request = _request([
        {"source_kind": "user_explicit", "source_ref": "owner:method",
         "fields": {"xc_functional": "PBE"}},
    ])
    result = plan_method(request)

    assert result["ready_for_core_compilation"] is False
    assert any("software version must be verified" in item.lower() for item in result["blockers"])


def _complete_cp2k_source(*, include_software_version=True):
    fields = {
        "xc_functional": "PBE",
        "dispersion": "D3(BJ)",
        "basis_set": "DZVP-MOLOPT-SR-GTH",
        "pseudopotential": "GTH-PBE",
        "basis_file_name": "BASIS_MOLOPT",
        "potential_file_name": "GTH_POTENTIALS",
        "kind_definitions": [{"element": "H", "basis": "DZVP-MOLOPT-SR-GTH", "potential": "GTH-PBE"}],
        "cutoff_ry": 600,
        "rel_cutoff_ry": 60,
        "scf": {"method": "OT", "eps_scf": 1e-6, "max_scf": 150},
        "charge": 0,
        "multiplicity": 1,
        "spin": 0,
        "uks": False,
        "center_coordinates": True,
        "periodicity": "NONE",
        "poisson_periodicity": "NONE",
        "poisson_solver": "MT",
        "solvation": {"implicit": "NONE", "explicit": "NONE"},
    }
    if include_software_version:
        fields["software_version"] = "2025.2"
    return {
        "source_kind": "frozen_source",
        "source_ref": "frozen-docx-sha256:page-4/table-1",
        "fields": fields,
    }


def test_source_backed_version_allows_mock_only_planning_but_not_real_preflight():
    request = _request([_complete_cp2k_source()])
    request["execution_mode"] = "mock"
    request["runtime_version_verified"] = False

    result = plan_method(request)
    route = route_capability(request)

    version = result["fields"]["software_version"]
    assert version["value"] == "2025.2"
    assert version["status"] == "SOURCE_CONFIRMED"
    assert version["source_ref"] == "frozen-docx-sha256:page-4/table-1"
    assert result["status"] == "METHOD_FIELDS_RESOLVED"
    assert result["ready_for_core_compilation"] is True
    assert not any("software version must be verified" in item.lower() for item in result["blockers"])
    assert route["runtime_version_verified"] is False
    assert route["can_enter_real_preflight"] is False


def test_request_metadata_version_without_source_stays_blocked_for_mock_planning():
    request = _request([_complete_cp2k_source(include_software_version=False)])
    request["execution_mode"] = "mock"
    request["runtime_version_verified"] = False

    result = plan_method(request)

    version = result["fields"]["software_version"]
    assert version["status"] == "DECLARED_UNVERIFIED"
    assert version["source_ref"] is None
    assert result["status"] == "BLOCKED_RUNTIME_VERSION_UNVERIFIED"
    assert result["ready_for_core_compilation"] is False
    assert any("software_version" in item.lower() or "software version" in item.lower()
               for item in result["blockers"])
