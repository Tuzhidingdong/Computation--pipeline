"""Report exact modeling-tool versions and fail on missing required tools."""
from __future__ import annotations
from importlib import metadata

DISTRIBUTIONS = {
    "ase": "ase",
    "rdkit": "rdkit",
    "molSimplify": "molSimplify",
    "mace_torch": "mace-torch",
}


def toolchain_report(*, require_rdkit: bool = False, require_molsimplify: bool = False,
                     require_mace: bool = False) -> dict:
    required = {"ase"}
    if require_rdkit:
        required.add("rdkit")
    if require_molsimplify:
        required.add("molSimplify")
    if require_mace:
        required.add("mace_torch")
    packages = {}
    for key, distribution in DISTRIBUTIONS.items():
        try:
            version = metadata.version(distribution)
            packages[key] = {"available": True, "version": version,
                             "required": key in required}
        except metadata.PackageNotFoundError:
            packages[key] = {"available": False, "version": None,
                             "required": key in required}
    missing = [key for key in required if not packages[key]["available"]]
    return {"status": "READY" if not missing else "MISSING_REQUIRED_TOOLS",
            "packages": packages, "missing_required": sorted(missing)}
