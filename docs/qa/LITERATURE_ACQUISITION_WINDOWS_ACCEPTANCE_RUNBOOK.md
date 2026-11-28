# Windows Local Acceptance Runbook — Native Literature Acquisition

## 1. Safety boundary

This acceptance uses only the user's own authorized WebVPN account and normal
publisher access. It must not bypass CAPTCHA, 403/429 restrictions, account
quotas, paywalls or publisher terms. Stop a publisher test on an access-denial,
challenge or rate-limit result and retain the diagnostic.

Never copy Cookie values into PowerShell history, issue text, console output,
screenshots, logs, Git, GitHub Actions, PR attachments or Data_analysis
artifacts. Never upload the Cookie JSON file. Use the Pipeline's isolated
temporary Edge/Chromium profile; do not export or open the user's daily browser
profile.

The offline CI tests use synthetic documents and mock registries. This runbook
is the separate manual verification of a real authorized environment.

## 2. Install local dependencies

From the Pipeline repository root in PowerShell:

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-literature-acquisition.txt
~~~

Edge is auto-discovered on Windows. To use a specific Edge or Chromium binary,
set browser_executable in the local config. No daily user profile path is
accepted as a browser profile setting; the implementation always creates a
new temporary --user-data-dir.

## 3. Prepare a local-only configuration

Copy the example:

~~~powershell
Copy-Item .pipeline\literature-acquisition.local.example.json .pipeline\literature-acquisition.local.json
New-Item -ItemType Directory -Force .pipeline\webvpn-cookies | Out-Null
~~~

Edit only the local file. Supply:

- your institution's actual portal_url;
- the WebVPN resource IDs for Elsevier, Wiley and IOP/ECS from your own portal;
- an optional explicit Edge executable path;
- your desired local output location and safe request delays;
- actual Data_analysis Artifact format IDs only if an existing Data_analysis
  integration factory is going to be used.

The example deliberately contains no UCAS URL or institution resource IDs.
A resource ID must not be copied from another organization.

Put one Cookie-Editor JSON export per authorized account in the configured
Cookie directory. The supported formats are either a top-level Cookie array
or an object containing a cookies array. Keep the files local. The Pipeline
reads values only for CDP Cookie injection.

Check that no Cookie file is tracked:

~~~powershell
git status --short
git check-ignore .pipeline\webvpn-cookies\account01.json
git check-ignore .pipeline\literature-acquisition.local.json
~~~

If either command does not report the path as ignored, stop and correct the
local ignore rule before proceeding.

## 4. Verify configuration without opening a browser

Run the offline acquisition tests:

~~~powershell
python -m pytest -q tests/test_literature_acquisition.py
python -m pytest -q tests/test_source_preprocessor.py tests/test_preprocessing_pipeline.py
~~~

Review local config values. Confirm that portal URL, resource IDs, Cookie
directory and executable path are the values you intended. No Cookie content
should appear in reports or logs.

If there is no authorized Cookie account or Edge/Chromium is unavailable,
project research --full-text must report UNAVAILABLE, not a successful
full-text fetch and not an Open Access fallback.

## 5. Run the real Project Run

Use an existing Project Run ID, current Project Profile and existing Pipeline
state database. Example:

~~~powershell
python -m pipeline_contracts.cli project research <PROJECT_RUN_ID> --state-db .pipeline\workflow.sqlite --output-root runs --project-profile .pipeline\project_profile.json --literature-config .pipeline\literature-acquisition.local.json --full-text
~~~

This runs metadata search first, then selects up to
max_full_text_candidates supported publisher records. It does not create a
new workflow or state database.

For actual Data_analysis Artifact registration, also supply the existing
--integration-factory module:function and
--data-analysis-project-root <existing-project-root>. The factory must
return the real Data_analysis API object. The local file paths are not accepted
as proof of registration. The Pipeline verifies Artifact ID, registration
SHA-256 and resolved-file SHA-256 before reporting REGISTERED.

Without that existing API, expect LOCAL_UNREGISTERED. This is a valid
degraded mode, not a failed download and not a fake Artifact ID.

## 6. Inspect physical output

Inspect:

- runs/<project-run>/literature_acquisition/acquisition_report.json
- runs/<project-run>/literature_acquisition/raw/
- runs/<project-run>/literature_acquisition/source_packages/<doi-key>/01_preprocessing/
- the latest scientific_research/<dossier-id>/decision_dossier.json
- the latest scientific_research/<dossier-id>/decision_dossier.md

For each acquired paper, verify:

1. The original MAIN PDF is physically present and opens in a PDF reader.
2. Its SHA-256 in the report and Source Package matches the local file.
3. The page count equals the count shown by a PDF reader.
4. SI, when discovered, is physically present; ZIP/DOCX/PDF type is correct.
5. If SI is absent, MAIN remains in the package and the status is
   FULL_TEXT_ONLY or PARTIAL, depending on the ResearchPlan dependency.
6. The package contains main_analysis.md, si_analysis.md, page_text/,
   extracted_tables/, extracted_figures/, supplementary/, source_files/,
   evidence_index.json and PREPROCESSING_QC_REPORT.md.
7. The original MAIN/SI file SHA-256 values are preserved under source_files/;
   preprocessing did not overwrite the downloads.
8. Each page/table/figure evidence item retains source SHA-256 and its page,
   table or figure locator.
9. Any ArtifactRef names a real Data_analysis Artifact ID whose resolved bytes
   have the same SHA-256. If registration failed or was not configured, the
   report says LOCAL_UNREGISTERED and evidence contains no fake Artifact ID.
10. Figure/image entries say NOT_PERFORMED for visual interpretation. The
    existence of a crop is not a scientific interpretation.

Scanned pages must be listed in QC as warnings. There is no OCR in this stage.
An unavailable GROBID service must result in UNAVAILABLE_FALLBACK and
PyMuPDF fallback, not a failure to identify the source PDF as readable.

## 7. Verify isolation and cleanup

After the run:

- Confirm no Pipeline literature CDP browser process remains.
- Confirm temporary pipeline-literature-cdp-* directories have been removed.
- Confirm the user's normal Edge profile and normal Edge sessions were not
  modified or logged out.
- Confirm Cookie JSON files remain in their local Cookie directory and are
  absent from git status, Acquisition Reports, Dossiers and Artifact
  registrations.
- Confirm the report contains public publisher URLs, not tokenized WebVPN
  proxy URLs.

If a browser process/profile remains, stop further runs and preserve only
non-secret diagnostics (PID, timestamp, process image name, temporary-profile
directory name with no Cookie data) for review.

## 8. Acceptance record

Record the Project Run ID, Pipeline commit SHA, publisher, DOI, retrieval
status, MAIN/SI physical paths, MAIN/SI SHA-256, page count, Source Package ID
and SHA-256, preprocessing QC status, Artifact registration status and
Evidence IDs. Do not include Cookie account filenames or contents, proxy
tokens, session headers or unpublished paper files in the acceptance record.

This runbook does not authorize model approval, scientific decision approval,
CP2K/HPC execution or any calculation launch.
