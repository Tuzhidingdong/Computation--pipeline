# Scientific Reasoning & Literature Decision Engine

## Lifecycle integration

The engine extends the existing ScientificIntent → ResearchPlan → PlanningBundle and ProjectPipeline lifecycle. It does not create a second Agent Runtime, WorkflowStore, Artifact Store, Decision database, evidence registry, or generic execution engine. Dossier JSON/Markdown files live under the Project Run output root; research dossier records and scientific DecisionRecords live in the existing WorkflowStore SQLite database.

Normal user flow:
1. project start retains the Frozen DOCX and creates a Project Run.
2. project plan compiles the base immutable Scientific Planning Bundle.
3. project research classifies issues, source-resolves unique facts, records Pipeline interpretation defects, and researches only genuine scientific decisions.
4. project decisions displays the immutable JSON/Markdown Decision Dossier.
5. project approve-decision records the user's selection and compiles a child Project Run revision.
6. Continue only through the existing Model Approval, CalculationPlan freeze, Real Preflight, and Workflow lifecycle gates.

The parent Manifest, Planning Bundle, Frozen DOCX, and CalculationPlan are not rewritten. Automatic source resolutions and user-approved choices generate new Project Run revisions. Only the exact covered field is changed/removed from the child compiler's unresolved inputs; unrelated blockers remain.

## Issue classification and authority

- SOURCE_RESOLVED: a unique source claim with stable Evidence IDs and a paragraph/table/page locator is backed by the Frozen DOCX SHA, or an applicable prior user-approved DecisionRecord provides a unique selected value. The engine records the exact resolution and compiles a new revision without asking the user again.
- PIPELINE_INTERPRETATION_ISSUE: parser/transcription/field mapping, Profile schema, Artifact, runtime, resource, or other software/configuration interpretation defects. They are not packaged as scientific decisions. The engine preserves diagnostics; it does not self-modify its own code.
- GENUINE_SCIENTIFIC_DECISION: a scientific/methodological question remains unresolved after source and prior-decision reconciliation. These alone enter literature research and option assessment.

Unknown non-scientific configuration gaps do not default to science. When two source claims conflict, the engine does not auto-resolve them.

## Research and evidence provenance

Search routing is bounded and discipline-aware:
- Multidisciplinary: OpenAlex + Crossref.
- Biomedical: Europe PMC + OpenAlex + Crossref.
- Physics/computational/materials/mathematics: arXiv + OpenAlex + Crossref.

It reuses the selected upstream Paper Lookup paginator, OpenAlex abstract reconstructor, arXiv Atom parser, and JATS-to-text parser. Search URLs are credential-redacted. Queries, providers, call times, counts, page reconciliation, network errors, rate limits, no-result responses, and pagination shortfalls are recorded. No paid API credential is mandatory.

Records are deduplicated by DOI/PMID/arXiv ID and title. Possible preprint/published-version records with distinct identifiers are linked rather than silently collapsed. DOI/title identity is cross-checked against Crossref when possible. Crossref correction/retraction relations, provider retraction flags, publication type, and access status are preserved. A missing retraction flag is not proof that the article has never been retracted or corrected.

Europe PMC full text counts only when a JATS article body is retrieved and extracted. Metadata-only, restricted, unavailable, abstract-only and local PaperQA2 full-text-indexed documents have different statuses. The optional PaperQA2 plugin extracts source-linked contexts from caller-selected local files; it does not fetch arbitrary external URLs or upload private project inputs without explicit consent.

Evidence attributes are kept distinct: publication/retraction state, study design, method applicability, direct system applicability, evidence polarity, and independence. Unassessed dimensions remain NOT_ASSESSED. Citation count, journal impact factor and PaperQA retrieval relevance are not scientific quality scores. No unsupported composite numerical ranking is generated.

Without an evidence-assessment host, support/challenge polarity remains UNASSESSED, and the engine abstains from a recommendation. If the configured host returns assessments, option-specific evidence IDs and both supporting and challenging results are preserved. Conflicting evidence is grouped, not erased.

## Upstream skills and licenses

K-Dense repository: https://github.com/K-Dense-AI/scientific-agent-skills

Pinned commit: c21d13b3cc2894680229ba9959a53281acb9200e. The five selected upstream Skill files and five reusable Paper Lookup scripts are included under pipeline_contracts/scientific_planning/_vendor/kdense/, with MIT license, Git blob SHA and SHA-256 records in upstream-lock.json.

- paper-lookup 2.4 — enabled; the upstream 2026-11-23 scan reports SAFE / 0 findings.
- hypothesis-generation 2.4 — enabled; SAFE / 0 findings.
- scientific-critical-thinking 1.5 — enabled; SAFE / 0 findings.
- scientific-brainstorming 1.4 — enabled; SAFE / 0 findings.
- literature-review 1.11 — quarantined; the same upstream security report labels it CRITICAL with 3 findings. It is retained for audit and license traceability, but it is never loaded into a host prompt.

The upstream scan is self-reported, not independent certification. Enabled Skill instructions are still external reference data, and all returned paper, abstract, web and Skill content is untrusted. Pipeline does not run embedded commands or tool instructions.

PaperQA2 is optional and pinned separately in paperqa2.lock.json to paper-qa==2026.8.12, release commit 57e89f7223b0960d5ee5ea048c69e3c47e088572, Apache-2.0, Python >=3.11. The plugin uses the existing LiteLLM-compatible provider configuration; the caller must provide llm, summary_llm, and embedding. The PaperQA tool-selection Agent is bound to the configured llm/llm_config, rather than PaperQA's hosted default. No model service or API key is created by Pipeline. Missing package/provider settings are an explicit unavailable/degraded status and do not block the baseline literature workflow.

## Existing Agent/Skill host boundary

The inspected Planning Core has no generic Skill execution runtime. The implementation uses the existing load_integration_factory (module:function) boundary and accepts an optional skill_executor callback. The callback receives one allow-listed Skill's hash-verified instructions and structured evidence payload, and must return JSON data. It is used only with --allow-external-ai. Pipeline does not create a new Agent Runtime, invoke shell tools, or allow the callback to approve decisions or change lifecycle state. The literature-review Skill is never passed to the callback.

Public search APIs receive query terms derived from structured research scope; they are not sent the Frozen DOCX, unpublished source documents, raw Artifacts, or local Evidence Packages. Passing local files to PaperQA2 requires --allow-paperqa2-processing. Passing project context/public literature to an external Skill host requires --allow-external-ai. PaperQA2 local excerpts are excluded from that host payload unless --allow-local-evidence-to-external-ai is separately supplied.

## CLI

Normal sequence: project start → project plan → project research → project decisions → explicit project approve-decision.

Example research:

    computation-pipeline project research PROJECT_RUN_ID --project-profile profile.json --state-db .pipeline/workflow.sqlite --output-root runs

Example approval:

    computation-pipeline project approve-decision PROJECT_RUN_ID --decision-id DECISION_ID --option-id OPTION_ID --approved-by Reviewer --rationale 'Scientific rationale' --state-db .pipeline/workflow.sqlite --output-root runs

Research Dossiers remain PROPOSED / PENDING. The approval command accepts only a schema-valid option from the Project Profile or an explicitly enabled host Skill executor. It records approver, timestamp, choice, rationale, Dossier SHA, Evidence IDs and source references in the existing SQLite ledger, then recompiles a new Project Run. It does not approve the model, freeze a CalculationPlan, clear unrelated blockers or start a calculation.