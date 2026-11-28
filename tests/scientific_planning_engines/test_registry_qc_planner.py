from pipeline_contracts.scientific_planning.engines import (
    build_engine_planning, evaluate_qc, get_qc_contract, route_capability,
)


def test_cp2k_geo_opt_and_energy_are_only_available_real_adapter_routes():
    for operation in ("cp2k.geo_opt", "cp2k.energy"):
        route = route_capability({"engine": "CP2K", "task_type": operation,
                                  "software_version": "2025.2", "runtime_version_verified": True, "runtime_verified_version": "2025.2"})
        assert route["integration_status"] == "AVAILABLE"
        assert route["allows_real_execution_plan"] is True

    for engine, task in (("CP2K", "cp2k.band"), ("CP2K", "cp2k.neb")):
        route = route_capability({"engine": engine, "task_type": task,
                                  "software_version": "2025.2", "runtime_version_verified": True, "runtime_verified_version": "2025.2"})
        assert route["integration_status"] == "PLANNABLE_ONLY"
        assert route["allows_real_execution_plan"] is False
        assert route["can_enter_real_preflight"] is False


def test_cp2k_sccs_is_plannable_feature_not_real_adapter():
    route = route_capability({
        "engine": "CP2K", "task_type": "cp2k.energy",
        "software_version": "2026.2", "runtime_version_verified": True, "runtime_verified_version": "2026.2",
        "features": ["sccs"],
    })

    assert route["software_supported"] is True
    assert route["integration_status"] == "PLANNABLE_ONLY"
    assert route["allows_real_execution_plan"] is False
    assert "cp2k.sccs" in route["capability_ids"]


def test_vasp_gaussian_and_packmol_are_not_claimed_as_pipeline_real_adapters():
    routes = [
        route_capability({"engine": "VASP", "task_type": "vasp.relax", "software_version": "6.6.1"}),
        route_capability({"engine": "Gaussian", "task_type": "gaussian.opt", "software_version": "G16"}),
        route_capability({"engine": "Packmol", "task_type": "solvent.prepare_explicit", "software_version": "21.2.3"}),
    ]
    assert all(item["integration_status"] == "PLANNABLE_ONLY" for item in routes)
    assert all(item["allows_real_execution_plan"] is False for item in routes)


def test_qc_contracts_keep_six_validation_layers_separate():
    contract = get_qc_contract("cp2k.geo_opt")
    assert contract["status"] == "REGISTERED"
    assert [item["level"] for item in contract["validation_levels"]] == [1, 2, 3, 4, 5, 6]
    assert contract["automatic_scientific_acceptance"] is False
    assert contract["automatic_user_acceptance"] is False


def test_neb_qc_requires_per_image_mapping_force_and_frequency_for_transition_state():
    contract = get_qc_contract("cp2k.band")
    keys = {item["evidence_key"] for item in contract["checks"]}
    assert {"all_path_images_present", "atom_mapping_consistent", "every_image_converged",
            "declared_force_threshold_present", "max_force_value_present",
            "max_force_below_declared_threshold", "path_structural_anomalies_absent"} <= keys
    assert contract["special_rules"]["transition_state_confirmation"]["highest_energy_image_alone_is_transition_state"] is False

    evidence = {
        "frequency_job_complete": True,
        "imaginary_mode_count": 1,
        "one_chemically_meaningful_imaginary_mode": True,
        "mode_alignment_to_reaction_coordinate": True,
    }
    result = evaluate_qc("cp2k.neb", evidence)
    assert result["transition_state_status"] == "TS_EVIDENCE_COMPLETE"
    assert evaluate_qc("cp2k.neb", {})["transition_state_status"] == "TS_NOT_CONFIRMED"


def test_explicit_solvent_qc_distinguishes_packing_from_equilibration():
    contract = get_qc_contract("solvent.prepare_explicit")
    keys = {item["evidence_key"] for item in contract["checks"]}
    assert {"builder_version_recorded", "molecule_counts_match", "box_vectors_and_units_verified",
            "periodicity_declared", "minimum_distances_verified", "collisions_absent"} <= keys
    assert contract["special_rules"]["initial_packing_is_equilibrated"] is False
    assert contract["special_rules"]["equilibration_claim_requires_separate_md_evidence"] is True


def test_composed_planning_returns_mapping_without_executing_or_building_plan():
    result = build_engine_planning({
        "engine": "CP2K", "task_type": "cp2k.band",
        "structure": {"atom_count": 20, "system_type": "molecule", "periodicity": "NONE"},
    })

    assert result["creates_calculation_plan"] is False
    assert result["submits_or_executes_calculation"] is False
    assert result["capability_route"]["integration_status"] == "PLANNABLE_ONLY"
    assert result["qc_contract"]["status"] == "REGISTERED"
