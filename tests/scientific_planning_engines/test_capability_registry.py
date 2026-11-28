from pipeline_contracts.scientific_planning.engines import load_registry, route_capability


def test_registry_entries_are_complete_and_have_valid_integration_status():
    registry = load_registry()
    capabilities = registry["capabilities"]

    assert {item["engine"] for item in capabilities} >= {
        "CP2K", "VASP", "Gaussian", "ASE", "pymatgen", "Packmol"
    }
    for item in capabilities:
        assert item["capability_id"]
        assert item["version"]["documented_versions"]
        assert item["supported_task_types"]
        assert item["input_structure_requirements"]
        assert item["required_method_fields"]
        assert item["expected_outputs"]
        assert item["capability_sources"]
        assert item["license"]
        assert item["integration_status"] in {
            "AVAILABLE", "PLANNABLE_ONLY", "NOT_INTEGRATED", "UNVERIFIED"
        }
        assert "parser_qc_plugins" in item
        assert isinstance(item["allows_real_execution_plan"], bool)


def test_sccs_feature_from_source_mapping_is_still_plannable_only():
    route = route_capability({
        "engine": "CP2K",
        "task_type": "cp2k.energy",
        "software_version": "2026.2",
        "runtime_version_verified": True,
        "sources": [{
            "source_kind": "frozen_source",
            "source_ref": "paper:SI:solvation",
            "fields": {"solvation": {"implicit": {"model": "SCCS"}}},
        }],
    })

    assert "sccs" in route["requested_features"]
    assert route["integration_status"] == "PLANNABLE_ONLY"
    assert route["allows_real_execution_plan"] is False


def test_available_adapter_requires_exact_runtime_version_for_real_preflight():
    route = route_capability({"engine": "CP2K", "task_type": "cp2k.geo_opt",
                              "software_version": "2025.2"})
    assert route["integration_status"] == "AVAILABLE"
    assert route["allows_real_execution_plan"] is True
    assert route["can_enter_real_preflight"] is False



def test_real_preflight_requires_exact_runtime_verified_version_match():
    matching = route_capability({
        "engine": "CP2K", "task_type": "cp2k.geo_opt",
        "software_version": "2025.2", "runtime_version_verified": True,
        "runtime_verified_version": "2025.2",
    })
    mismatched = route_capability({
        "engine": "CP2K", "task_type": "cp2k.geo_opt",
        "software_version": "2025.2", "runtime_version_verified": True,
        "runtime_verified_version": "2025.1",
    })

    assert matching["can_enter_real_preflight"] is True
    assert matching["runtime_version_matches"] is True
    assert mismatched["can_enter_real_preflight"] is False
    assert mismatched["runtime_version_matches"] is False


def test_mock_capability_route_never_enters_real_preflight():
    route = route_capability({
        "engine": "CP2K", "task_type": "cp2k.geo_opt",
        "execution_mode": "mock", "software_version": "2025.2",
        "runtime_version_verified": True, "runtime_verified_version": "2025.2",
    })

    assert route["execution_mode"] == "mock"
    assert route["can_enter_real_preflight"] is False
    assert any("Mock-only" in item for item in route["blockers"])
