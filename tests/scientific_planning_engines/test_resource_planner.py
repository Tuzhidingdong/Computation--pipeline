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
