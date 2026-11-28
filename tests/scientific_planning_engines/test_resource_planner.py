from pipeline_contracts.scientific_planning.engines import plan_resources


def _request(profile=None):
    request = {
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "software_version": "2025.2",
        "structure": {"atom_count": 48, "system_type": "slab"},
    }
    if profile is not None:
        request["resource_profile"] = profile
    return request


def test_missing_resource_profile_does_not_invent_quantitative_estimates():
    result = plan_resources(_request())

    assert result["status"] == "BLOCKED_MISSING_RESOURCE_PROFILE"
    assert result["real_execution_preflight_allowed"] is False
    assert result["quantitative_estimate_available"] is False
    assert result["quantitative_estimate"] is None
    assert result["allocation"]["nodes"]["value"] is None
    assert result["allocation"]["memory_gb"]["value"] is None
    assert len(result["missing_profile_fields"]) == 7


def test_verified_resource_profile_is_preserved_without_reestimation():
    profile = {
        "profile_id": "cluster-cpu-2026",
        "verified": True,
        "source_ref": "site-doc:slurm-policy-v3",
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "allocation": {
            "nodes": 2, "mpi_ranks": 64, "openmp_threads": 1, "gpu_count": 0,
            "memory_gb": 256, "walltime_seconds": 14400, "scratch_gb": 500,
        },
    }
    result = plan_resources(_request(profile))

    assert result["status"] == "READY_FOR_REAL_PREFLIGHT"
    assert result["real_execution_preflight_allowed"] is True
    assert result["allocation"]["mpi_ranks"]["value"] == 64
    assert result["allocation"]["mpi_ranks"]["source_ref"] == "site-doc:slurm-policy-v3"
    assert result["quantitative_estimate"] is None



def test_mock_resource_plan_contains_no_estimated_or_profile_allocation_numbers():
    profile = {
        "verified": True,
        "source_ref": "owner-profile:must-be-ignored-in-mock",
        "engine": "cp2k",
        "task_type": "cp2k.geo_opt",
        "allocation": {
            "nodes": 8, "mpi_ranks": 256, "openmp_threads": 2, "gpu_count": 4,
            "memory_gb": 1024, "walltime_seconds": 86400, "scratch_gb": 2000,
        },
    }
    result = plan_resources({**_request(profile), "execution_mode": "mock"})

    assert result["status"] == "MOCK_ONLY"
    assert result["planning_scope"] == "MOCK_ONLY"
    assert result["mock_only"] is True
    assert result["execution_mode"] == "mock"
    assert result["real_execution_preflight_allowed"] is False
    assert result["quantitative_estimate_available"] is False
    assert result["quantitative_estimate"] is None
    assert result["quantitative_reference_available"] is False
    assert result["historical_benchmark_reference"] is None
    assert set(result["allocation"]) == {
        "nodes", "mpi_ranks", "openmp_threads", "gpu_count",
        "memory_gb", "walltime_seconds", "scratch_gb",
    }
    assert all(item["value"] is None for item in result["allocation"].values())
    assert all(item["status"] == "NOT_APPLICABLE" for item in result["allocation"].values())
    assert all(item["provenance"] == "mock_only_not_estimated" for item in result["allocation"].values())


def test_mock_resource_plan_cannot_enter_real_preflight_even_with_verified_profile():
    profile = {
        "verified": True, "source_ref": "owner-profile:real",
        "engine": "cp2k", "task_type": "cp2k.geo_opt",
        "allocation": {
            "nodes": 1, "mpi_ranks": 32, "openmp_threads": 1, "gpu_count": 0,
            "memory_gb": 64, "walltime_seconds": 3600, "scratch_gb": 100,
        },
    }
    result = plan_resources({**_request(profile), "execution_mode": "mock"})

    assert result["status"] == "MOCK_ONLY"
    assert result["real_execution_preflight_allowed"] is False
    assert all(item["value"] is None for item in result["allocation"].values())
