# Scientific Reasoning & Literature Decision Engine

The research command is a stage in the existing Project Run lifecycle. It reads
the Frozen DOCX Manifest, Project Profile, available Planning Bundle and
historical DecisionRecords, then creates immutable JSON/Markdown Decision
Dossiers under the Project Run output directory.

## Commands

```bash
computation-pipeline project research <PROJECT_RUN_ID> --state-db <workflow.sqlite> --output-root <runs> --project-profile <profile.json>
computation-pipeline project decisions <PROJECT_RUN_ID> --state-db <workflow.sqlite> --output-root <runs>
computation-pipeline project approve-decision <PROJECT_RUN_ID> --decision-id <id> --option-id <id> --approved-by <name> --rationale "<reason>" --state-db <workflow.sqlite> --output-root <runs>
```

`project research` does not require the optional PaperQA2 package, an LLM key
or a paid API. The default provider selection is bounded OpenAlex + Crossref;
biomedical context additionally selects Europe PMC. Search queries, URLs with
credentials redacted, page counts, retrieval limits, errors and shortfalls are
persisted. A provider's empty result is not interpreted as proof of no literature.

A retrieved abstract is not full text. Europe PMC JATS full text is labelled
only after a body is present and extracted. Restricted or metadata-only responses
remain explicitly restricted/metadata-only. DOI/title mismatches and retraction
metadata are retained as warnings/status fields.

The optional existing-host adapter is supplied through the repository's
existing `module:function` integration factory, returning a `skill_executor`.
It is invoked only with `--allow-external-ai`. The callback contract is:
`executor(skill_name=..., instructions=..., task=..., payload=...) -> mapping`.
Pass `--allow-external-ai` to enable it. Local PaperQA2 excerpts are filtered
from the callback evidence matrix unless `--allow-local-evidence-to-external-ai`
is also supplied. Pipeline does not create another Agent runtime. External text is untrusted and
cannot issue commands or mutate lifecycle state. The upstream
`literature-review` skill is quarantined due to the upstream security report's
CRITICAL/3-findings designation; it is never loaded into a prompt.

PaperQA2 is optional and pinned in `paperqa2.lock.json` to release tag `v2026.08.12` (commit `57e89f7223b0960d5ee5ea048c69e3c47e088572`, Apache-2.0, Python `>=3.11`). Install `requirements-paperqa2.txt` only when wanted.
Provide `paperqa2.llm`, `paperqa2.summary_llm`, `paperqa2.embedding`, and any provider config in the integration/profile. For local inference, configure LiteLLM `api_base` to the existing local service. The PaperQA tool-selection Agent is pinned to the same configured `llm` and `llm_config`; PaperQA hosted-model/embedding defaults are not used. No model, key or remote endpoint is inferred. Explicit
consent is required before selected local documents are submitted for
PaperQA2 processing.

All Decision Dossiers remain PROPOSED / PENDING. Approving an option writes a
DecisionRecord in the existing WorkflowStore SQLite ledger and starts a new
Project Run revision with that decision applied only to its declared
`field_path`. Prior runs and immutable bundles are retained. The existing
model-approval, CalculationPlan freeze, real preflight and Workflow gates are
unchanged.
