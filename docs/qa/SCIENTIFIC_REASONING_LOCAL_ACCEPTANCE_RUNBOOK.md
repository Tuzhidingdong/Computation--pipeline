# Scientific Reasoning & Literature Engine — Local Acceptance Runbook

This runbook is generic. Use a copy of the real Frozen DOCX and Project Profile as external QA inputs. Do not place their scientific parameters, citations, conclusions, file contents or identifiers in shared Skill files, test fixtures, generic prompts, or production code.

## Preparation

1. Work in a disposable Pipeline workspace with a separate workflow.sqlite and output directory. Record the input Frozen DOCX and Project Profile SHA-256.
2. Complete the existing Project Review / Evidence Review lifecycle before compiling/recompiling the Planning Bundle. Do not bypass existing review gates.
3. Ensure scientific_planning.intent in the Project Profile describes the research question, object, comparison, target conclusion and observables. Where meaningful alternatives are already known, declare them under scientific_planning.scientific_decisions[] with stable option IDs, values, pros/cons/risks, scope, prerequisites and downstream impacts.
4. First run without PaperQA2 and without API keys. Public OpenAlex/Crossref and the selected Europe PMC/arXiv path must work without paid credentials.
5. Do not run Model Approval, Real Preflight, CP2K, HPC, or Workflow execution during the scientific-research acceptance.

## Normal CLI sequence

Run project start with the Frozen DOCX, then project review, project plan, project research, and project decisions. Use the same state database and output root for all commands. Supply the real Project Profile path to project plan and project research.

The JSON and Markdown Dossier are written under the Project Run output root in scientific_research/<dossier_id>/. The SQLite ledger retains the Dossier ID, SHA-256 and report paths.

## Acceptance checks

### 1. Source authority and automatic resolution

Use a Frozen DOCX containing at least one extracted claim that maps to an unresolved field and has a unique value with a paragraph/table/page locator.

Pass conditions:
- the issue is SOURCE_RESOLVED, with exact value, Evidence ID, document SHA and source locator;
- it does not create a PROPOSED scientific decision;
- a new immutable Project Run revision is created;
- the child ResearchPlan contains a SELECTED_FROM_EVIDENCE DecisionRecord with the same value and source EvidenceRefs;
- the parent Manifest, Frozen DOCX and Planning Bundle hashes are unchanged;
- all unrelated blockers remain.

Also test two conflicting source claims for the same field. The engine must not select one or clear the conflict.

### 2. Prior decision reconciliation

Approve one declared option through the normal approval command, then run research on its child Project Run. The matching inherited DecisionRecord must be resolved from history without asking for the same decision again. Verify the original Dossier SHA, Evidence IDs and source locators remain traceable.

### 3. Pipeline interpretation defects

Use a known parser, transcription, field mapping, Profile schema, Artifact, runtime or resource reconciliation defect. It must be classified as PIPELINE_INTERPRETATION_ISSUE, keep its diagnostic, and not become a scientific approval question. The engine reports this software defect; it does not self-edit or execute a patch. Apply any correction as a separately reviewed, targeted Pipeline change and rerun from a new Project Run where required.

### 4. Genuine scientific decisions and literature

Use a genuinely undefined scientific/methodological field that cannot be uniquely resolved from source evidence or prior decisions.

Pass conditions:
- structured scientific context is built before queries;
- only genuine science issues trigger literature search;
- chosen databases fit the discipline; no blanket all-provider fan-out;
- queries, provider, timestamps, redacted URLs, counts, pagination, errors, rate limits and no-result statuses are recorded;
- DOI/title identity, PMID/arXiv IDs and preprint/published relationships are retained;
- retraction/correction status and limitations are explicit;
- abstract, JATS full text, restricted, metadata-only, unavailable and PaperQA2 local-full-text statuses are distinguished;
- Evidence Matrix records source IDs, hashes and page/section/figure/table locators where the source provides them;
- support, challenge, mixed results and conflict groups are all retained when returned by an enabled evidence-assessment host;
- study design, publication reliability, method applicability, direct applicability and independence remain distinct fields;
- without a trusted assessor or enough evidence, polarity remains UNASSESSED and recommendation is withheld.

Do not compare LLM output with citation counts or impact factors as a proxy for scientific quality.

### 5. Privacy, optional adapters and failure degradation

- With no PaperQA2 package installed, the normal research flow still completes.
- With PaperQA2 requested but no consent, it returns SKIPPED_PRIVACY_CONSENT_REQUIRED.
- With explicit consent but no package or provider configuration, PaperQA2 is UNAVAILABLE; existing OpenAlex/Crossref/Europe PMC research continues.
- Network failure, HTTP 429, malformed API response and page-count shortfall are visible in retrieval logs and do not destroy the existing Planning Bundle.
- No API key is present; verify no paid Parallel service is required.
- No Frozen DOCX, raw Artifact, private data package or unpublished source file is sent to a public search API or external Skill host.

### 6. Approval and downstream gates

Before approval:
- every decision stays PROPOSED / PENDING;
- models_approved, scientific_decisions_approved, blockers_cleared, and calculations_started remain false;
- no DecisionRecord is marked APPROVED.

After a user explicitly selects a declared option:
- the existing WorkflowStore contains one DecisionRecord with approver, timestamp, selected option/value, rationale, Dossier SHA and Evidence IDs;
- a new Project Run revision is created; the old Run and Dossier remain;
- only the covered field is applied; unrelated blockers remain;
- child Planning Bundle, ResearchPlan and downstream Method/Model/QC objects retain source hashes and the DecisionRecord reference;
- Model Approval, CalculationPlan freeze, Real Preflight and Workflow execution remain independently blocked until their own existing authorization steps.

### 7. Data_analysis Artifact missing

Repeat the research test with the Data_analysis Artifact resolver absent or a required structure Artifact unavailable. Literature research must still produce the Dossier for independent scientific questions. The downstream model/calculation path must remain blocked and must not fabricate an Artifact, Analysis Run or Evidence Package.

## QA evidence to archive

Record branch and commit SHA, local input file hashes, CLI commands and exit codes, test results, Dossier JSON/Markdown and hashes, SQLite record IDs, retrieval logs and any API degradation. Keep real-project QA reports outside generic Skill directories and source-controlled fixtures.