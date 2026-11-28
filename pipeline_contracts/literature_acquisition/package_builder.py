"""Direct migration of chem-literature/core/preprocessing/pipeline.py.

Upstream: Tuzhidingdong/chem-literature@e099406adb689281c0337bcacc7868c3ccdbc438.
Pipeline-owned package orchestration only; no second workflow/state store is created.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import pymupdf
from docx import Document as validate_docx

from .source_preprocessor import SourcePreprocessor


SUPPORTED_DOCUMENTS = {".pdf", ".docx"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "paper")[:80]


def _resolve_input(value: Any, working_dir: Path) -> Path:
    path = Path(str(value).strip()).expanduser()
    return path.resolve() if path.is_absolute() else (working_dir / path).resolve()


def _output_path(value: str | Path, working_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (working_dir / path).resolve()


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_supported_zip_members(
    archive_path: Path,
    destination: Path,
    *,
    max_member_bytes: int,
    max_total_bytes: int,
    max_members: int = 250,
) -> Tuple[List[Path], List[str]]:
    """Extract only PDF/DOCX members, rejecting unsafe paths and oversized archives."""
    extracted: List[Path] = []
    unsupported: List[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > max_members:
                unsupported.append(
                    f"[archive member limit exceeded: {len(infos)} members, limit {max_members}]"
                )
                infos = infos[:max_members]
            supported_infos = [
                info for info in infos
                if Path(PurePosixPath(info.filename.replace("\\", "/")).name).suffix.lower() in SUPPORTED_DOCUMENTS
            ]
            total_declared = sum(max(0, info.file_size) for info in supported_infos)
            total_budget_exceeded = total_declared > max_total_bytes
            total_written = 0
            for index, info in enumerate(infos, start=1):
                raw_name = info.filename.replace("\\", "/")
                member = PurePosixPath(raw_name)
                suffix = Path(member.name).suffix.lower()
                if member.is_absolute() or ".." in member.parts or (member.parts and ":" in member.parts[0]):
                    unsupported.append(f"{info.filename} [unsafe archive path]")
                    continue
                if info.flag_bits & 0x1:
                    unsupported.append(f"{info.filename} [encrypted]")
                    continue
                if suffix not in SUPPORTED_DOCUMENTS:
                    unsupported.append(info.filename)
                    continue
                if info.file_size > max_member_bytes:
                    unsupported.append(f"{info.filename} [member size limit exceeded]")
                    continue
                if total_budget_exceeded or total_written + info.file_size > max_total_bytes:
                    unsupported.append(f"{info.filename} [archive extraction size limit exceeded]")
                    continue
                safe_filename = _safe_name(Path(member.name).name)
                target = destination / f"{index:04d}_{safe_filename}"
                try:
                    with archive.open(info, "r") as src, target.open("wb") as dst:
                        written = 0
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_member_bytes or total_written + written > max_total_bytes:
                                raise ValueError("actual uncompressed ZIP member exceeded configured limits")
                            dst.write(chunk)
                except Exception as exc:
                    target.unlink(missing_ok=True)
                    unsupported.append(f"{info.filename} [extraction failed: {exc}]")
                    continue
                valid_document = True
                try:
                    if suffix == ".pdf":
                        with target.open("rb") as handle:
                            valid_document = handle.read(5) == b"%PDF-"
                        if valid_document:
                            with pymupdf.open(str(target)) as pdf_document:
                                valid_document = (not pdf_document.needs_pass and len(pdf_document) > 0)
                    elif suffix == ".docx":
                        with zipfile.ZipFile(target) as document:
                            valid_document = "word/document.xml" in document.namelist()
                        if valid_document:
                            validate_docx(str(target))
                except Exception:
                    valid_document = False
                if not valid_document:
                    target.unlink(missing_ok=True)
                    unsupported.append(f"{info.filename} [file extension/content mismatch]")
                    continue
                actual_size = target.stat().st_size
                if actual_size > max_member_bytes or total_written + actual_size > max_total_bytes:
                    target.unlink(missing_ok=True)
                    unsupported.append(f"{info.filename} [actual extraction size limit exceeded]")
                    continue
                total_written += actual_size
                extracted.append(target)
    except (OSError, zipfile.BadZipFile) as exc:
        unsupported.append(f"[invalid or unreadable ZIP: {exc}]")
    return extracted, unsupported


def _make_input_record(path: Path) -> dict:
    return {
        "path": str(path),
        "filename": path.name,
        "format": path.suffix.lower().lstrip(".").upper(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _update_package_and_qc(
    package_dir: Path,
    package: dict,
    *,
    original_si_records: List[dict],
    archive_records: List[dict],
    unsupported_members: List[str],
    has_original_si: bool,
) -> dict:
    package.setdefault("inventory", {})
    package["inventory"]["source_supplementary_files"] = original_si_records
    package["inventory"]["source_archives"] = archive_records
    for item in package["inventory"].get("supplementary_files", []):
        path = Path(str(item.get("path") or ""))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(package_dir.resolve())
            item["relative_path"] = resolved.relative_to(package_dir.resolve()).as_posix()
            item["path"] = item["relative_path"]
        except (OSError, ValueError):
            pass
    package.setdefault("metadata", {})["has_si"] = bool(has_original_si)

    summary = package["processing_summary"]
    warnings = summary.setdefault("warnings", [])
    if unsupported_members:
        warnings.append(
            "Some SI archive members/formats were preserved or recorded but not parsed: "
            + "; ".join(unsupported_members[:30])
        )
    if summary.get("scanned_pages_detected", 0):
        status = "WARNING_SCANNED_PAGES"
    elif unsupported_members or any(
        item.get("processing_status") == "PRESERVED_NOT_PARSED"
        for item in package["inventory"].get("supplementary_files", [])
    ):
        status = "PARTIAL_SI_UNSUPPORTED"
    elif not has_original_si:
        status = "PARTIAL_NO_SI"
    else:
        status = "COMPLETE"
    summary["status"] = status

    (package_dir / "evidence_index.json").write_text(
        json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    qc_path = package_dir / "PREPROCESSING_QC_REPORT.md"
    with qc_path.open("a", encoding="utf-8") as handle:
        handle.write("\n## Chem-Literature integration notes\n")
        handle.write(f"- Original SI files: {len(original_si_records)}\n")
        handle.write(f"- Source archives preserved: {len(archive_records)}\n")
        handle.write(f"- Unsupported/unparsed SI members: {len(unsupported_members)}\n")
        if unsupported_members:
            for item in unsupported_members[:30]:
                handle.write(f"- Not parsed: {item}\n")
        handle.write("- Archive extraction is restricted to PDF/DOCX members; other members remain in the original archive.\n")
    return package



def _cache_package_valid(package_dir: Path, package: dict, main_path: Path,
                         si_path: Path | None) -> bool:
    """A matching input signature is insufficient: every cached asset is re-hashed."""
    try:
        from .schemas import validate_source_package
        validate_source_package(package)
        input_manifest = _read_json(package_dir / "PREPROCESSING_INPUTS.json") or {}
        stored_inputs = input_manifest.get("inputs") or []
        # The directly migrated corpus preprocessor stores {"main": ..., "si": ...};
        # the single-package builder stores a list. Validate both persisted formats.
        if isinstance(stored_inputs, Mapping):
            input_records = [
                value for key, value in stored_inputs.items()
                if key in {"main", "si"} and isinstance(value, Mapping)
            ]
        elif isinstance(stored_inputs, list):
            input_records = [value for value in stored_inputs if isinstance(value, Mapping)]
        else:
            return False
        if not input_records:
            return False
        for input_record in input_records:
            input_path = Path(str(input_record.get("path") or ""))
            if (not input_path.is_file() or input_path.stat().st_size != input_record.get("size_bytes")
                    or _sha256(input_path) != input_record.get("sha256")):
                return False
        inventory = package.get("inventory") or {}
        if inventory.get("main_pdf", {}).get("sha256") != _sha256(main_path):
            return False
        if si_path is not None:
            si_hashes = {
                item.get("sha256") for item in
                (inventory.get("source_supplementary_files") or inventory.get("supplementary_files") or [])
            }
            si_hashes.update(item.get("sha256") for item in (inventory.get("source_archives") or []))
            if _sha256(si_path) not in si_hashes:
                return False
        for asset in package.get("media_assets", []):
            relative = Path(str(asset.get("relative_path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                return False
            asset_path = package_dir / relative
            if not asset_path.is_file() or _sha256(asset_path) != asset.get("sha256"):
                return False
        for relative_dir in ("page_text", "extracted_tables", "extracted_figures", "supplementary"):
            if not (package_dir / relative_dir).is_dir():
                return False
        return (package_dir / "main_analysis.md").is_file() and (package_dir / "si_analysis.md").is_file()
    except Exception:
        return False



def write_failed_source_package(
    *, doi: str, title: str, output_dir: str | Path,
    main_pdf: str | Path | None, supplementary_files: Sequence[str | Path] = (),
    error: str, paper_id: str | None = None,
) -> dict[str, Any]:
    """Persist a schema-valid FAILED Source Package without claiming extracted content."""
    from .contracts import doi_storage_id
    from .schemas import validate_source_package

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    package_id = paper_id or doi_storage_id(doi)
    main = Path(main_pdf).expanduser().resolve() if main_pdf else None
    main_exists = bool(main and main.is_file() and not main.is_symlink())
    main_hash = _sha256(main) if main_exists and main else hashlib.sha256(b"").hexdigest()
    main_size = main.stat().st_size if main_exists and main else 0
    si_inventory = []
    for value in supplementary_files:
        path = Path(value).expanduser().resolve()
        if path.is_file() and not path.is_symlink():
            si_inventory.append(_make_input_record(path))
    for directory in (
        "page_text", "extracted_tables", "extracted_tables/table_images",
        "extracted_figures/MAIN", "extracted_figures/SI", "supplementary",
    ):
        (output / directory).mkdir(parents=True, exist_ok=True)
    package = {
        "package_version": "1.1.0",
        "paper_id": package_id,
        "metadata": {
            "doi": doi, "title": title, "has_si": bool(si_inventory),
            "publication_year": None,
        },
        "inventory": {
            "main_pdf": {
                "path": str(main) if main else "",
                "sha256": main_hash, "size_bytes": main_size, "page_count": 0,
            },
            "si_pdf": None,
            "supplementary_files": si_inventory,
            "source_supplementary_files": si_inventory,
        },
        "pages": [], "tables": [], "figures": [], "si_references": [], "media_assets": [],
        "processing_summary": {
            "total_main_pages": 0, "total_si_pages": 0,
            "total_tables_detected": 0, "total_figures_detected": 0,
            "total_si_references": 0, "scanned_pages_detected": 0,
            "images_extracted": 0, "grobid_status": "NOT_RUN",
            "warnings": [str(error)[:2000]],
            "status": "FAILED",
        },
        "failure": {"error": str(error)[:2000], "failed_at": datetime.now(timezone.utc).isoformat()},
    }
    # Root schema has additionalProperties=false; keep failure detail in warnings/QC,
    # while the status and diagnostics remain within the established contract.
    package.pop("failure", None)
    validate_source_package(package)
    (output / "main_analysis.md").write_text(
        f"# Main Analysis: {title}\nDOI: {doi}\n\nPreprocessing failed.\n",
        encoding="utf-8",
    )
    (output / "si_analysis.md").write_text(
        f"# Supporting Information Analysis: {title}\nDOI: {doi}\n\n"
        "No SI text was asserted as extracted.\n",
        encoding="utf-8",
    )
    (output / "evidence_index.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "PREPROCESSING_QC_REPORT.md").write_text(
        "# Source Preprocessing QC Report\n\n"
        f"- Paper ID: {package_id}\n- Status: FAILED\n"
        f"- MAIN exists: {main_exists}\n- SI files physically present: {len(si_inventory)}\n"
        f"- Failure: {str(error)[:2000]}\n"
        "- OCR was not performed; image interpretation was not performed.\n",
        encoding="utf-8",
    )
    return package


def build_source_package(
    *, main_pdf: str | Path, supplementary_files: List[str | Path] | Tuple[str | Path, ...] = (),
    output_dir: str | Path, doi: str, title: str = "",
    publication_year: int | None = None, config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build/reuse one atomic MAIN/SI package, preserving inputs and isolating failures."""
    from .contracts import doi_storage_id

    opts = dict(config or {})
    main = Path(main_pdf).expanduser().resolve()
    si_paths = [Path(item).expanduser().resolve() for item in supplementary_files]
    package_root = Path(output_dir).expanduser().resolve()
    paper_id = doi_storage_id(doi)
    final_dir = package_root / paper_id / "01_preprocessing"
    final_dir.parent.mkdir(parents=True, exist_ok=True)

    input_records = []
    for path in [main, *si_paths]:
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"source input is missing or not a regular file: {path.name}")
        input_records.append(_make_input_record(path))
    signature_payload = {
        "inputs": input_records,
        "grobid_enabled": bool(opts.get("grobid_enabled", False)),
        "grobid_url": str(opts.get("grobid_url") or ""),
        "grobid_timeout_seconds": int(opts.get("grobid_timeout_seconds", 30)),
        "max_zip_member_bytes": int(opts.get("max_zip_member_bytes", 100 * 1024 * 1024)),
        "max_zip_total_bytes": int(opts.get("max_zip_total_bytes", 512 * 1024 * 1024)),
        "max_zip_members": int(opts.get("max_zip_members", 250)),
        "figure_dpi": int(opts.get("figure_dpi", 200)),
        "table_dpi": int(opts.get("table_dpi", 200)),
    }
    signature = hashlib.sha256(json.dumps(signature_payload, sort_keys=True).encode("utf-8")).hexdigest()
    input_manifest = final_dir / "PREPROCESSING_INPUTS.json"
    existing = _read_json(final_dir / "evidence_index.json")
    previous = _read_json(input_manifest)
    if (previous and previous.get("signature") == signature and existing
            and (final_dir / "PREPROCESSING_QC_REPORT.md").is_file()
            and _cache_package_valid(final_dir, existing, main, si_paths[0] if len(si_paths) == 1 else None)):
        return {
            "status": existing["processing_summary"]["status"], "action": "REUSED_UNCHANGED",
            "paper_id": paper_id, "package_dir": str(final_dir),
            "package": existing, "input_signature": signature,
        }

    staging_parent = package_root / f".{paper_id}.{uuid.uuid4().hex}.staging"
    staging_parent.mkdir(parents=True, exist_ok=False)
    staging_dir = staging_parent / "processed"
    record = {
        "doi": doi, "title": title, "year": publication_year,
        "local_pdf_path": str(main),
        "local_si_info": str(si_paths[0]) if len(si_paths) == 1 else "",
    }
    try:
        if len(si_paths) > 1:
            # Preserve each original SI file; parse supported formats through a bounded ZIP.
            combined = staging_parent / "source_supplementary_inputs.zip"
            with zipfile.ZipFile(combined, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, si_path in enumerate(si_paths, 1):
                    archive.write(si_path, arcname=f"source_{index:04d}_{si_path.name}")
            record["local_si_info"] = str(combined)
        import pandas as pd
        frame = pd.DataFrame([record])
        def _run_preprocessing(frame_to_process):
            return preprocess_paired_corpus(
                frame_to_process, working_dir=staging_parent, preprocessed_dir=staging_dir,
                grobid_enabled=bool(opts.get("grobid_enabled", False)),
                grobid_url=opts.get("grobid_url"),
                grobid_timeout_seconds=int(opts.get("grobid_timeout_seconds", 30)),
                max_zip_member_bytes=int(opts.get("max_zip_member_bytes", 100 * 1024 * 1024)),
                max_zip_total_bytes=int(opts.get("max_zip_total_bytes", 512 * 1024 * 1024)),
                max_zip_members=int(opts.get("max_zip_members", 250)),
            )

        result = _run_preprocessing(frame)
        row = result.iloc[0].to_dict()
        si_preprocessing_error = ""
        if row.get("preprocessing_status") == "FAILED" and si_paths:
            # SI parse/extraction failure is isolated from a readable MAIN paper.
            # Retry MAIN-only and retain every original SI byte in source_files/.
            si_preprocessing_error = str(row.get("preprocessing_error") or "SI preprocessing failed")
            main_only = frame.copy()
            main_only.loc[main_only.index[0], "local_si_info"] = ""
            result = _run_preprocessing(main_only)
            row = result.iloc[0].to_dict()
        produced = Path(str(row.get("preprocessing_path") or ""))
        produced = produced if produced.is_absolute() else (staging_parent / produced).resolve()
        package = _read_json(produced / "evidence_index.json")
        if row.get("preprocessing_status") == "FAILED" or not package:
            raise RuntimeError(str(row.get("preprocessing_error") or "SourcePreprocessor did not produce a valid MAIN package"))
        if si_preprocessing_error:
            package["metadata"]["has_si"] = True
            package["processing_summary"].setdefault("warnings", []).append(
                "SI was physically available but could not be safely preprocessed; its original bytes are preserved in source_files/: "
                + si_preprocessing_error[:1500]
            )
            package["processing_summary"]["status"] = (
                "WARNING_SCANNED_PAGES"
                if package["processing_summary"].get("scanned_pages_detected", 0)
                else "PARTIAL_SI_UNSUPPORTED"
            )
            with (produced / "PREPROCESSING_QC_REPORT.md").open("a", encoding="utf-8") as handle:
                handle.write("\n## SI preprocessing failure — MAIN retained\n")
                handle.write(f"- SI inputs supplied: {len(si_paths)}\n")
                handle.write(f"- Diagnostic: {si_preprocessing_error[:1500]}\n")
                handle.write("- Original SI bytes are preserved; SI text/evidence was not fabricated.\n")
        # Bundle immutable physical copies of original MAIN and SI files so the
        # Source Package remains self-contained; original download paths are retained
        # only as provenance and are never modified by preprocessing.
        source_files = produced / "source_files"
        source_files.mkdir(parents=True, exist_ok=True)
        main_copy = source_files / f"MAIN_{doi_storage_id(doi)}.pdf"
        shutil.copy2(main, main_copy)
        if _sha256(main_copy) != _sha256(main):
            raise RuntimeError("copied MAIN source bytes failed SHA-256 verification")
        main_record = {
            **_make_input_record(main),
            "original_path": str(main),
            "path": main_copy.relative_to(produced).as_posix(),
            "relative_path": main_copy.relative_to(produced).as_posix(),
            "filename": main.name,
        }
        package.setdefault("inventory", {})["main_pdf"].update({
            "path": main_record["path"],
            "filename": main.name,
            "original_path": str(main),
            "sha256": main_record["sha256"],
            "size_bytes": main_record["size_bytes"],
        })
        package["inventory"]["source_main_file"] = main_record
        copied_si = []
        for index, si_path in enumerate(si_paths, 1):
            suffix = si_path.suffix.lower()
            destination = source_files / f"SI_{index:03d}_{doi_storage_id(si_path.name)}{suffix}"
            shutil.copy2(si_path, destination)
            if _sha256(destination) != _sha256(si_path):
                raise RuntimeError(f"copied SI source bytes failed SHA-256 verification: {si_path.name}")
            copied = {
                **_make_input_record(si_path),
                "original_path": str(si_path),
                "path": destination.relative_to(produced).as_posix(),
                "relative_path": destination.relative_to(produced).as_posix(),
                "filename": si_path.name,
            }
            copied_si.append(copied)
            package["media_assets"].append({
                "asset_id": f"SOURCE_FILE_{index:04d}",
                "doc_type": "SI",
                "asset_type": "source_file",
                "source_file": si_path.name,
                "source_sha256": copied["sha256"],
                "relative_path": copied["relative_path"],
                "sha256": copied["sha256"],
                "extraction_method": "original_source_file_copy",
                "page_number": None,
                "bbox": None,
                "figure_id": None,
                "table_id": None,
                "caption": None,
                "width": None,
                "height": None,
                "mime_type": None,
                "is_tiny_icon": False,
            })
        package["inventory"]["source_supplementary_files"] = copied_si
        for item in package["inventory"].get("source_archives", []):
            relative = str(item.get("relative_path") or "")
            if relative:
                item["original_path"] = str(item.get("path") or "")
                item["path"] = relative
        si_pdf = package["inventory"].get("si_pdf")
        if isinstance(si_pdf, dict):
            original_name = Path(str(si_pdf.get("path") or "")).name
            match = next((item for item in copied_si if item.get("filename") == original_name), None)
            if match:
                si_pdf["original_path"] = match["original_path"]
                si_pdf["path"] = match["relative_path"]
        # Rebase original preprocessor inventory paths to the copied package files.
        si_lookup = {item["filename"]: item for item in copied_si}
        for item in package["inventory"].get("supplementary_files", []):
            match = si_lookup.get(str(item.get("filename") or ""))
            if match:
                item["original_path"] = match["original_path"]
                item["path"] = match["relative_path"]
                item["relative_path"] = match["relative_path"]
        package["metadata"]["has_si"] = bool(si_paths)
        package["processing_summary"]["status"] = (
            "WARNING_SCANNED_PAGES"
            if si_preprocessing_error and package["processing_summary"].get("scanned_pages_detected", 0)
            else "PARTIAL_SI_UNSUPPORTED"
            if si_preprocessing_error
            else row["preprocessing_status"]
        )
        row["preprocessing_status"] = package["processing_summary"]["status"]
        package.setdefault("media_assets", []).append({
            "asset_id": "SOURCE_FILE_MAIN",
            "doc_type": "MAIN",
            "asset_type": "source_file",
            "source_file": main.name,
            "source_sha256": main_record["sha256"],
            "relative_path": main_record["relative_path"],
            "sha256": main_record["sha256"],
            "extraction_method": "original_source_file_copy",
            "page_number": None,
            "bbox": None,
            "figure_id": None,
            "table_id": None,
            "caption": None,
            "width": None,
            "height": None,
            "mime_type": "application/pdf",
            "is_tiny_icon": False,
        })
        from .schemas import validate_source_package
        validate_source_package(package)
        (produced / "evidence_index.json").write_text(
            json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        input_path = produced / "PREPROCESSING_INPUTS.json"
        input_path.write_text(json.dumps({
            "signature": signature,
            "inputs": input_records,
            "settings": {key: value for key, value in signature_payload.items() if key != "inputs"},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        qc_path = produced / "PREPROCESSING_QC_REPORT.md"
        with qc_path.open("a", encoding="utf-8") as handle:
            handle.write("\n## Pipeline acquisition provenance\n")
            handle.write(f"- MAIN SHA-256: {input_records[0]['sha256']}\n")
            handle.write(f"- Original SI file count: {len(si_paths)}\n")
            for item in input_records[1:]:
                handle.write(f"- SI {item['filename']}: SHA-256 {item['sha256']}\n")
            handle.write("- OCR was not performed; scanned pages are flagged. Image extraction is not visual interpretation.\n")

        # Atomic directory promotion: the previous package stays intact until
        # the replacement is fully written. Roll back if promotion fails.
        backup = final_dir.with_name(final_dir.name + f".{uuid.uuid4().hex}.previous")
        had_previous = final_dir.exists()
        if had_previous:
            os.replace(final_dir, backup)
        try:
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced, final_dir)
        except Exception:
            if had_previous and backup.exists() and not final_dir.exists():
                os.replace(backup, final_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        final_package = _read_json(final_dir / "evidence_index.json")
        return {
            "status": final_package["processing_summary"]["status"],
            "action": "PROCESSED", "paper_id": paper_id,
            "package_dir": str(final_dir), "package": final_package,
            "input_signature": signature,
        }
    except Exception as exc:
        if final_dir.exists() and (final_dir / "evidence_index.json").is_file():
            raise RuntimeError(f"new preprocessing failed; prior valid package retained: {type(exc).__name__}: {exc}") from exc
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def preprocess_paired_corpus(
    paired_records: pd.DataFrame,
    *,
    working_dir: str | Path = ".",
    preprocessed_dir: str | Path = "runs/preprocessed",
    grobid_enabled: bool = False,
    grobid_url: Optional[str] = None,
    grobid_timeout_seconds: int = 30,
    max_zip_member_bytes: int = 100 * 1024 * 1024,
    max_zip_total_bytes: int = 512 * 1024 * 1024,
    max_zip_members: int = 250,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> pd.DataFrame:
    """Preprocess paired records independently and return rows with QC/status columns.

    Required columns: doi, local_pdf_path, local_si_info. Paths may be absolute
    or relative to working_dir. One paper failure does not stop the remaining corpus.
    """
    results = paired_records.copy()
    columns = {
        "preprocessing_path": "",
        "preprocessing_status": "PENDING",
        "preprocessing_action": "",
        "preprocessing_error": "",
        "preprocessing_qc_report": "",
        "preprocessing_grobid_status": "",
    }
    for name, default in columns.items():
        if name not in results.columns:
            results[name] = default

    root = Path(working_dir).expanduser().resolve()
    preprocess_root = _output_path(preprocessed_dir, root)

    for index, row in results.iterrows():
        doi = str(row.get("doi", "") or "").strip()
        paper_id = _safe_name(doi or str(row.get("title", "")) or f"paper_{index}")
        main_value = str(row.get("local_pdf_path", "") or "").strip()
        si_value = str(row.get("local_si_info", "") or "").strip()
        package_dir = preprocess_root / paper_id / "01_preprocessing"

        try:
            package_display = str(package_dir.relative_to(root)) if package_dir.is_relative_to(root) else str(package_dir)
            qc_display = str((package_dir / "PREPROCESSING_QC_REPORT.md").relative_to(root)) \
                if (package_dir / "PREPROCESSING_QC_REPORT.md").is_relative_to(root) \
                else str(package_dir / "PREPROCESSING_QC_REPORT.md")
            record = {
                "doi": doi,
                "preprocessing_path": package_display,
                "preprocessing_status": "FAILED",
                "preprocessing_action": "",
                "preprocessing_error": "",
                "preprocessing_qc_report": qc_display,
                "preprocessing_grobid_status": "",
            }

            if not main_value:
                raise FileNotFoundError("A source package requires a local MAIN PDF; SI is optional.")
            main_path = _resolve_input(main_value, root)
            si_path = _resolve_input(si_value, root) if si_value else None
            if not main_path.is_file():
                raise FileNotFoundError(f"MAIN PDF not found: {main_path}")
            if si_path is not None and not si_path.is_file():
                raise FileNotFoundError(f"SI source file not found: {si_path}")

            original_si_record = _make_input_record(si_path) if si_path is not None else None
            signature_payload = {
                "main": _make_input_record(main_path),
                "si": original_si_record,
                "grobid_enabled": bool(grobid_enabled),
                "grobid_url": grobid_url or "",
                "grobid_timeout_seconds": int(grobid_timeout_seconds),
                "max_zip_member_bytes": int(max_zip_member_bytes),
                "max_zip_total_bytes": int(max_zip_total_bytes),
            }
            signature = hashlib.sha256(
                json.dumps(signature_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            input_manifest = package_dir / "PREPROCESSING_INPUTS.json"
            previous = _read_json(input_manifest)
            existing_package = _read_json(package_dir / "evidence_index.json")
            if (
                previous
                and previous.get("signature") == signature
                and existing_package
                and (package_dir / "PREPROCESSING_QC_REPORT.md").is_file()
                and _cache_package_valid(package_dir, existing_package, main_path, si_path)
            ):
                package = existing_package
                record["preprocessing_action"] = "REUSED_UNCHANGED"
            else:
                if package_dir.exists():
                    shutil.rmtree(package_dir)
                package_dir.mkdir(parents=True, exist_ok=True)
                unpack_root = package_dir / "source_si_unpacked"
                unpack_root.mkdir(parents=True, exist_ok=True)

                supplementary_inputs: List[Path] = []
                unsupported_members: List[str] = []
                archive_records: List[dict] = []
                if si_path is not None and si_path.suffix.lower() == ".zip":
                    archive_copy_dir = package_dir / "source_archives"
                    archive_copy_dir.mkdir(parents=True, exist_ok=True)
                    archive_copy = archive_copy_dir / _safe_name(si_path.name)
                    shutil.copy2(si_path, archive_copy)
                    archive_records.append({
                        **original_si_record,
                        "relative_path": archive_copy.relative_to(package_dir).as_posix(),
                    })
                    extracted, unsupported_members = _extract_supported_zip_members(
                        si_path,
                        unpack_root,
                        max_member_bytes=max_zip_member_bytes,
                        max_total_bytes=max_zip_total_bytes,
                        max_members=max_zip_members,
                    )
                    supplementary_inputs.extend(extracted)
                    if not extracted and not unsupported_members:
                        unsupported_members.append("[ZIP contained no supported PDF/DOCX SI documents]")
                elif si_path is not None:
                    supplementary_inputs.append(si_path)

                year_raw = str(row.get("year", "") or "").strip()
                publication_year = int(year_raw) if year_raw.isdigit() else None
                processor = SourcePreprocessor(
                    grobid_url=grobid_url,
                    use_grobid=bool(grobid_enabled),
                    grobid_timeout=int(grobid_timeout_seconds),
                )
                package = processor.process(
                    main_pdf=main_path,
                    supplementary_files=supplementary_inputs,
                    output_dir=package_dir,
                    paper_id=paper_id,
                    doi=doi,
                    title=str(row.get("title", "") or ""),
                    publication_year=publication_year,
                )
                package = _update_package_and_qc(
                    package_dir,
                    package,
                    original_si_records=[original_si_record] if original_si_record else [],
                    archive_records=archive_records,
                    unsupported_members=unsupported_members,
                    has_original_si=bool(original_si_record),
                )
                input_manifest.write_text(
                    json.dumps(
                        {"signature": signature, "inputs": signature_payload},
                        indent=2, ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            record["preprocessing_status"] = package["processing_summary"]["status"]
            record["preprocessing_grobid_status"] = package["processing_summary"].get("grobid_status", "")
            record["preprocessing_action"] = record["preprocessing_action"] or "PROCESSED"
        except Exception as exc:
            package_display = str(package_dir.relative_to(root)) if package_dir.is_relative_to(root) else str(package_dir)
            package_dir.mkdir(parents=True, exist_ok=True)
            qc_failure = package_dir / "PREPROCESSING_QC_REPORT.md"
            if not qc_failure.exists():
                qc_failure.write_text(
                    "# Source Preprocessing QC Report\n\n"
                    f"- Paper ID: {paper_id}\n- Status: FAILED\n"
                    f"- Error: {type(exc).__name__}: {exc}\n"
                    "- No OCR or visual interpretation was performed.\n",
                    encoding="utf-8",
                )
            record = {
                "doi": doi,
                "preprocessing_path": package_display,
                "preprocessing_status": "FAILED",
                "preprocessing_action": "FAILED",
                "preprocessing_error": f"{type(exc).__name__}: {exc}",
                "preprocessing_qc_report": str(package_dir / "PREPROCESSING_QC_REPORT.md"),
                "preprocessing_grobid_status": "",
            }

        for key, value in record.items():
            if key in results.columns:
                results.at[index, key] = value
        if progress_callback:
            progress_callback(record)

    return results
