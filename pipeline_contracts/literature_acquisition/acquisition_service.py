"""Native Pipeline literature acquisition coordinator.

Owns no workflow, state database, or Artifact Store. It orchestrates the directly
migrated harvester/preprocessor and delegates Artifact registration to the
existing caller-supplied Data_analysis API.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Mapping, Sequence

from ..models import ArtifactRef
from .contracts import (
    AcquisitionConfig, AcquisitionStatus, ArtifactRegistrationStatus,
    LiteratureTarget, decide_si_requirement, doi_storage_id, now_utc, sha256_file,
)
from .package_builder import build_source_package, write_failed_source_package
from .paper_harvester import PaperHarvester
from .publisher_registry import detect_publisher, publisher_support_matrix
from .vpn_session import (
    BrowserSessionError, BrowserUnavailable, PublisherAccessBlocked,
    VpnBrowserSession, discover_cookie_accounts, resolve_browser_executable,
)


class LiteratureAcquisitionService:
    def __init__(
        self,
        config: AcquisitionConfig,
        *,
        data_analysis_api: Any = None,
        data_analysis_project_root: str | Path | None = None,
        session_factory: Callable[..., Any] = VpnBrowserSession,
        harvester_factory: Callable[..., PaperHarvester] = PaperHarvester,
        package_builder: Callable[..., dict] = build_source_package,
        account_discoverer: Callable[[str | Path], list[dict[str, str]]] = discover_cookie_accounts,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.SystemRandom().uniform,
    ):
        self.config = config
        self.data_analysis_api = data_analysis_api
        self.data_analysis_project_root = (
            Path(data_analysis_project_root).expanduser().resolve()
            if data_analysis_project_root else None
        )
        self.session_factory = session_factory
        self.harvester_factory = harvester_factory
        self.package_builder = package_builder
        self.account_discoverer = account_discoverer
        self.sleeper = sleeper
        self.random_uniform = random_uniform
        self._blocked_publishers: set[str] = set()
        self._blocked_lock = threading.RLock()

    def _output_root(self, run_root: str | Path) -> Path:
        configured = Path(self.config.output_dir).expanduser()
        if not configured.is_absolute():
            configured = Path(run_root).expanduser().resolve() / configured
        result = configured.resolve()
        result.mkdir(parents=True, exist_ok=True)
        return result

    @staticmethod
    def _safe_record(target: LiteratureTarget, publisher_key: str | None,
                     status: str, diagnostic: str | None = None) -> dict[str, Any]:
        return {
            "doi": target.doi, "record_id": target.record_id, "title": target.title,
            "publisher": publisher_key, "status": status,
            "requires_si": target.requires_si,
            "si_requirement_basis": target.si_requirement_basis,
            "diagnostics": ([{"stage": "ACQUISITION", "status": status,
                              "diagnostic": diagnostic}] if diagnostic else []),
        }

    def _register_artifacts(
        self, *, package_dir: Path, package: Mapping[str, Any], main_pdf: Path,
        si_file: Path | None, target: LiteratureTarget, run_root: Path,
    ) -> dict[str, Any]:
        api = self.data_analysis_api
        project_root = self.data_analysis_project_root
        formats = dict(self.config.artifact_format_ids or {})
        if api is None or project_root is None or not project_root.is_dir():
            return {
                "status": ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value,
                "reason": "EXISTING_DATA_ANALYSIS_API_OR_PROJECT_ROOT_NOT_AVAILABLE",
                "artifacts": [], "by_relative_path": {},
            }
        if not hasattr(api, "register_derived_artifact") or not hasattr(api, "resolve_artifact_path"):
            return {
                "status": ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value,
                "reason": "EXISTING_DATA_ANALYSIS_API_DOES_NOT_EXPOSE_VERIFIED_ARTIFACT_REGISTRATION",
                "artifacts": [], "by_relative_path": {},
            }
        if not formats:
            return {
                "status": ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value,
                "reason": "DATA_ANALYSIS_ARTIFACT_FORMAT_IDS_NOT_CONFIGURED",
                "artifacts": [], "by_relative_path": {},
            }

        files: list[tuple[str, Path, str]] = [
            ("MAIN_PDF", main_pdf, self._format_key(main_pdf)),
            ("SOURCE_PACKAGE_INDEX", package_dir / "evidence_index.json", "json"),
            ("MAIN_ANALYSIS", package_dir / "main_analysis.md", "markdown"),
            ("SI_ANALYSIS", package_dir / "si_analysis.md", "markdown"),
            ("PREPROCESSING_QC", package_dir / "PREPROCESSING_QC_REPORT.md", "markdown"),
        ]
        if si_file is not None:
            files.append(("SI_SOURCE", si_file, self._format_key(si_file)))
        for path in sorted(package_dir.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(package_dir).as_posix()
            if relative in {
                "evidence_index.json", "main_analysis.md", "si_analysis.md",
                "PREPROCESSING_QC_REPORT.md", "PREPROCESSING_INPUTS.json",
            }:
                continue
            files.append((relative, path, self._format_key(path)))

        artifacts: list[dict[str, Any]] = []
        by_relative: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        mock_mode = False
        for role, path, format_key in files:
            if not path.is_file() or path.is_symlink():
                errors.append(f"{role}: expected file is missing or is a symlink")
                continue
            format_id = str(formats.get(format_key) or "")
            if not format_id:
                errors.append(f"{role}: Data_analysis format_id for {format_key!r} is not configured")
                continue
            before = sha256_file(path)
            try:
                result = api.register_derived_artifact(
                    str(project_root), str(path.resolve(strict=True)),
                    source_artifact_ids=[],
                    format_id=format_id,
                    provenance={
                        "component": "PipelineLiteratureAcquisition",
                        "source_repository": "Tuzhidingdong/chem-literature",
                        "source_commit": "e099406adb689281c0337bcacc7868c3ccdbc438",
                        "doi": target.doi, "paper_title": target.title,
                        "artifact_role": role, "source_sha256": before,
                        "project_run_root": str(run_root),
                    },
                )
                if not isinstance(result, Mapping) or not result.get("artifact_id") or not result.get("sha256"):
                    raise RuntimeError("Data_analysis did not return artifact_id and sha256")
                if str(result["sha256"]).lower() != before.lower():
                    raise RuntimeError("Data_analysis registration SHA-256 differs from local bytes")
                artifact_id = str(result["artifact_id"])
                resolved = Path(api.resolve_artifact_path(str(project_root), artifact_id)).resolve(strict=True)
                after = sha256_file(resolved)
                if after.lower() != before.lower():
                    raise RuntimeError("Data_analysis Artifact resolver returned different bytes")
                is_mock = bool(result.get("mock") or result.get("execution_mode") == "mock"
                               or artifact_id.startswith("mock-"))
                mock_mode = mock_mode or is_mock
                artifact_ref = ArtifactRef(
                    artifact_id=artifact_id,
                    sha256=before,
                    format_id=format_id,
                    media_type=__import__("mimetypes").guess_type(path.name)[0],
                    uri=(f"mock://data-analysis/{artifact_id}" if is_mock
                         else str(result.get("uri") or resolved.as_uri())),
                    storage_mode=str(result.get("storage_mode") or "managed"),
                    source_system=("Mock:Data_analysis" if is_mock else "Data_analysis"),
                    mock=is_mock,
                )
                artifact = {
                    "artifact_id": artifact_id,
                    "sha256": before,
                    "size_bytes": path.stat().st_size,
                    "format_id": format_id,
                    "uri": artifact_ref.uri,
                    "source_system": artifact_ref.source_system,
                    "artifact_ref": asdict(artifact_ref),
                    "verified": True,
                    "mock": is_mock,
                    "role": role,
                    "relative_path": path.relative_to(package_dir).as_posix()
                        if path.is_relative_to(package_dir) else None,
                    "local_path": str(path.resolve()),
                }
                artifacts.append(artifact)
                if artifact["relative_path"]:
                    by_relative[artifact["relative_path"]] = artifact
                if role in {"MAIN_PDF", "SI_SOURCE"}:
                    by_relative[role] = artifact
            except Exception as exc:
                errors.append(f"{role}: {type(exc).__name__}: {exc}")

        if errors and artifacts:
            status = ArtifactRegistrationStatus.PARTIAL.value
        elif errors:
            status = ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value
        else:
            status = ArtifactRegistrationStatus.REGISTERED.value
        return {
            "status": status, "reason": "; ".join(errors) if errors else None,
            "artifacts": artifacts, "by_relative_path": by_relative,
            "mock_only": mock_mode,
        }

    @staticmethod
    def _format_key(path: Path) -> str:
        suffix = path.suffix.casefold()
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".docx":
            return "docx"
        if suffix == ".zip":
            return "zip"
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix == ".json":
            return "json"
        if suffix == ".csv":
            return "csv"
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
            return "image"
        if suffix in {".txt", ".xml", ".tei"}:
            return "text"
        return "binary"

    def _process_target(self, target: LiteratureTarget, publisher, vpn,
                        harvester: PaperHarvester, output_root: Path,
                        run_root: Path) -> dict[str, Any]:
        resource_id = self.config.publisher_resource_ids.get(publisher.resource_key)
        if not self.config.portal_url or not resource_id:
            return self._safe_record(
                target, publisher.key, "UNAVAILABLE",
                "WEBVPN_PORTAL_URL_OR_PUBLISHER_RESOURCE_ID_NOT_CONFIGURED",
            )
        with self._blocked_lock:
            if publisher.key in self._blocked_publishers:
                return self._safe_record(
                    target, publisher.key, "UNAVAILABLE",
                    "PUBLISHER_COOLDOWN_AFTER_ACCESS_DENIAL_OR_RATE_LIMIT",
                )
        base = vpn.get_proxy_base(
            publisher.resource_key, resource_id=int(resource_id),
            portal_url=self.config.portal_url,
        )
        acquisition = harvester.acquire(
            asdict(target), publisher.key, vpn, base,
        )
        main_value = acquisition.get("main_pdf")
        if not main_value:
            return {**self._safe_record(
                target, publisher.key, acquisition.get("status") or "FAILED",
                "; ".join(str(x.get("diagnostic")) for x in acquisition.get("diagnostics", [])),
            ), "acquisition": acquisition}

        main_path = Path(main_value).resolve(strict=True)
        si_value = acquisition.get("si_file")
        si_path = (
            Path(si_value).resolve(strict=True)
            if acquisition.get("si_available") is True and si_value and Path(si_value).is_file()
            else None
        )
        record = {
            **acquisition,
            "doi": target.doi, "record_id": target.record_id,
            "title": target.title, "publisher": publisher.key,
            "requires_si": target.requires_si,
            "si_requirement_basis": target.si_requirement_basis,
            "si_dependency_status": (
                "SATISFIED" if not target.requires_si or si_path is not None else "MISSING_REQUIRED_SI"
            ),
            "registration": {
                "status": ArtifactRegistrationStatus.NOT_REQUESTED.value,
                "reason": "PREPROCESSING_DISABLED",
                "artifacts": [], "by_relative_path": {},
            },
        }
        if target.requires_si and si_path is None:
            record["status"] = "PARTIAL"
            record.setdefault("diagnostics", []).append({
                "stage": "SI_DEPENDENCY", "status": "MISSING_REQUIRED_SI",
                "diagnostic": "The ResearchPlan requires SI evidence; MAIN is retained but conclusions depending on SI must not be considered complete.",
            })

        if not self.config.preprocessing_enabled:
            record["source_package_status"] = "NOT_REQUESTED"
            record["artifact_registration_status"] = ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value
            if si_path is not None:
                record["si_dependency_status"] = "AVAILABLE_NOT_PREPROCESSED"
            if target.requires_si:
                record["si_dependency_status"] = "MISSING_REQUIRED_SI_EVIDENCE"
                record["status"] = "PARTIAL"
                record.setdefault("diagnostics", []).append({
                    "stage": "SI_DEPENDENCY", "status": "MISSING_REQUIRED_SI_EVIDENCE",
                    "diagnostic": "SI is required by the ResearchPlan but preprocessing was disabled; no SI evidence was produced.",
                })
            return record

        try:
            package_result = self.package_builder(
                main_pdf=main_path,
            supplementary_files=[si_path] if si_path is not None else [],
            output_dir=output_root / "source_packages",
            doi=target.doi, title=target.title, publication_year=target.year,
            config={
                "grobid_enabled": self.config.grobid_enabled,
                "grobid_url": self.config.grobid_url,
                "grobid_timeout_seconds": self.config.grobid_timeout_seconds,
                "max_zip_member_bytes": self.config.max_zip_member_bytes,
                "max_zip_total_bytes": self.config.max_zip_total_bytes,
                "max_zip_members": self.config.max_zip_members,
            },
            )
        except Exception as exc:
            failed_id = doi_storage_id(target.doi)
            # A failed refresh never overwrites a previously completed Source Package.
            failed_dir = (
                output_root / "source_packages" / failed_id / "failed_attempts" /
                f"attempt-{uuid.uuid4().hex}" / "01_preprocessing"
            )
            write_failed_source_package(
                doi=target.doi, title=target.title, output_dir=failed_dir,
                main_pdf=main_path, supplementary_files=[si_path] if si_path else [],
                error=f"{type(exc).__name__}: {exc}", paper_id=failed_id,
            )
            record.update({
                "status": "PARTIAL",
                "si_dependency_status": (
                    "MISSING_OR_UNPARSED_REQUIRED_SI" if target.requires_si
                    else "AVAILABLE_UNPARSED" if si_path is not None
                    else "MISSING_OPTIONAL_SI"
                ),
                "source_package_status": "FAILED",
                "source_package_id": failed_id,
                "source_package_path": str(failed_dir),
                "source_package_sha256": sha256_file(failed_dir / "evidence_index.json"),
                "artifact_registration_status": ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value,
                "registration": {
                    "status": ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value,
                    "reason": "PREPROCESSING_FAILED; package is local and no Artifact is claimed",
                    "artifacts": [], "by_relative_path": {},
                },
                "diagnostics": list(record.get("diagnostics", [])) + [{
                    "stage": "PREPROCESSING", "status": "FAILED",
                    "diagnostic": f"{type(exc).__name__}: {exc}",
                }],
            })
            return record
        package = package_result["package"]
        package_dir = Path(package_result["package_dir"]).resolve(strict=True)
        registration = self._register_artifacts(
            package_dir=package_dir, package=package, main_pdf=main_path,
            si_file=si_path, target=target, run_root=run_root,
        )
        # Physical SI presence alone is not evidence completeness. Only a readable
        # PDF page/table/figure or a parsed DOCX can satisfy the ResearchPlan dependency.
        si_items = list((package.get("inventory") or {}).get("supplementary_files") or [])
        parsed_docx = any(
            str(item.get("format") or "").upper() == "DOCX"
            and item.get("processing_status") == "PARSED"
            for item in si_items
        )
        readable_si_pages = any(
            page.get("doc_type") == "SI" and not page.get("is_scanned")
            and int(page.get("char_count") or 0) > 0
            for page in package.get("pages", [])
        )
        structured_si = any(
            item.get("doc_type") == "SI"
            for item in (package.get("tables", []) + package.get("figures", []))
        )
        si_parsed = bool(parsed_docx or readable_si_pages or structured_si)
        if si_path is not None and si_parsed:
            record["si_dependency_status"] = (
                "SATISFIED" if target.requires_si else "AVAILABLE_PARSED"
            )
        elif si_path is not None:
            record["si_dependency_status"] = (
                "MISSING_OR_UNPARSED_REQUIRED_SI" if target.requires_si else "AVAILABLE_UNPARSED"
            )
        record.update({
            "source_package_status": package_result["status"],
            "preprocessing_action": package_result["action"],
            "source_package_id": package_result["paper_id"],
            "source_package_path": str(package_dir),
            "source_package_sha256": sha256_file(package_dir / "evidence_index.json"),
            "source_package_counts": {
                "main_pages": package.get("processing_summary", {}).get("total_main_pages", 0),
                "si_pages": package.get("processing_summary", {}).get("total_si_pages", 0),
                "tables": package.get("processing_summary", {}).get("total_tables_detected", 0),
                "figures": package.get("processing_summary", {}).get("total_figures_detected", 0),
                "scanned_pages": package.get("processing_summary", {}).get("scanned_pages_detected", 0),
            },
            "registration": registration,
            "artifact_registration_status": registration["status"],
        })
        if package_result["status"] in {"FAILED", "PARTIAL_SI_UNSUPPORTED", "WARNING_SCANNED_PAGES"}:
            record["status"] = "PARTIAL" if main_path.is_file() else "FAILED"
        if record.get("si_dependency_status") in {
            "MISSING_REQUIRED_SI", "MISSING_OR_UNPARSED_REQUIRED_SI",
            "MISSING_REQUIRED_SI_EVIDENCE",
        }:
            record["status"] = "PARTIAL"
        return record

    def acquire(
        self, records: Sequence[Mapping[str, Any]], *, run_root: str | Path,
        context: Mapping[str, Any], profile: Mapping[str, Any] | None = None,
        enabled_override: bool = False, max_candidates: int | None = None,
        project_run_id: str | None = None,
    ) -> dict[str, Any]:
        root = Path(run_root).expanduser().resolve()
        output_root = self._output_root(root)
        enabled = bool(self.config.enabled or enabled_override)
        targets: list[tuple[LiteratureTarget, Any]] = []
        skipped: list[dict[str, Any]] = []

        for record in records:
            if not isinstance(record, Mapping):
                continue
            target = LiteratureTarget.from_record(record)
            if not target.doi:
                continue
            publisher = detect_publisher(record)
            if publisher is None:
                skipped.append(self._safe_record(
                    target, None, "NOT_IMPLEMENTED",
                    "NO_VALIDATED_PUBLISHER_ROUTE_FOR_RETRIEVED_SOURCE_METADATA",
                ))
                continue
            if not publisher.supported:
                skipped.append(self._safe_record(
                    target, publisher.key, "NOT_IMPLEMENTED",
                    f"{publisher.key.upper()}_DOWNLOADER_NOT_IMPLEMENTED",
                ))
                continue
            requires_si, basis = decide_si_requirement(self.config, context=context, profile=profile)
            target = replace(target, requires_si=requires_si, si_requirement_basis=basis)
            targets.append((target, publisher))

        limit = int(max_candidates or self.config.max_full_text_candidates)
        eligible = targets[:limit]
        for target, publisher in targets[limit:]:
            skipped.append(self._safe_record(
                target, publisher.key, "UNAVAILABLE", "MAX_FULL_TEXT_CANDIDATE_LIMIT_REACHED",
            ))

        report: dict[str, Any] = {
            "schema_version": "1.0",
            "project_run_id": project_run_id,
            "created_at": now_utc(),
            "source_repository": "Tuzhidingdong/chem-literature",
            "source_commit": "e099406adb689281c0337bcacc7868c3ccdbc438",
            "enabled": enabled,
            "configuration": self.config.report_settings(),
            "publisher_support_matrix": publisher_support_matrix(),
            "candidate_count": len(eligible),
            "records": list(skipped),
            "summary": {},
            "security": {
                "cookie_contents_logged": False,
                "cookie_contents_artifacted": False,
                "daily_browser_profile_used": False,
                "open_access_fallback_claimed": False,
            },
        }
        if not enabled:
            report["status"] = "SKIPPED_DISABLED"
            report["summary"] = {"processed": 0, "unavailable": 0, "not_implemented": len(skipped)}
            return self._write_report(output_root, report)
        if not eligible:
            report["status"] = "NOT_REQUIRED"
            report["summary"] = {"processed": 0, "unavailable": 0, "not_implemented": len(skipped)}
            return self._write_report(output_root, report)

        cookie_accounts = self.account_discoverer(self.config.cookie_dir)
        report["authorized_cookie_account_count"] = len(cookie_accounts)
        if not cookie_accounts:
            report["records"].extend(self._safe_record(
                target, publisher.key, "UNAVAILABLE",
                "NO_AUTHORIZED_WEBVPN_COOKIE_FOUND; OA_FALLBACK_NOT_IMPLEMENTED",
            ) for target, publisher in eligible)
            report["status"] = "UNAVAILABLE"
            report["summary"] = {"processed": 0, "unavailable": len(eligible),
                                 "not_implemented": len(skipped)}
            return self._write_report(output_root, report)

        browser = resolve_browser_executable(self.config.browser_executable)
        if not browser and self.session_factory is VpnBrowserSession:
            report["records"].extend(self._safe_record(
                target, publisher.key, "UNAVAILABLE",
                "EDGE_OR_CHROMIUM_EXECUTABLE_NOT_FOUND",
            ) for target, publisher in eligible)
            report["status"] = "UNAVAILABLE"
            report["summary"] = {"processed": 0, "unavailable": len(eligible),
                                 "not_implemented": len(skipped)}
            return self._write_report(output_root, report)

        worker_count = min(self.config.max_workers, len(cookie_accounts), len(eligible))
        accounts = cookie_accounts[:worker_count]
        buckets: list[list[tuple[LiteratureTarget, Any]]] = [[] for _ in accounts]
        for index, item in enumerate(eligible):
            buckets[index % worker_count].append(item)

        results: list[dict[str, Any]] = []
        def worker(account: Mapping[str, str], assigned: list[tuple[LiteratureTarget, Any]]) -> list[dict[str, Any]]:
            account_id = str(account["account_id"])
            harvested: list[dict[str, Any]] = []
            failures = 0
            harvester = self.harvester_factory(output_root / "raw" / account_id)
            try:
                with self.session_factory(
                    account["cookie_file"], config=self.config, account_id=account_id,
                    workspace_dir=output_root / "browser_sessions",
                ) as vpn:
                    for position, (target, publisher) in enumerate(assigned):
                        with self._blocked_lock:
                            is_blocked = publisher.key in self._blocked_publishers
                        if is_blocked:
                            harvested.append(self._safe_record(
                                target, publisher.key, "UNAVAILABLE",
                                "PUBLISHER_COOLDOWN_AFTER_ACCESS_DENIAL_OR_RATE_LIMIT",
                            ))
                            continue
                        if failures >= self.config.max_consecutive_failures:
                            harvested.append(self._safe_record(
                                target, publisher.key, "UNAVAILABLE",
                                f"ACCOUNT_COOLDOWN_AFTER_{failures}_CONSECUTIVE_FAILURES",
                            ))
                            continue
                        if position:
                            self.sleeper(self.random_uniform(
                                self.config.min_delay_seconds, self.config.max_delay_seconds
                            ))
                        try:
                            result = self._process_target(
                                target, publisher, vpn, harvester, output_root, root,
                            )
                            status = result.get("status")
                            if status in {"FAILED", "UNAVAILABLE", "NOT_IMPLEMENTED"}:
                                failures += 1
                            else:
                                failures = 0
                            for diagnostic in result.get("diagnostics", []):
                                if diagnostic.get("status") == "BLOCKED":
                                    with self._blocked_lock:
                                        self._blocked_publishers.add(publisher.key)
                            result["account_id"] = account_id
                            harvested.append(result)
                        except PublisherAccessBlocked as exc:
                            with self._blocked_lock:
                                self._blocked_publishers.add(publisher.key)
                            failures += 1
                            harvested.append({
                                **self._safe_record(target, publisher.key, "PARTIAL",
                                                    f"ACCESS_BLOCKED: {exc}"),
                                "account_id": account_id, "access_blocked": True,
                                "cooldown_seconds": self.config.cooldown_seconds,
                            })
                        except BrowserSessionError as exc:
                            # One bounded CDP/browser recovery; no repeated retries.
                            try:
                                if hasattr(vpn, "recover"):
                                    vpn.recover()
                                    result = self._process_target(
                                        target, publisher, vpn, harvester, output_root, root,
                                    )
                                    result["account_id"] = account_id
                                    result.setdefault("diagnostics", []).append({
                                        "stage": "CDP_RECOVERY", "status": "RECOVERED",
                                        "diagnostic": "The isolated CDP session recovered once.",
                                    })
                                    harvested.append(result)
                                    failures = 0 if result.get("main_pdf") else failures + 1
                                    continue
                            except PublisherAccessBlocked as blocked:
                                with self._blocked_lock:
                                    self._blocked_publishers.add(publisher.key)
                                exc = blocked
                            except Exception as recovery_error:
                                exc = BrowserSessionError(
                                    f"browser/CDP operation failed; bounded recovery failed: {type(recovery_error).__name__}"
                                )
                            failures += 1
                            harvested.append(self._safe_record(
                                target, publisher.key, "FAILED",
                                f"{type(exc).__name__}: {exc}",
                            ) | {"account_id": account_id})
                        except Exception as exc:
                            failures += 1
                            harvested.append(self._safe_record(
                                target, publisher.key, "FAILED",
                                f"{type(exc).__name__}: {exc}",
                            ) | {"account_id": account_id})
            except BrowserUnavailable as exc:
                harvested.extend(self._safe_record(
                    target, publisher.key, "UNAVAILABLE", str(exc),
                ) | {"account_id": account_id} for target, publisher in assigned)
            except Exception as exc:
                harvested.extend(self._safe_record(
                    target, publisher.key, "FAILED",
                    f"{type(exc).__name__}: {exc}",
                ) | {"account_id": account_id} for target, publisher in assigned)
            return harvested

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="literature-vpn") as pool:
            futures = [
                pool.submit(worker, account, bucket)
                for account, bucket in zip(accounts, buckets)
            ]
            for future in as_completed(futures):
                try:
                    results.extend(future.result())
                except Exception as exc:
                    # A worker exception is isolated; other accounts still complete.
                    report.setdefault("worker_errors", []).append(
                        f"{type(exc).__name__}: account worker failed"
                    )
        report["records"].extend(results)
        counts: dict[str, int] = {}
        for record in report["records"]:
            status = str(record.get("status") or "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
        report["summary"] = {
            "processed": len(results), "by_status": counts,
            "local_unregistered": sum(
                1 for item in results
                if item.get("artifact_registration_status") == ArtifactRegistrationStatus.LOCAL_UNREGISTERED.value
            ),
            "registered_artifact_count": sum(
                len((item.get("registration") or {}).get("artifacts") or []) for item in results
            ),
        }
        report["status"] = (
            "COMPLETE" if results and all(item.get("status") in {
                "FULL_TEXT_PLUS_SI", "FULL_TEXT_ONLY"
            } for item in results) else
            "PARTIAL" if any(item.get("main_pdf") or item.get("status") == "PARTIAL" for item in results) else
            "UNAVAILABLE"
        )
        return self._write_report(output_root, report)

    @staticmethod
    def _write_report(output_root: Path, report: dict[str, Any]) -> dict[str, Any]:
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / "acquisition_report.json"
        descriptor, temporary = tempfile.mkstemp(prefix=".acquisition-report.", suffix=".part", dir=output_root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        report["report_path"] = str(path)
        report["report_sha256"] = sha256_file(path)
        return report
