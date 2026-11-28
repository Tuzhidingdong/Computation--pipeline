"""Direct migration of chem-literature/core/paper_harvester.py.

Upstream source: Tuzhidingdong/chem-literature@e099406adb689281c0337bcacc7868c3ccdbc438.
Publisher routines retain the original Crossref PII → ScienceDirect DOM/CDP print,
Wiley pdfdirect/downloadSupplement, and IOP/ECS /article/{doi}/pdf algorithms.
This Pipeline port adds atomic writes, strict content checks, cache hash revalidation,
and per-paper diagnostics. No publisher access restrictions are bypassed.
"""

import os
import re
import time
import base64
import random
import hashlib
import json
import mimetypes
import zipfile
import tempfile
import threading
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

import requests
import pymupdf

from .contracts import doi_storage_id, sha256_file
from .vpn_session import VpnBrowserSession, PublisherAccessBlocked

class PaperHarvester:
    def __init__(self, output_dir: str | Path, *, min_pdf_bytes: int = 1024,
                 max_download_bytes: int = 250 * 1024 * 1024):
        self.output_dir = str(Path(output_dir).expanduser().resolve())
        self.pdf_dir = os.path.join(self.output_dir, "papers_pdf")
        self.si_dir = os.path.join(self.output_dir, "papers_si")
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.si_dir, exist_ok=True)
        self.min_pdf_bytes = int(min_pdf_bytes)
        self.max_download_bytes = int(max_download_bytes)
        self.diagnostics: list[dict[str, Any]] = []
        self._manifest_lock = threading.Lock()
        self._manifest_path = Path(self.output_dir) / "harvest_manifest.json"

    @staticmethod
    def safe_filename(doi: str) -> str:
        return doi_storage_id(doi)

    def _diagnose(self, doi: str, stage: str, message: str, *, status: str = "WARNING") -> None:
        # Do not store Cookie data, request headers, or full browser page bodies.
        self.diagnostics.append({
            "doi": doi, "stage": stage, "status": status,
            "diagnostic": str(message)[:1000], "occurred_at": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _valid_pdf(path: Path, *, min_bytes: int = 1024) -> tuple[bool, int | None, str | None]:
        try:
            if not path.is_file() or path.stat().st_size < min_bytes:
                return False, None, "FILE_MISSING_OR_TOO_SMALL"
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    return False, None, "PDF_MAGIC_BYTES_INVALID"
            with pymupdf.open(str(path)) as document:
                if document.needs_pass or len(document) < 1:
                    return False, None, "PDF_UNREADABLE_OR_ENCRYPTED"
                pages = len(document)
            return True, pages, None
        except Exception:
            return False, None, "PDF_PARSE_FAILED"

    @staticmethod
    def _valid_zip(data: bytes) -> bool:
        if not data.startswith((b"PK\\x03\\x04", b"PK\\x05\\x06", b"PK\\x07\\x08")):
            return False
        try:
            import io
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None:
                    return False
                return bool(archive.namelist())
        except Exception:
            return False

    @classmethod
    def validate_supplementary(cls, data: bytes) -> tuple[bool, str, str]:
        if data.startswith(b"%PDF-"):
            try:
                with pymupdf.open(stream=data, filetype="pdf") as document:
                    if not document.needs_pass and len(document) > 0:
                        return True, ".pdf", "PDF"
            except Exception:
                pass
            return False, ".pdf", "INVALID_PDF"
        if cls._valid_zip(data):
            try:
                import io
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if "word/document.xml" in archive.namelist():
                        from docx import Document as open_docx
                        open_docx(io.BytesIO(data))
                        return True, ".docx", "DOCX"
            except Exception:
                return False, ".docx", "INVALID_DOCX"
            return True, ".zip", "ZIP"
        return False, ".bin", "UNSUPPORTED_OR_INVALID"

    def _atomic_bytes(self, target: Path, data: bytes) -> None:
        if not data or len(data) > self.max_download_bytes:
            raise ValueError("download is empty or exceeds configured maximum size")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=str(target.parent))
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _write_pdf(self, doi: str, data: bytes) -> str:
        sid = self.safe_filename(doi)
        target = Path(self.pdf_dir) / f"{sid}.pdf"
        if not data.startswith(b"%PDF-"):
            raise ValueError("publisher response is not a PDF (%PDF- magic bytes missing)")
        if len(data) < self.min_pdf_bytes:
            raise ValueError("publisher PDF response is truncated or too small")
        # Validate the in-memory bytes before the final path can become visible.
        import io
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass or len(document) < 1:
                raise ValueError("publisher PDF is encrypted or has no readable pages")
            page_count = len(document)
        self._atomic_bytes(target, data)
        digest = sha256_file(target)
        self._write_sidecar(target, {"doi": doi, "sha256": digest, "size_bytes": len(data),
                                     "page_count": page_count, "content_type": "application/pdf"})
        return str(target)

    def _write_si(self, doi: str, data: bytes, *, suffix_hint: str = "") -> str:
        sid = self.safe_filename(doi)
        valid, suffix, detected = self.validate_supplementary(data)
        suffix = suffix if valid else (suffix_hint if suffix_hint in {".pdf", ".zip", ".docx"} else ".bin")
        target = Path(self.si_dir) / f"{sid}_SI{suffix}"
        self._atomic_bytes(target, data)
        self._write_sidecar(target, {
            "doi": doi, "sha256": sha256_file(target), "size_bytes": len(data),
            "content_type": detected, "validated": bool(valid),
        })
        if not valid:
            self._diagnose(doi, "SI_VALIDATION", detected)
        return str(target)

    def _write_sidecar(self, path: Path, payload: Mapping[str, Any]) -> None:
        sidecar = path.with_suffix(path.suffix + ".metadata.json")
        content = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\\n"
        descriptor, temporary = tempfile.mkstemp(prefix=f".{sidecar.name}.", suffix=".part", dir=str(sidecar.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, sidecar)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _cached_pdf(self, doi: str) -> str | None:
        path = Path(self.pdf_dir) / f"{self.safe_filename(doi)}.pdf"
        sidecar = path.with_suffix(path.suffix + ".metadata.json")
        if not path.is_file() or not sidecar.is_file():
            return None
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            valid, pages, _ = self._valid_pdf(path, min_bytes=self.min_pdf_bytes)
            digest = sha256_file(path)
            if (not valid or digest != metadata.get("sha256")
                    or path.stat().st_size != metadata.get("size_bytes")
                    or pages != metadata.get("page_count")):
                self._diagnose(doi, "CACHE_VALIDATION", "cached PDF failed magic/PyMuPDF/size/SHA-256 revalidation")
                return None
            return str(path)
        except Exception:
            self._diagnose(doi, "CACHE_VALIDATION", "cached PDF metadata is unreadable")
            return None

    def _record_download(self, doi: str, *, publisher: str, method: str,
                         source_url: str | None, main_path: str | None,
                         si_path: str | None) -> None:
        payload = {
            "doi": doi, "publisher": publisher, "acquisition_method": method,
            "source_url": source_url, "acquired_at": datetime.now(timezone.utc).isoformat(),
            "main_pdf": self._file_metadata(main_path) if main_path else None,
            "si_file": self._file_metadata(si_path) if si_path else None,
        }
        with self._manifest_lock:
            try:
                current = json.loads(self._manifest_path.read_text(encoding="utf-8")) if self._manifest_path.is_file() else {}
            except Exception:
                current = {}
            current[doi] = payload
            descriptor, temporary = tempfile.mkstemp(prefix=".harvest-manifest.", suffix=".part", dir=self.output_dir)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(current, handle, ensure_ascii=False, indent=2)
                    handle.write("\\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self._manifest_path)
            except Exception:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise

    @staticmethod
    def _file_metadata(value: str) -> dict[str, Any]:
        path = Path(value)
        return {"path": str(path), "content_type": mimetypes.guess_type(path.name)[0] or path.suffix.lower(),
                "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}

    def acquire(self, target: Mapping[str, Any], publisher_key: str,
                vpn: VpnBrowserSession, publisher_base: str) -> dict[str, Any]:
        doi = str(target.get("doi") or "").strip()
        if not doi:
            return {"status": "FAILED", "diagnostic": "DOI_MISSING"}
        self.diagnostics = []
        main = self._cached_pdf(doi)
        si = None
        source_url = None
        try:
            if publisher_key == "elsevier":
                pii = self.resolve_elsevier_pii(doi)
                if not pii:
                    self._diagnose(doi, "DOI_TO_PII", "Crossref did not provide a ScienceDirect PII", status="FAILED")
                    return {"status": "FAILED", "doi": doi, "main_pdf": None, "si_file": None,
                            "diagnostics": list(self.diagnostics), "method": "crossref_pii_cdp_render_print_pdf"}
                source_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
                main, si = self.harvest_elsevier(vpn, publisher_base, doi, pii)
            elif publisher_key == "wiley":
                source_url = f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}?download=true"
                main, si = self.harvest_wiley(vpn, publisher_base, doi)
            elif publisher_key == "iop_ecs":
                source_url = f"https://iopscience.iop.org/article/{doi}/pdf"
                main = self.harvest_iop(vpn, publisher_base, doi)
            else:
                return {"status": "NOT_IMPLEMENTED", "doi": doi, "main_pdf": None, "si_file": None,
                        "diagnostics": [{"stage": "PUBLISHER", "status": "NOT_IMPLEMENTED"}]}
        except PublisherAccessBlocked as exc:
            self._diagnose(doi, "PUBLISHER_ACCESS", str(exc), status="BLOCKED")
            main = self._cached_pdf(doi)
            si = None
            blocked = True
        except Exception as exc:
            self._diagnose(doi, "PUBLISHER_HARVEST", f"{type(exc).__name__}: {exc}", status="FAILED")
            main = self._cached_pdf(doi)
            si = None
            blocked = False
        else:
            blocked = False
        if main and not Path(main).is_absolute():
            main = str(Path(self.pdf_dir) / Path(main).name)
        if si and not Path(si).is_absolute():
            si = str(Path(self.si_dir) / Path(si).name)
        valid, page_count, error = self._valid_pdf(Path(main), min_bytes=self.min_pdf_bytes) if main else (False, None, "MAIN_PDF_UNAVAILABLE")
        if not valid:
            main = None
            self._diagnose(doi, "MAIN_PDF", error or "MAIN_PDF_UNAVAILABLE", status="FAILED")
        si_valid = bool(si and Path(si).is_file())
        if si_valid:
            si_valid, _, si_kind = self.validate_supplementary(Path(si).read_bytes())
            if not si_valid:
                self._diagnose(doi, "SI_FILE", si_kind)
        self._record_download(doi, publisher=publisher_key,
                              method={"elsevier": "science_direct_dom_print", "wiley": "pdfdirect", "iop_ecs": "article_pdf"}[publisher_key],
                              source_url=source_url, main_path=main, si_path=si if si_valid else None)
        return {
            "doi": doi, "publisher": publisher_key,
            "status": ("PARTIAL" if valid and blocked else
                       "FULL_TEXT_PLUS_SI" if valid and si_valid else
                       "PARTIAL" if valid and si and not si_valid else
                       "FULL_TEXT_ONLY" if valid else "FAILED"),
            "main_pdf": main, "main_pdf_page_count": page_count,
            "si_file": si if si_valid else None, "si_available": bool(si_valid),
            "si_content_type": Path(si).suffix.lstrip(".").upper() if si_valid and si else None,
            "source_url": source_url,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "main_file": self._file_metadata(main) if main else None,
            "si_file_metadata": self._file_metadata(si) if si_valid and si else None,
            "diagnostics": list(self.diagnostics),
            "method": {"elsevier": "crossref_pii_cdp_render_print_pdf",
                       "wiley": "pdfdirect_downloadSupplement", "iop_ecs": "article_doi_pdf_endpoint"}[publisher_key],
        }

    @staticmethod
    def resolve_elsevier_pii(doi: str) -> Optional[str]:
        """Resolve ScienceDirect PII from Crossref API metadata."""
        try:
            url = f"https://api.crossref.org/works/{quote(str(doi), safe='')}"
            r = requests.get(url, timeout=10).json()
            items = r.get("message", {}).get("link", [])
            for item in items:
                u = item.get("URL", "")
                m = re.search(r'(?:PII:|/pii/)([A-Za-z0-9]+)', u, flags=re.I)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def harvest_elsevier(self, vpn: VpnBrowserSession, sd_base: str, doi: str, pii: str) -> Tuple[Optional[str], Optional[str]]:
        """Migrated Elsevier flow: resolve PII, DOM lazy-load scroll, print CSS cleanup, CDP PDF and MMC SI."""
        sid = self.safe_filename(doi)
        pdf_out = Path(self.pdf_dir) / f"{sid}.pdf"
        main_path = self._cached_pdf(doi)
        si_path = None
        url = f"{sd_base}science/article/pii/{pii}"
        vpn.navigate(url, wait_secs=9)

        # Retain the original ScienceDirect MMC/ars.els-cdn.com SI discovery strategy.
        try:
            links = vpn.cdp.eval("Array.from(document.querySelectorAll('a[href]')).map(a => a.href)") or []
            mmc_links = [link for link in links if "mmc" in link.lower() or "ars.els-cdn.com" in link.lower()]
            if mmc_links:
                data, _ = vpn.fetch_binary(mmc_links[0], max_bytes=self.max_download_bytes)
                if data:
                    si_path = self._write_si(doi, data)
        except PublisherAccessBlocked:
            raise
        except Exception as exc:
            self._diagnose(doi, "ELSEVIER_SI_DOWNLOAD", f"{type(exc).__name__}: {exc}")

        if main_path:
            return main_path, si_path

        # Original CDP scroll: lazy-loaded article figures/content are brought into DOM.
        vpn.cdp.eval("""(async () => {
            const total = Math.min(document.body.scrollHeight || 15000, 45000);
            for (let y = 0; y <= total; y += 1200) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
            }
            window.scrollTo(0, 0);
            for (const sheet of Array.from(document.styleSheets)) {
                try {
                    const rules = Array.from(sheet.cssRules || []);
                    for (let i = rules.length - 1; i >= 0; i--) {
                        if (rules[i].type === CSSRule.MEDIA_RULE && /print/i.test(rules[i].conditionText || '')) {
                            sheet.deleteRule(i);
                        }
                    }
                } catch (e) {}
            }
            const hideSelectors = [
                'header', 'footer', '#gh-cnt', '.Toolbar', '.TableOfContents',
                '.RelatedContent', '.RecommendedArticles', '#onetrust-consent-sdk',
                '.Outline', '.elsevier-non-solus'
            ];
            for (const sel of hideSelectors) {
                document.querySelectorAll(sel).forEach(el => el.style.display = 'none');
            }
        })()""", await_promise=True)
        vpn.cdp.call("Emulation.setEmulatedMedia", {"media": "screen"})
        time.sleep(1.5)
        pdf_res = vpn.cdp.call("Page.printToPDF", {
            "printBackground": True, "preferCSSPageSize": True,
            "marginTop": 0.4, "marginBottom": 0.4,
            "marginLeft": 0.4, "marginRight": 0.4,
        })
        encoded = pdf_res.get("data", "")
        if not encoded:
            self._diagnose(doi, "ELSEVIER_MAIN_PDF", "Page.printToPDF returned no PDF data")
            return None, si_path
        try:
            pdf_bytes = base64.b64decode(encoded, validate=True)
            main_path = self._write_pdf(doi, pdf_bytes)
        except Exception as exc:
            self._diagnose(doi, "ELSEVIER_MAIN_PDF", f"{type(exc).__name__}: {exc}", status="FAILED")
            return None, si_path
        return main_path, si_path

    def harvest_wiley(self, vpn: VpnBrowserSession, wiley_base: str, doi: str) -> Tuple[Optional[str], Optional[str]]:
        """Migrated Wiley /doi/pdfdirect and downloadSupplement strategies."""
        main_path = self._cached_pdf(doi)
        si_path = None
        if not main_path:
            pdf_url = f"{wiley_base}doi/pdfdirect/{doi}?download=true"
            try:
                data, _ = vpn.fetch_binary(pdf_url, max_bytes=self.max_download_bytes)
                if data:
                    main_path = self._write_pdf(doi, data)
                else:
                    self._diagnose(doi, "WILEY_MAIN_PDF", "PDF direct endpoint returned no file")
            except PublisherAccessBlocked:
                raise
            except Exception as exc:
                self._diagnose(doi, "WILEY_MAIN_PDF", f"{type(exc).__name__}: {exc}", status="FAILED")

        # Keep the upstream full-text-page link discovery selector.
        try:
            art_url = f"{wiley_base}doi/full/{doi}"
            vpn.navigate(art_url, wait_secs=6)
            links = vpn.cdp.eval(
                """Array.from(document.querySelectorAll('a[href*="downloadSupplement"]')).map(a => a.href)"""
            ) or []
            for link in links:
                try:
                    data, _ = vpn.fetch_binary(link, max_bytes=self.max_download_bytes)
                    if data:
                        valid, _, _ = self.validate_supplementary(data)
                        si_path = self._write_si(doi, data)
                        if valid:
                            break
                except PublisherAccessBlocked:
                    raise
                except Exception as exc:
                    self._diagnose(doi, "WILEY_SI_DOWNLOAD", f"{type(exc).__name__}: {exc}")
        except PublisherAccessBlocked:
            raise
        except Exception as exc:
            self._diagnose(doi, "WILEY_SI_DISCOVERY", f"{type(exc).__name__}: {exc}")
        return main_path, si_path

    def harvest_iop(self, vpn: VpnBrowserSession, iop_base: str, doi: str) -> Optional[str]:
        """Migrated IOP/ECS /article/{doi}/pdf endpoint."""
        main_path = self._cached_pdf(doi)
        if main_path:
            return main_path
        pdf_url = f"{iop_base}article/{doi}/pdf"
        data, _ = vpn.fetch_binary(pdf_url, max_bytes=self.max_download_bytes)
        if not data:
            self._diagnose(doi, "IOP_ECS_MAIN_PDF", "publisher PDF endpoint returned no file")
            return None
        try:
            return self._write_pdf(doi, data)
        except Exception as exc:
            self._diagnose(doi, "IOP_ECS_MAIN_PDF", f"{type(exc).__name__}: {exc}", status="FAILED")
            return None

