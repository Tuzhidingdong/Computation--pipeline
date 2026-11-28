"""Optional PaperQA2 integration; no package/provider is mandatory."""
from __future__ import annotations

import hashlib
import importlib.metadata
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


def query_local_paperqa2(
    *, documents: Sequence[str | Path], question: str,
    settings: Mapping[str, Any], consent_external_processing: bool = False,
) -> dict[str, Any]:
    """Index explicitly selected local papers with caller-configured provider.

    PaperQA2 supports local/provider model adapters through LiteLLM. No default
    model or credential is selected here. External processing is disabled unless
    the caller explicitly opts in; point settings at a local service for offline
    operation.
    """
    if not consent_external_processing:
        return {"status": "SKIPPED_PRIVACY_CONSENT_REQUIRED"}
    if sys.version_info < (3, 11):
        return {"status": "UNAVAILABLE", "reason": "PaperQA2 v5+ requires Python 3.11+."}
    try:
        version = importlib.metadata.version("paper-qa")
        from packaging.version import Version
        if Version(version).major < 5:
            return {"status": "UNAVAILABLE", "reason": f"paper-qa {version} is older than v5."}
        from paperqa import Docs, Settings
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    allowed = {
        "llm", "summary_llm", "embedding", "llm_config", "summary_llm_config",
        "embedding_config",
    }
    config = {key: value for key, value in dict(settings).items() if key in allowed and value is not None}
    if not config.get("llm") or not config.get("summary_llm") or not config.get("embedding"):
        return {
            "status": "UNAVAILABLE",
            "reason": "Explicit llm, summary_llm and embedding model settings are required; PaperQA provider defaults are not used.",
        }
    # PaperQA defaults its tool-selection Agent to a hosted OpenAI model even
    # when llm/summary_llm are customised. Bind it to the caller's existing
    # configured LLM/provider to avoid silently starting an unrelated service.
    config["agent"] = {
        "agent_llm": config["llm"],
        "agent_llm_config": config.get("llm_config"),
    }
    paths = [Path(item).expanduser().resolve() for item in documents]
    missing = [str(item) for item in paths if not item.is_file()]
    if missing:
        return {"status": "UNAVAILABLE", "reason": "Selected local paper(s) do not exist.", "missing": missing}
    try:
        docs = Docs()
        document_hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        for path in paths:
            docs.add(str(path))
        response = docs.query(question, settings=Settings(**config))
        chunks = []
        for context in list(getattr(response, "contexts", []) or [])[:100]:
            text_object = getattr(context, "text", None)
            document = getattr(text_object, "doc", None)
            doc_name = str(getattr(document, "docname", "") or "")
            metadata = getattr(text_object, "__pydantic_extra__", None) or {}
            chunks.append({
                "context_id": str(getattr(context, "id", "") or ""),
                "document_name": Path(doc_name).name if doc_name else "selected-local-document",
                "document_sha256": document_hashes.get(Path(doc_name).name),
                "document_content_hash": getattr(document, "content_hash", None),
                "citation": str(getattr(document, "citation", "") or ""),
                "chunk_name": str(getattr(text_object, "name", "") or ""),
                "excerpt": str(getattr(context, "context", "") or ""),
                "chunk_text": str(getattr(text_object, "text", "") or "")[:12000],
                "page": metadata.get("page") or metadata.get("page_num"),
                # Retrieval relevance only; never a scientific quality score.
                "retrieval_relevance_score": getattr(context, "score", None),
            })
        # PaperQA output and excerpts are untrusted research data. They can be
        # summarized/cited but cannot run tools or mutate Pipeline state.
        formatted = str(getattr(response, "formatted_answer", "") or response)
        return {"status": "COMPLETED", "paper_qa_version": version,
                "document_count": len(paths), "question": question,
                "answer_untrusted_text": formatted,
                "references_untrusted_text": str(getattr(response, "references", "") or ""),
                "evidence_chunks": chunks,
                "model_configuration_keys": sorted(config.keys())}
    except Exception as exc:
        return {"status": "DEGRADED", "paper_qa_version": version,
                "reason": f"{type(exc).__name__}: {exc}"}
