"""Calculation-specific QC evidence contracts and staged evaluation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def _check(key: str, description: str, *, level: int, required: bool = True) -> dict[str, Any]:
    return {"evidence_key": key, "description": description, "required": required, "level": level}


def _contract(task_type: str, description: str, checks: list[dict[str, Any]], *,
              special_rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "task_type": task_type, "description": description,
        "validation_levels": [
            {"level": 1, "name": "output_completeness", "meaning": "Required files/Artifacts exist and hashes are verified."},
            {"level": 2, "name": "normal_termination", "meaning": "Program/scheduler ended normally; this alone is not convergence."},
            {"level": 3, "name": "technical_convergence", "meaning": "Numerical algorithm met declared source-backed criteria."},
            {"level": 4, "name": "structural_numerical_plausibility", "meaning": "Objective geometry/mapping/numerical checks pass."},
            {"level": 5, "name": "scientific_conclusion_validity", "meaning": "A scientific reviewer verifies that evidence supports the intended claim."},
            {"level": 6, "name": "user_acceptance", "meaning": "The authorized user/owner explicitly accepts the result."},
        ],
        "checks": checks, "special_rules": deepcopy(dict(special_rules or {})),
        "automatic_scientific_acceptance": False, "automatic_user_acceptance": False,
    }


_BASE = [
    _check("output_files_complete", "All task-required output files are present.", level=1),
    _check("artifact_hashes_verified", "Input/output Artifact identities and SHA-256 values are verified.", level=1),
    _check("program_normal_termination", "Engine reports normal termination.", level=2),
    _check("scheduler_completed", "Scheduler completed and application exit code is zero.", level=2),
    _check("technical_convergence", "Calculation-specific numerical convergence checks passed.", level=3),
    _check("numerical_values_finite", "Required energies/forces/frequencies are finite and parseable.", level=4),
    _check("structural_anomalies_absent", "No atom loss, forbidden overlap or chemically impossible geometry is detected.", level=4),
]


_CONTRACTS = {
    "geo_opt": _contract("geo_opt", "Geometry optimization with explicit fixed-cell/cell policy.", _BASE + [
        _check("all_optimizer_criteria_met", "All declared optimizer criteria pass (maximum/RMS forces and displacements as applicable).", level=3),
        _check("atom_count_and_identity_preserved", "Atom count, element identity and atom mapping are preserved.", level=4),
        _check("cell_constraints_preserved", "Cell, periodicity and fixed-atom constraints match the approved input.", level=4),
    ]),
    "energy_scf": _contract("energy_scf", "Single-point energy and SCF calculation.", _BASE + [
        _check("scf_converged", "SCF convergence is confirmed from parsed engine output.", level=3),
        _check("electronic_state_consistent", "Charge, spin/multiplicity and state match the approved method.", level=4),
        _check("energy_reference_declared", "Energy units/reference and correction convention are declared.", level=4),
    ]),
    "frequency": _contract("frequency", "Harmonic frequency/vibrational analysis.", _BASE + [
        _check("frequency_job_complete", "Frequency calculation completed and all requested modes are present.", level=3),
        _check("mode_count_matches_degrees_of_freedom", "Mode count is consistent with molecular/periodic constraints and removed modes.", level=4),
        _check("imaginary_mode_count_interpreted", "Imaginary modes are counted and their eigenvectors interpreted.", level=4),
    ]),
    "neb_band_dimer": _contract("neb_band_dimer", "Reaction-path optimization using NEB/BAND or Dimer.", _BASE + [
        _check("all_path_images_present", "All required endpoints/intermediate images are present.", level=1),
        _check("endpoints_independently_optimized", "Initial/final endpoints are converged at the same approved method.", level=3),
        _check("atom_mapping_consistent", "Every image preserves the same atom identity/order mapping.", level=4),
        _check("every_image_converged", "Every replica/image meets its declared convergence criteria.", level=3),
        _check("declared_force_threshold_present", "The source-backed maximum-force threshold is recorded.", level=3),
        _check("max_force_value_present", "The maximum relevant image/path force is reported.", level=3),
        _check("max_force_below_declared_threshold", "Maximum relevant force is below the declared threshold.", level=3),
        _check("path_energy_profile_complete", "All image energies are present with consistent method and units.", level=4),
        _check("path_structural_anomalies_absent", "No image contains atom crossing, severe contacts or implausible geometry.", level=4),
        _check("dimer_mode_converged", "Dimer rotation/translation convergence and target mode are confirmed.", level=3, required=False),
        _check("frequency_job_complete", "A separate frequency calculation completed for TS confirmation.", level=3, required=False),
    ], special_rules={
        "transition_state_confirmation": {
            "frequency_evidence_required": True,
            "required_evidence": ["frequency_job_complete", "imaginary_mode_count",
                                  "one_chemically_meaningful_imaginary_mode",
                                  "mode_alignment_to_reaction_coordinate"],
            "expected_imaginary_mode_count": 1,
            "irc_or_endpoint_connectivity_evidence_required_when_claimed": True,
            "highest_energy_image_alone_is_transition_state": False,
            "rule": "The path maximum is only a candidate geometry. Do not label it a transition state without a separate frequency calculation and a chemically meaningful first-order saddle mode.",
        },
        "path_requirements": ["explicit endpoints", "same atom map", "all images converged",
                              "declared maximum-force threshold", "complete energy profile", "geometry anomaly check"],
    }),
    "aimd": _contract("aimd", "Ab initio molecular dynamics trajectory.", _BASE + [
        _check("trajectory_frames_complete", "Trajectory frame/time range matches the declared run.", level=1),
        _check("scf_converged_each_required_step", "SCF convergence evidence exists for each required MD step.", level=3),
        _check("time_step_and_ensemble_declared", "Time step, ensemble, thermostat/barostat and run controls are declared.", level=4),
        _check("energy_drift_within_declared_limit", "Energy drift is assessed against a declared justified limit.", level=4),
        _check("equilibration_assessed", "Equilibration and production windows are distinguished.", level=4),
    ]),
    "explicit_solvent": _contract("explicit_solvent", "Explicit solvent box/molecular packing preparation.", [
        _check("output_files_complete", "Packed coordinates and builder log are complete.", level=1),
        _check("artifact_hashes_verified", "Templates, input deck and output coordinates have recorded hashes.", level=1),
        _check("program_normal_termination", "Packmol/builder completed normally.", level=2),
        _check("builder_version_recorded", "Exact Packmol builder/version is recorded.", level=2),
        _check("molecule_counts_match", "Molecule counts by species match declared input counts.", level=4),
        _check("box_vectors_and_units_verified", "Box vectors, shape and length units are explicit.", level=4),
        _check("periodicity_declared", "Periodic boundary conditions are explicitly declared downstream.", level=4),
        _check("minimum_distances_verified", "Minimum interatomic/intermolecular distances meet a declared policy.", level=4),
        _check("collisions_absent", "Unphysical overlaps/collisions are absent.", level=4),
        _check("molecular_templates_intact", "Molecular connectivity, atom identity and intramolecular geometry are preserved.", level=4),
        _check("equilibration_evidence_available", "Separate MD equilibration evidence exists; initial packing is not equilibration.", level=4, required=False),
    ], special_rules={
        "initial_packing_is_equilibrated": False,
        "equilibration_claim_requires_separate_md_evidence": True,
        "builder_output_is_initial_condition_only": True,
    }),
    "electronic_analysis": _contract("electronic_analysis", "Post-processing of electronic-structure data.", _BASE + [
        _check("source_wavefunction_or_density_available", "Required wavefunction, charge density or source Artifact exists.", level=1),
        _check("parser_version_and_format_verified", "Parser version and source format are recorded.", level=2),
        _check("analysis_parameters_declared", "Energy window, projection, grid, spin and normalization settings are declared.", level=4),
        _check("normalization_and_sum_rules_checked", "Applicable normalization/state-count/integration checks pass.", level=4),
        _check("chemical_interpretation_reviewed", "Chemical interpretation is checked against the intended claim.", level=5),
    ]),
}


_ALIASES = {
    "cp2k.geo_opt": "geo_opt", "vasp.relax": "geo_opt", "gaussian.opt": "geo_opt",
    "geo_opt": "geo_opt", "geometry_optimization": "geo_opt",
    "cp2k.energy": "energy_scf", "vasp.energy": "energy_scf", "gaussian.energy": "energy_scf",
    "energy": "energy_scf", "scf": "energy_scf",
    "cp2k.freq": "frequency", "gaussian.freq": "frequency", "vasp.freq": "frequency",
    "frequency": "frequency", "freq": "frequency",
    "cp2k.band": "neb_band_dimer", "cp2k.neb": "neb_band_dimer", "vasp.neb": "neb_band_dimer",
    "neb": "neb_band_dimer", "band": "neb_band_dimer", "dimer": "neb_band_dimer",
    "cp2k.aimd": "aimd", "vasp.aimd": "aimd", "aimd": "aimd",
    "solvent.prepare_explicit": "explicit_solvent", "packmol.prepare": "explicit_solvent",
    "explicit_solvent.preparation": "explicit_solvent", "structure.pack_molecules": "explicit_solvent",
    "electronic_structure.analysis": "electronic_analysis", "dft.analysis": "electronic_analysis",
}


def get_qc_contract(task_type: str) -> dict[str, Any]:
    token = str(task_type).strip().casefold()
    selected = _ALIASES.get(token)
    if selected is None:
        return {"task_type": token or None, "status": "UNREGISTERED_QC_CONTRACT", "checks": [],
                "blockers": [f"No QC contract is registered for task_type {task_type!r}."],
                "automatic_scientific_acceptance": False, "automatic_user_acceptance": False}
    result = deepcopy(_CONTRACTS[selected])
    result["task_type"] = token
    result["status"] = "REGISTERED"
    return result


def evaluate_qc(task_type: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate evidence completeness/status; scientific validity and acceptance remain explicit."""
    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be a Mapping")
    contract = get_qc_contract(task_type)
    if contract.get("status") != "REGISTERED":
        return {"status": "UNREGISTERED_QC_CONTRACT", "contract": contract, "checks": []}

    results = []
    for check in contract["checks"]:
        key, value = check["evidence_key"], evidence.get(check["evidence_key"])
        if value is None:
            status = "NOT_EVALUATED"
        elif isinstance(value, bool):
            status = "PASS" if value else "FAIL"
        else:
            status = "EVIDENCE_PROVIDED_REQUIRES_INTERPRETATION"
        results.append({"evidence_key": key, "level": check["level"], "required": check["required"],
                        "status": status, "value": deepcopy(value)})

    failures = [x for x in results if x["required"] and x["status"] == "FAIL"]
    missing = [x for x in results if x["required"] and x["status"] == "NOT_EVALUATED"]
    technical = [x for x in results if x["level"] <= 4 and x["required"]]
    if failures:
        technical_status = "TECHNICAL_QC_FAILED"
    elif any(x["status"] != "PASS" for x in technical):
        technical_status = "TECHNICAL_QC_INCOMPLETE"
    else:
        technical_status = "TECHNICAL_QC_PASSED"

    review = evidence.get("scientific_review")
    scientific_status = "REQUIRES_SCIENTIFIC_REVIEW"
    if isinstance(review, Mapping) and review.get("review_status") in {"ACCEPTED", "REJECTED"} and review.get("reviewer") and review.get("source_ref"):
        scientific_status = "SCIENTIFIC_REVIEW_ACCEPTED" if review["review_status"] == "ACCEPTED" else "SCIENTIFIC_REVIEW_REJECTED"

    acceptance = evidence.get("user_acceptance")
    user_status = "WAITING_FOR_USER_ACCEPTANCE"
    if isinstance(acceptance, Mapping) and acceptance.get("accepted") is True and acceptance.get("accepted_by") and acceptance.get("source_ref"):
        user_status = "USER_ACCEPTED"
    elif isinstance(acceptance, Mapping) and acceptance.get("accepted") is False:
        user_status = "USER_REJECTED"

    ts_status = None
    ts_rule = contract.get("special_rules", {}).get("transition_state_confirmation")
    if isinstance(ts_rule, Mapping):
        has_freq = evidence.get("frequency_job_complete") is True
        one_mode = evidence.get("imaginary_mode_count") == ts_rule["expected_imaginary_mode_count"]
        meaningful = evidence.get("one_chemically_meaningful_imaginary_mode") is True
        aligned = evidence.get("mode_alignment_to_reaction_coordinate") is True
        ts_status = "TS_EVIDENCE_COMPLETE" if has_freq and one_mode and meaningful and aligned else "TS_NOT_CONFIRMED"

    return {
        "status": technical_status, "task_type": contract["task_type"], "checks": results,
        "technical_qc_status": technical_status,
        "scientific_conclusion_status": scientific_status, "user_acceptance_status": user_status,
        "transition_state_status": ts_status,
        "blocking_checks": [x["evidence_key"] for x in failures + missing],
        "automatic_scientific_acceptance": False, "automatic_user_acceptance": False,
        "special_rules": deepcopy(contract.get("special_rules", {})),
    }


__all__ = ["get_qc_contract", "evaluate_qc"]
