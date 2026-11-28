"""Convert preprocessed Source Packages into explicit, page/table/figure Evidence.

Extracted images are indexed as assets only. No visual interpretation or scientific
claim is inferred by the preprocessing stage.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..models import EvidenceRef


def _stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:20]}"


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _artifact(registration: Mapping[str, Any], key: str) -> dict | None:
    found = (registration.get("by_relative_path") or {}).get(key)
    if isinstance(found, Mapping) and found.get("artifact_id") and found.get("verified") is True:
        ref = found.get("artifact_ref")
        if isinstance(ref, Mapping) and ref.get("artifact_id"):
            return dict(ref)
        return None
    return None


def _source_artifacts(registration: Mapping[str, Any], *, doc_type: str,
                      relative_path: str | None = None) -> list[dict[str, Any]]:
    candidates = []
    if relative_path:
        item = _artifact(registration, relative_path)
        if item:
            candidates.append(item)
    role = "MAIN_PDF" if doc_type == "MAIN" else "SI_SOURCE"
    item = _artifact(registration, role)
    if item and all(item["artifact_id"] != x["artifact_id"] for x in candidates):
        candidates.append(item)
    return candidates


def source_package_evidence(
    acquisition_report: Mapping[str, Any],
    *,
    literature_records: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Produce evidence rows from Source Package JSON already registered in the Run."""
    record_by_doi = {
        str(item.get("doi") or "").casefold(): dict(item)
        for item in literature_records if isinstance(item, Mapping) and item.get("doi")
    }
    output: list[dict[str, Any]] = []
    for acquisition in acquisition_report.get("records", []):
        if not isinstance(acquisition, Mapping):
            continue
        package_path = acquisition.get("source_package_path")
        if not package_path:
            continue
        package_dir = Path(str(package_path)).expanduser().resolve()
        index_path = package_dir / "evidence_index.json"
        if not index_path.is_file():
            continue
        try:
            package = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        registration = acquisition.get("registration") or {}
        registration_status = str(
            acquisition.get("artifact_registration_status") or
            registration.get("status") or "LOCAL_UNREGISTERED"
        )
        package_id = str(acquisition.get("source_package_id") or package.get("paper_id") or "")
        doi = str(acquisition.get("doi") or package.get("metadata", {}).get("doi") or "")
        paper_record = record_by_doi.get(doi.casefold(), {})
        paper_record_id = str(paper_record.get("record_id") or acquisition.get("record_id") or
                               _stable_id("paper-record", doi or package_id))
        metadata = package.get("metadata") or {}
        inventory = package.get("inventory") or {}
        main = inventory.get("main_pdf") or {}
        si_inputs = list(inventory.get("source_supplementary_files") or
                         inventory.get("supplementary_files") or [])
        source_by_filename = {str(main.get("filename") or Path(str(main.get("path") or "")).name): main}
        for item in si_inputs:
            source_by_filename[str(item.get("filename") or Path(str(item.get("path") or "")).name)] = item
        for item in inventory.get("supplementary_files", []) or []:
            filename = str(item.get("filename") or Path(str(item.get("path") or "")).name)
            source_by_filename[filename] = item

        common = {
            "paper_record_id": paper_record_id,
            "title": str(paper_record.get("title") or metadata.get("title") or ""),
            "authors": list(paper_record.get("authors") or []),
            "year": paper_record.get("year") or metadata.get("publication_year"),
            "doi": doi or None,
            "pmid": paper_record.get("pmid"),
            "pmcid": paper_record.get("pmcid"),
            "arxiv_id": paper_record.get("arxiv_id"),
            "databases": ["publisher-full-text-acquisition", "deterministic-source-preprocessing"],
            "source_urls": [str(acquisition.get("source_url"))] if acquisition.get("source_url") else [],
            "publication_status": paper_record.get("publication_status") or "FULL_TEXT_ACQUIRED",
            "retraction_status": paper_record.get("retraction_status") or "NOT_RECHECKED_BY_HARVESTER",
            "correction_status": paper_record.get("correction_status") or "NOT_RECHECKED_BY_HARVESTER",
            "publication_reliability": "NOT_ASSESSED",
            "study_design": "NOT_ASSESSED",
            "method_applicability": "NOT_ASSESSED",
            "direct_applicability": "NOT_ASSESSED",
            "independence": "NOT_ASSESSED",
            "polarity": "UNASSESSED",
            "claim": None,
            "claim_assessments": [],
            "conflict_group_id": None,
            "source_package_id": package_id,
            "source_package_sha256": acquisition.get("source_package_sha256"),
            "artifact_registration_status": registration_status,
            "artifact_registration_mock_only": bool(registration.get("mock_only")),
            "source_package_processing_status": package.get("processing_summary", {}).get("status"),
            "si_acquisition_status": acquisition.get("status"),
            "si_dependency_status": acquisition.get("si_dependency_status"),
            "limitations": [
                "Preprocessing is deterministic. It did not perform OCR, visual interpretation, or claim assessment.",
            ],
            "boundary_conditions": [],
        }

        for page in package.get("pages", []):
            doc_type = str(page.get("doc_type") or "MAIN")
            source_filename = str(page.get("source_file") or "")
            source = source_by_filename.get(source_filename) or (
                main if doc_type == "MAIN" else (si_inputs[0] if si_inputs else {})
            )
            source_sha = str(page.get("source_sha256") or source.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha):
                continue
            text = "\n\n".join(
                _text(block.get("text"))
                for block in page.get("blocks", [])
                if isinstance(block, Mapping) and _text(block.get("text"))
            )
            is_scanned = bool(page.get("is_scanned"))
            if not text and not is_scanned:
                continue
            artifacts = _source_artifacts(
                registration, doc_type=doc_type,
                relative_path=str(source.get("relative_path") or source.get("path") or "") or None,
            )
            locator = {"kind": "page", "value": f"{doc_type} page {page.get('page_number')}"}
            output.append({
                **common,
                "evidence_id": _stable_id("fulltext-page", {
                    "doi": doi, "source_sha256": source_sha,
                    "doc_type": doc_type, "page_number": page.get("page_number"),
                }),
                "evidence_type": "FULL_TEXT_PAGE",
                "doc_type": doc_type,
                "source_sha256": source_sha,
                "source_content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
                "full_text_sha256": source_sha,
                "excerpt": text[:12000],
                "locator": locator,
                "page_number": int(page.get("page_number") or 0),
                "page_bbox": None,
                "access_status": "SCANNED_PAGE_NO_OCR" if is_scanned else "PREPROCESSED_FULL_TEXT",
                "visual_interpretation_status": "NOT_APPLICABLE",
                "source_file": source_filename,
                "local_source_path": source.get("path"),
                "artifact_refs": artifacts,
                "source_artifact_ids": [item["artifact_id"] for item in artifacts],
                "artifact_registration_status": registration_status,
                "limitations": common["limitations"] + (
                    ["This page appears scanned/has insufficient extractable text; OCR was not performed."]
                    if is_scanned else []
                ),
            })

        # SI DOCX paragraphs/headings and equation text are full-text evidence too.
        # The original DOCX SHA and file-level locator are retained; this is not OCR.
        for si_item in inventory.get("supplementary_files", []):
            if str(si_item.get("format") or "").upper() != "DOCX":
                continue
            source_sha = str(si_item.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha):
                continue
            filename = str(si_item.get("filename") or "")
            stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem).strip("._") or "source"
            clean_path = package_dir / "supplementary" / stem / "si_cleaned.md"
            if not clean_path.is_file():
                # Some SI ZIP members carry a prefixed unpacked directory name.
                matches = list((package_dir / "supplementary").glob("*/si_cleaned.md"))
                if len(matches) == 1:
                    clean_path = matches[0]
            if clean_path.is_file():
                raw_text = clean_path.read_text(encoding="utf-8", errors="replace")
                current_section = filename
                for paragraph_index, line in enumerate(raw_text.splitlines(), 1):
                    text = _text(line)
                    if not text or text.startswith("SHA256:"):
                        continue
                    if text.startswith("#"):
                        current_section = text.lstrip("# ").strip() or filename
                        continue
                    excerpt = text[:12000]
                    relative = clean_path.relative_to(package_dir).as_posix()
                    artifacts = _source_artifacts(registration, doc_type="SI", relative_path=relative)
                    output.append({
                        **common,
                        "evidence_id": _stable_id("si-docx-paragraph", {
                            "doi": doi, "source_sha256": source_sha, "paragraph": paragraph_index,
                            "text_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                        }),
                        "evidence_type": "SI_DOCX_PARAGRAPH",
                        "doc_type": "SI", "source_sha256": source_sha,
                        "source_content_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                        "full_text_sha256": source_sha, "excerpt": excerpt,
                        "locator": {"kind": "section", "value": f"{filename} — {current_section} — line {paragraph_index}"},
                        "page_number": None, "access_status": "SI_DOCX_TEXT_EXTRACTED",
                        "source_file": filename, "local_source_path": si_item.get("path"),
                        "artifact_refs": artifacts,
                        "source_artifact_ids": [item["artifact_id"] for item in artifacts],
                        "limitations": common["limitations"] + [
                            "DOCX paragraph/heading text was deterministically extracted from OOXML; scientific interpretation was not performed."
                        ],
                    })
            meta_path = (package_dir / "supplementary" / stem / "si_metadata.json")
            if meta_path.is_file():
                try:
                    si_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    si_meta = {}
                for equation_index, equation in enumerate(si_meta.get("equations") or [], 1):
                    equation_text = _text(equation)
                    if not equation_text:
                        continue
                    output.append({
                        **common,
                        "evidence_id": _stable_id("si-docx-equation", {
                            "doi": doi, "source_sha256": source_sha, "equation_index": equation_index,
                        }),
                        "evidence_type": "SI_DOCX_EQUATION", "doc_type": "SI",
                        "source_sha256": source_sha,
                        "source_content_sha256": hashlib.sha256(equation_text.encode("utf-8")).hexdigest(),
                        "full_text_sha256": source_sha, "excerpt": equation_text,
                        "locator": {"kind": "section", "value": f"{filename} — OOXML equation {equation_index}"},
                        "access_status": "SI_DOCX_EQUATION_EXTRACTED",
                        "source_file": filename, "local_source_path": si_item.get("path"),
                        "visual_interpretation_status": "NOT_APPLICABLE",
                        "artifact_refs": [], "source_artifact_ids": [],
                        "limitations": common["limitations"] + ["Equation text was extracted from OOXML math; its scientific meaning was not assessed."],
                    })

        for table in package.get("tables", []):
            doc_type = str(table.get("doc_type") or "MAIN")
            source_filename = str(table.get("source_file") or "")
            source = source_by_filename.get(source_filename) or (
                main if doc_type == "MAIN" else (si_inputs[0] if si_inputs else {})
            )
            source_sha = str(table.get("source_sha256") or source.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha):
                continue
            rows = table.get("rows") or []
            excerpt = json.dumps(rows, ensure_ascii=False)[:12000]
            csv_path = str(table.get("csv_file") or "")
            md_path = str(table.get("md_file") or "")
            artifacts = _source_artifacts(registration, doc_type=doc_type, relative_path=csv_path)
            if source.get("relative_path") or source.get("path"):
                artifacts.extend(_source_artifacts(
                    registration, doc_type=doc_type,
                    relative_path=str(source.get("relative_path") or source.get("path")),
                ))
            unique_artifacts = {item["artifact_id"]: item for item in artifacts}
            artifacts = list(unique_artifacts.values())
            output.append({
                **common,
                "evidence_id": _stable_id("fulltext-table", {
                    "doi": doi, "source_sha256": source_sha, "table_id": table.get("table_id"),
                }),
                "evidence_type": "NATIVE_TABLE",
                "doc_type": doc_type,
                "source_sha256": source_sha,
                "source_content_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "full_text_sha256": source_sha,
                "excerpt": (
                    f"{_text(table.get('label') or table.get('table_id'))}: "
                    f"{_text(table.get('caption'))}\n{excerpt}"
                ),
                "locator": {
                    "kind": "table",
                    "value": f"{doc_type} {table.get('table_id')} page {table.get('page_number')}",
                },
                "page_number": table.get("page_number"),
                "bbox": table.get("bbox"),
                "access_status": "NATIVE_TABLE_EXTRACTED",
                "source_file": source_filename,
                "local_source_path": source.get("path"),
                "table_csv_path": csv_path,
                "table_markdown_path": md_path,
                "artifact_refs": artifacts,
                "source_artifact_ids": [item["artifact_id"] for item in artifacts],
                "limitations": common["limitations"] + [
                    "Table extraction is deterministic and was not independently scientifically interpreted."
                ],
            })

        for figure in package.get("figures", []):
            doc_type = str(figure.get("doc_type") or "MAIN")
            source_filename = str(figure.get("source_file") or "")
            source = source_by_filename.get(source_filename) or (
                main if doc_type == "MAIN" else (si_inputs[0] if si_inputs else {})
            )
            source_sha = str(figure.get("source_sha256") or source.get("sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha):
                continue
            figure_id = str(figure.get("figure_id") or "")
            asset = next((
                item for item in package.get("media_assets", [])
                if isinstance(item, Mapping) and item.get("figure_id") == figure_id and
                item.get("doc_type") == doc_type
            ), None)
            relative = str(asset.get("relative_path")) if asset and asset.get("relative_path") else ""
            artifacts = _source_artifacts(registration, doc_type=doc_type, relative_path=relative)
            if source.get("relative_path") or source.get("path"):
                artifacts.extend(_source_artifacts(
                    registration, doc_type=doc_type,
                    relative_path=str(source.get("relative_path") or source.get("path")),
                ))
            artifacts = list({item["artifact_id"]: item for item in artifacts}.values())
            output.append({
                **common,
                "evidence_id": _stable_id("fulltext-figure", {
                    "doi": doi, "source_sha256": source_sha, "figure_id": figure_id,
                }),
                "evidence_type": "EXTRACTED_FIGURE_ASSET",
                "doc_type": doc_type,
                "source_sha256": source_sha,
                "source_content_sha256": str(asset.get("sha256")) if asset else None,
                "full_text_sha256": source_sha,
                "excerpt": _text(figure.get("caption")),
                "locator": {
                    "kind": "figure",
                    "value": f"{doc_type} {figure_id} page {figure.get('page_number')}",
                },
                "page_number": figure.get("page_number"),
                "bbox": figure.get("bbox"),
                "figure_id": figure_id,
                "figure_asset_path": relative,
                "figure_asset_sha256": asset.get("sha256") if asset else None,
                "visual_interpretation_status": "NOT_PERFORMED",
                "access_status": "FIGURE_ASSET_EXTRACTED_NOT_INTERPRETED",
                "source_file": source_filename,
                "local_source_path": source.get("path"),
                "artifact_refs": artifacts,
                "source_artifact_ids": [item["artifact_id"] for item in artifacts],
                "limitations": common["limitations"] + [
                    "Image extraction is not visual interpretation; no content or scientific conclusion is inferred from this figure."
                ],
            })

    # Index SI PDF embedded images, page composites and DOCX OOXML media even
    # when no caption/Figure object was available. Extraction is not interpretation.
    figure_asset_ids = {
        str(item.get("figure_id")) for item in package.get("figures", [])
        if isinstance(item, Mapping) and item.get("figure_id")
    }
    for asset in package.get("media_assets", []):
        if not isinstance(asset, Mapping) or asset.get("asset_type") not in {
            "embedded_image", "composite_figure", "page_render"
        }:
            continue
        if asset.get("figure_id") and str(asset.get("figure_id")) in figure_asset_ids:
            continue
        doc_type = str(asset.get("doc_type") or "SI")
        relative = str(asset.get("relative_path") or "")
        source_file = str(asset.get("source_file") or "")
        source = source_by_filename.get(source_file) or (
            main if doc_type == "MAIN" else (si_inputs[0] if si_inputs else {})
        )
        source_sha = str(asset.get("source_sha256") or source.get("sha256") or "")
        asset_sha = str(asset.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha) or not re.fullmatch(r"[0-9a-fA-F]{64}", asset_sha):
            continue
        refs = _source_artifacts(
            registration, doc_type=doc_type, relative_path=relative,
        )
        refs.extend(_source_artifacts(
            registration, doc_type=doc_type,
            relative_path=str(source.get("relative_path") or source.get("path") or "") or None,
        ))
        refs = list({item["artifact_id"]: item for item in refs}.values())
        output.append({
            **common,
            "evidence_id": _stable_id("extracted-media-asset", {
                "doi": doi, "source_sha256": source_sha, "asset_sha256": asset_sha,
                "asset_type": asset.get("asset_type"), "relative_path": relative,
            }),
            "evidence_type": "EXTRACTED_SI_MEDIA_ASSET" if doc_type == "SI" else "EXTRACTED_MAIN_MEDIA_ASSET",
            "doc_type": doc_type,
            "source_sha256": source_sha,
            "source_content_sha256": asset_sha,
            "full_text_sha256": source_sha,
            "excerpt": _text(asset.get("caption")),
            "locator": {
                "kind": "figure" if asset.get("asset_type") != "page_render" else "page",
                "value": f"{doc_type} {asset.get('asset_type')} page {asset.get('page_number') or 'unknown'}",
            },
            "page_number": asset.get("page_number"),
            "bbox": asset.get("bbox"),
            "asset_type": asset.get("asset_type"),
            "asset_path": relative,
            "asset_sha256": asset_sha,
            "visual_interpretation_status": "NOT_PERFORMED",
            "access_status": "MEDIA_ASSET_EXTRACTED_NOT_INTERPRETED",
            "source_file": source_file,
            "local_source_path": source.get("path"),
            "artifact_refs": refs,
            "source_artifact_ids": [item["artifact_id"] for item in refs],
            "limitations": common["limitations"] + [
                "The file was extracted and indexed only; no visual content or scientific claim has been interpreted."
            ],
        })

    # Persist the Pipeline's existing EvidenceRef contract whenever at least one
    # Data_analysis ArtifactRef is registered. LOCAL_UNREGISTERED rows have no ref.
    for item in output:
        artifact_refs = item.get("artifact_refs") or []
        if not artifact_refs:
            item["evidence_ref"] = None
            continue
        source_hashes = {
            str(ref["artifact_id"]): str(ref["sha256"])
            for ref in artifact_refs
            if ref.get("artifact_id") and ref.get("sha256")
        }
        evidence_ref = EvidenceRef(
            evidence_id=str(item["evidence_id"]),
            source_artifact_ids=tuple(source_hashes),
            source_hashes=source_hashes,
            source_locator=json.dumps(item.get("locator") or {}, ensure_ascii=False, sort_keys=True),
            contract_id="pipeline-literature-evidence-ref",
            contract_version="1.0",
        )
        item["evidence_ref"] = asdict(evidence_ref)
    return output
