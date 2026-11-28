# Native Literature Acquisition and Source Package Preprocessing

## Purpose and integration boundary

This capability is a native optional execution stage of the existing Scientific
Reasoning flow:

ScientificIntent → ResearchPlan → Literature Research → Full-text acquisition →
Source Package → Evidence → Decision Dossier.

It is called by the existing project research CLI after the existing
OpenAlex/Crossref/Europe PMC/arXiv metadata search. It does not introduce a
second run_workflow.py, workflow database, WorkflowController, ResearchPlan
store, project state machine, or Artifact Store. Data_analysis registration is
delegated only to the existing register_derived_artifact /
resolve_artifact_path API supplied through the Pipeline's existing
integration factory.

The PaperQA2 optional plugin remains an evidence-retrieval/assessment plugin.
It is not used as a publisher downloader.

## Upstream source and source-to-target map

The migrated upstream baseline is
[Tuzhidingdong/chem-literature](https://github.com/Tuzhidingdong/chem-literature)
commit e099406adb689281c0337bcacc7868c3ccdbc438.

| Upstream source at pinned commit | Pipeline destination | Migration notes |
|---|---|---|
| core/paper_harvester.py | pipeline_contracts/literature_acquisition/paper_harvester.py | Publisher-specific routines preserved; adds DOI collision resistance, atomic writes, file/PyMuPDF validation, SHA cache sidecars and Acquisition Report diagnostics |
| core/vpn_session.py | pipeline_contracts/literature_acquisition/vpn_session.py | CDP/WebVPN algorithm preserved; configurable portal/resource IDs/browser, independent temporary profiles/ports, bounded timeouts and safe cleanup |
| core/preprocessing/source_preprocessor.py | pipeline_contracts/literature_acquisition/source_preprocessor.py | Deterministic 712-line implementation retained; only package schema path and optional GROBID environment variable are adapted, with source input SHA locators added |
| core/preprocessing/pipeline.py | pipeline_contracts/literature_acquisition/package_builder.py | ZIP safety, SI dispatch, preprocessing isolation and cache lineage retained; adds MAIN-only support, actual streamed ZIP limits, full cache asset rehash, atomic package promotion and original input copies |
| schemas/source_package.schema.json | pipeline_contracts/literature_acquisition/schemas/source_package.schema.json | Contract retained; Pipeline-local ID, explicit FAILED status and zero-page failed-package representation added |
| tests/test_source_preprocessor.py | tests/test_source_preprocessor.py | Original offline regression tests migrated with Pipeline import paths |
| tests/test_preprocessing_pipeline.py | tests/test_preprocessing_pipeline.py | Original ZIP/SI/cache tests migrated with Pipeline import paths |
| README.md, SKILL.md, config/settings.yaml | This migration document, publisher matrix, local JSON config example and Windows acceptance runbook | Configuration values that were institution-specific are not copied as defaults |

The repository tree at the exact source commit contains no LICENSE,
LICENSE.md, or COPYING file. The upstream README says “MIT License”,
but this is recorded only as an upstream README declaration; this migration
does not claim that a formal MIT license file was present or independently
verified. The user's explicit authorization to transfer between the two
owned repositories is the operational basis for this task. No upstream
license file has been fabricated.

## Publisher acquisition implementation

Only the following publishers have executable retrieval routes in this port:

- **Elsevier / ScienceDirect**: Crossref DOI → PII; isolated CDP navigation;
  article DOM lazy-load scroll; removal of print-media CSS restrictions and
  non-article page elements; Emulation.setEmulatedMedia; Page.printToPDF;
  MMC / ars.els-cdn.com supplementary-link discovery.
- **Wiley**: /doi/pdfdirect/{doi}?download=true; navigate to the full-text
  article; discover downloadSupplement URLs and validate supported SI.
- **IOP Publishing / ECS**: /article/{doi}/pdf direct binary retrieval.

Springer, ACS, RSC, Nature and Science are explicitly reported as
NOT_IMPLEMENTED. A configured WebVPN resource ID does not imply that a
publisher downloader exists. There is no general Open Access fallback; without
authorized Cookie credentials the result is UNAVAILABLE, not a claimed
full-text success.

See [Publisher Support Matrix](LITERATURE_PUBLISHER_SUPPORT_MATRIX.md).

## WebVPN session security

- Portal URL, publisher resource IDs, Cookie directory and Edge/Chromium path
  are local configuration values. No UCAS portal URL or institution resource
  ID is a Pipeline default.
- Each Cookie account is assigned its own browser process, CDP port and fresh
  temporary browser profile. No daily Edge/Chrome user profile is opened.
- Cookie content is read only for CDP injection; Cookie values and filenames
  are not written to Acquisition Reports, Dossiers, artifacts or Git.
- Access denied, CAPTCHA, HTTP 403/429/451/503 and browser challenge pages stop
  the affected publisher/account task. A CDP/network interruption gets one
  bounded isolated-session recovery attempt; consecutive failures trip a
  per-account circuit breaker.
- Session temporary directories are cleaned when the worker exits.
- Public publisher URLs, not WebVPN proxy URLs containing session route tokens,
  are recorded as source URLs.

## Integrity, caching and atomicity

- PDF responses must start with %PDF-, meet the configured minimum and open
  successfully in PyMuPDF with at least one readable page.
- ZIP and DOCX responses are validated as ZIP containers; DOCX additionally
  requires word/document.xml.
- Cached MAIN PDFs are rechecked for magic bytes, size, PyMuPDF readability,
  page count and SHA-256 sidecar equality. A filename or file-existence check is
  never sufficient.
- DOI file keys append a SHA-256 identity suffix, avoiding sanitized-name
  collisions.
- Download writes use a same-directory temporary file and os.replace.
  Source Package creation uses a staging directory and atomic promotion; a
  failed refresh does not delete a prior valid Source Package.
- The original MAIN and SI input bytes are copied into source_files/;
  original SI ZIP archives are also retained under source_archives/, where
  supplied.
- The source-package cache signature includes input SHA values and relevant
  preprocessing/GROBID/ZIP/DPI settings. All cached media asset bytes are
  rehashed before reuse.

## Source Package contents and interpretation boundary

A successful or partial package contains:

- main_analysis.md, si_analysis.md
- page_text/ with per-page text
- extracted_tables/ with CSV/Markdown/table summaries
- extracted_figures/MAIN/ and extracted_figures/SI/
- supplementary/ with PDF/DOCX extracted content and media
- source_files/ with byte-preserved MAIN/SI originals
- source_archives/ with original SI ZIP files, where supplied
- evidence_index.json
- PREPROCESSING_QC_REPORT.md
- PREPROCESSING_INPUTS.json

Preprocessing retains page blocks, coordinates, table rows, figure captions,
SI references, source/asset SHA-256 and file/page locators. GROBID is optional;
PyMuPDF is the fallback. OCR is not performed. Pages with insufficient text
are flagged as scanned. Extracted images are asset records only. No claim is
made that an image has been visually or scientifically interpreted.

Statuses include COMPLETE, WARNING_SCANNED_PAGES, PARTIAL_NO_SI,
PARTIAL_SI_UNSUPPORTED, and FAILED. Acquisition statuses include
FULL_TEXT_PLUS_SI, FULL_TEXT_ONLY, PARTIAL, UNAVAILABLE, FAILED, and
NOT_IMPLEMENTED.

## Evidence and Artifact registration

The evidence builder converts Source Package page/table/figure/SI DOCX records
to Dossier evidence with stable Evidence IDs, source-file SHA-256, text SHA-256,
page/table/figure locators, and visual interpretation status. Where Data_analysis
registration succeeds, these rows carry the existing Pipeline
ArtifactRef and EvidenceRef shapes.

Registration is considered successful only when the existing Data_analysis API
returns a non-empty Artifact ID and matching SHA-256, and its resolver returns
the same bytes with the same SHA-256. Local file paths are not treated as
Artifact IDs. Without the existing API/project root/format IDs, the package is
kept locally and explicitly marked LOCAL_UNREGISTERED; Evidence rows have
no fabricated ArtifactRef.

All artifacts returned by a mock Data_analysis adapter are visibly marked
mock=true / MOCK_ONLY. Mock IDs are not written into real artifact records.

Local full-text, SI and extracted excerpts are excluded from external Skill
executor payloads by default. The existing
--allow-local-evidence-to-external-ai flag is the separate explicit consent
needed to send them to that executor. Public bibliographic metadata and
abstracts can still be assessed according to the existing
--allow-external-ai boundary.

## CLI

Copy .pipeline/literature-acquisition.local.example.json to
.pipeline/literature-acquisition.local.json, populate the user's WebVPN
portal and publisher resource IDs, and place authorized Cookie JSON files in
the configured local Cookie directory (default in the example:
.pipeline/webvpn-cookies/).

~~~powershell
python -m pipeline_contracts.cli project research <PROJECT_RUN_ID> --state-db .pipeline/workflow.sqlite --output-root runs --project-profile .pipeline/project_profile.json --literature-config .pipeline/literature-acquisition.local.json --full-text
~~~

Without --full-text, acquisition runs only when enabled in the selected
local config or Project Profile. Without credentials/browser configuration,
metadata literature research still runs and the full-text stage reports
UNAVAILABLE with its cause.

To register real source files, additionally use the existing Pipeline
--integration-factory that supplies the existing Data_analysis API and
--data-analysis-project-root, and configure the API's actual format IDs.
If this is not supplied, local packages are explicitly LOCAL_UNREGISTERED.

No model decision or model approval is triggered by acquisition.
