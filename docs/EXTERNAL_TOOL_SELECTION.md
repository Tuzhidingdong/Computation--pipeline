# External Tool Selection — Initial Baseline

**Status:** Initial selection; versions and runtime compatibility remain to be verified by the remediation Agent.  
**Applies to:** Computation--pipeline v1.0.0 and the initial CO-reduction validation workflow.

## Decision summary

Use established scientific software for atomic structures, DFT syntax, output parsing, vibrations, charge analysis, rendering and document writing. Only build adapters and project-specific coordination logic where necessary.

| Function | Preferred tool | Intended owner/interface | Selection status |
|---|---|---|---|
| Atomic structure container, transformations and file I/O | [ASE](https://ase-lib.org/) | chem-scitoolkit wrappers; pipeline task/model orchestration | Selected; pin supported version after environment audit |
| Organic ligand graph and conformer operations | [RDKit](https://www.rdkit.org/) | Project model plugin via ASE/RDKit | Selected for organic fragments; transition-metal coordination must be explicitly constructed/validated |
| Local transition-metal coordination geometry suggestions | [molSimplify](https://molsimplify.mit.edu/) | Optional model-generation helper | Optional; evaluate exact ligand/metal suitability before relying on it |
| CP2K input parsing, generation and syntax/data-file lint | [cp2k-input-tools](https://github.com/cp2k/cp2k-input-tools) | chem-scitoolkit CP2K builder/validator | Preferred validation helper; verify compatibility with target CP2K 2025.2 inputs |
| CP2K output parsing and PDOS broadening | [cp2k-output-tools](https://github.com/cp2k/cp2k-output-tools) | chem-scitoolkit parser adapter | Preferred candidate; test exact output variants and retain metadata |
| Independent CP2K output/PDOS cross-check | [pymatgen CP2K interfaces](https://pymatgen.org/pymatgen.io.cp2k.html) | Tests/optional parser adapter | Optional cross-check; do not maintain two primary parsers |
| Vibrational finite differences and thermochemistry | [ASE](https://ase-lib.org/ase/thermochemistry/thermochemistry.html) | ASE algorithms via chem-scitoolkit; remote force task batching in pipeline | Selected; do not reimplement ASE's vibration/thermochemistry algorithms |
| Actual density-basin charge analysis | [Multiwfn](http://sobereva.com/multiwfn/) and/or a validated Bader implementation | chem-scitoolkit wrappers | Candidate runtime tools; verify installation, file requirements, version, output conventions and atom mapping |
| Charge-density cube visual inspection | [VESTA](https://jp-minerals.org/vesta/en/) / VMD | User-visible visualization and optional scripted rendering | Reuse installed tool; do not assume installation |
| Plot rendering | [Matplotlib](https://matplotlib.org/) | chem-scitoolkit | Selected; add configurable style profiles rather than another plotting library |
| Molecular/atomistic structure preview | ASE GUI / VESTA / VMD | Pipeline model-review package | Reuse; choose export path after local environment check |
| DOCX and XLSX writing | [python-docx](https://python-docx.readthedocs.io/) / [openpyxl](https://openpyxl.readthedocs.io/) | Pipeline report/export layer | Selected; verify installed versions |
| Provenance/workflow alternative | [AiiDA](https://aiida.net/) and [aiida-cp2k](https://github.com/cp2k/aiida-cp2k) | Future alternative only | Not selected for initial implementation; existing HPC Skills + light DAG meet current scale |

## CP2K parser policy

A single primary parser route must be selected after testing. The initial candidates are:
- `cp2k-output-tools` for common CP2K output values and PDOS broadening/export.
- `pymatgen.io.cp2k` for additional structured parsing/cross-checks.
- A small chem-scitoolkit parser layer for task-aware acceptance fields not provided by either tool.

Do not maintain two full parallel CP2K parsers. Every parser output must preserve its source log/output hash, CP2K version (when identifiable), parser version, and warnings.

## ASE vibration policy

ASE owns the finite-difference vibration and harmonic/ideal-gas thermochemistry algorithms. The project's remote calculation architecture is separate:
1. Pipeline uses ASE to enumerate displacement structures and atom mappings.
2. Pipeline batches CP2K ENERGY_FORCE tasks through the selected HPC Skill.
3. Pipeline validates/reassembles the force arrays and returns them to ASE-compatible structures.
4. ASE computes the Hessian/frequencies and thermochemistry.
5. chem-scitoolkit may provide a thin reusable wrapper and normalized result record.

Do not run the full 174 remote v4.1 force calls from a local ASE CP2K process unless a valid local calculator is explicitly chosen and tested.

## License/version/runtime checks required

Before declaring any dependency selected for production:
- Record package name, exact version, license, source URL, Python compatibility and optional dependencies.
- Verify the version can be installed in the user's current Python environment or the target HPC environment where required.
- Check that the license permits the intended use and redistribution of integration code.
- Test only the functions actually used by the pipeline.
- Store a lock/requirements record in the relevant upstream repository; do not hardcode workstation-specific absolute paths.
- Keep executables such as CP2K, Multiwfn and VESTA as detected external dependencies, not silently assumed bundled tools.

## Reference-only Agent Skills

The public [SFETNI/Deep-Matter-Chem-Skills](https://github.com/SFETNI/Deep-Matter-Chem-Skills) repository includes CP2K, ASE, AiiDA and DFT-convergence Skills. Its CP2K workflow metadata identifies itself as draft and lists CP2K 2023.2 as tested. Use it as a checklist/reference after checking the repository license and current revision. Do not import/copy its Skill wholesale or treat it as production-validated for CP2K 2025.2.

## MACE pre-screen caution

The initial v4.1 protocol mentions MACE-MP-0 as a geometry pre-screen only. Before using it, verify model metadata, element coverage, intended chemistry domain and force behavior on representative coordination motifs. It must not make final energy rankings, must not be the sole reason to discard a chemically distinct candidate, and must never substitute for DFT. If no defensible test is available for the Cu/Sn/polyphenol coordination environment, record MACE screening as unvalidated and preserve representative candidates for DFT review.

## Deferred

Do not add AiiDA, atomate2, jobflow, FireWorks, a database service, or an always-running workflow daemon in the first implementation. Reconsider only if concrete operational requirements exceed the current single-project resumable DAG design.
