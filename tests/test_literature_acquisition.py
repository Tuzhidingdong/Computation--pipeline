from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pymupdf
from docx import Document

from pipeline_contracts.literature_acquisition.contracts import (
    AcquisitionConfig, LiteratureTarget, decide_si_requirement, doi_storage_id,
)
from pipeline_contracts.literature_acquisition.evidence import source_package_evidence
from pipeline_contracts.literature_acquisition.package_builder import (
    _extract_supported_zip_members, build_source_package,
)
from pipeline_contracts.literature_acquisition.paper_harvester import PaperHarvester
from pipeline_contracts.literature_acquisition.publisher_registry import (
    detect_publisher, publisher_support_matrix,
)
from pipeline_contracts.literature_acquisition.schemas import validate_source_package
from pipeline_contracts.literature_acquisition.source_preprocessor import SourcePreprocessor
from pipeline_contracts.literature_acquisition.vpn_session import (
    BrowserSessionError, VpnBrowserSession, discover_cookie_accounts,
)


def _pdf(path: Path, title: str = "Synthetic test paper", *, figure: bool = False) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((45, 50), title, fontsize=12)
    page.insert_textbox(
        pymupdf.Rect(45, 80, 540, 360),
        ("Deterministic offline literature acquisition test. " * 30),
        fontsize=10,
    )
    if figure:
        page.draw_rect(pymupdf.Rect(80, 390, 500, 610), color=(0, 0, 0), width=2)
        page.insert_textbox(
            pymupdf.Rect(55, 620, 530, 690),
            "Figure 1. Synthetic geometric schematic with a caption.",
            fontsize=10,
        )
    document.save(path)
    document.close()
    return path


def _pdf_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as temp:
        path = _pdf(Path(temp) / "fixture.pdf", figure=True)
        return path.read_bytes()


def _docx(path: Path) -> Path:
    document = Document()
    document.add_heading("Supporting Information", level=1)
    document.add_paragraph("Synthesis details and experimental conditions.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Temperature"
    table.cell(1, 1).text = "298 K"
    document.save(path)
    return path


class _FakeCDP:
    def __init__(self, pdf_bytes: bytes, si_bytes: bytes | None = None):
        self.pdf_bytes = pdf_bytes
        self.si_bytes = si_bytes
        self.calls = []

    def eval(self, expression, await_promise=False, **kwargs):
        self.calls.append(("eval", expression))
        if "downloadSupplement" in expression:
            return ["https://onlinelibrary.wiley.com/supplement.bin"]
        if "document.querySelectorAll('a[href]')" in expression:
            return []
        return True

    def call(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        if method == "Page.printToPDF":
            return {"data": base64.b64encode(self.pdf_bytes).decode("ascii")}
        return {}


class _FakeVPN:
    def __init__(self, pdf_bytes: bytes, si_bytes: bytes | None = None):
        self.cdp = _FakeCDP(pdf_bytes, si_bytes)
        self.pdf_bytes = pdf_bytes
        self.si_bytes = si_bytes
        self.visited = []
        self.fetched = []

    def navigate(self, url, wait_secs=0):
        self.visited.append(url)
        return url, "Synthetic publisher article", "article body"

    def fetch_binary(self, url, **kwargs):
        self.fetched.append(url)
        if "downloadSupplement" in url or "supplement" in url:
            return self.si_bytes, "application/zip"
        return self.pdf_bytes, "application/pdf"


class _MockDataAnalysis:
    execution_mode = "mock"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {}
        self.counter = 0

    def register_derived_artifact(self, project_root, file_path, *, source_artifact_ids, format_id, provenance):
        self.counter += 1
        artifact_id = f"mock-literature-artifact-{self.counter:04d}"
        destination = self.root / artifact_id
        shutil.copy2(file_path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        self.paths[artifact_id] = destination
        return {
            "artifact_id": artifact_id, "sha256": digest,
            "format_id": format_id, "mock": True, "execution_mode": "mock",
        }

    def resolve_artifact_path(self, project_root, artifact_id):
        return str(self.paths[artifact_id])


def test_doi_storage_id_is_collision_resistant_and_filesystem_safe():
    left = doi_storage_id("10.1000/a:b")
    right = doi_storage_id("10.1000/a?b")
    assert left != right
    assert "/" not in left and "\\" not in left
    assert len(left) <= 80


def test_publisher_registry_only_claims_validated_routes():
    assert detect_publisher({
        "doi": "10.1000/wiley",
        "source_records": [{"publisher": "John Wiley & Sons", "source_url": "https://doi.org/x"}],
    }).key == "wiley"
    assert detect_publisher({
        "doi": "10.1000/elsevier",
        "publisher": "Elsevier BV",
    }).key == "elsevier"
    assert detect_publisher({
        "doi": "10.1000/nature",
        "source_urls": ["https://www.nature.com/articles/example"],
    }).supported is False
    assert detect_publisher({
        "doi": "10.1000/springer",
        "publisher": "Springer Nature",
    }).method == "NOT_IMPLEMENTED"
    assert {item["key"] for item in publisher_support_matrix() if item["supported"]} == {
        "elsevier", "wiley", "iop_ecs",
    }


def test_resolve_elsevier_pii_accepts_crossref_pii_path_and_label(tmp_path):
    class _Response:
        def json(self):
            return {"message": {"link": [
                {"URL": "https://api.elsevier.com/content/article/pii/S1234567890123456"}
            ]}}
    with patch("pipeline_contracts.literature_acquisition.paper_harvester.requests.get", return_value=_Response()):
        assert PaperHarvester.resolve_elsevier_pii("10.1016/j.synthetic.1") == "S1234567890123456"


def test_crossref_pii_elsevier_dom_print_pdf_and_mmc_strategy(tmp_path):
    pdf_data = _pdf_bytes()
    harvester = PaperHarvester(tmp_path, min_pdf_bytes=100)
    vpn = _FakeVPN(pdf_data)

    class _Response:
        def json(self):
            return {"message": {"link": [{"URL": "https://api.elsevier.com/content/article/pii/PII:S123456789"}]}}

    with patch("pipeline_contracts.literature_acquisition.paper_harvester.requests.get", return_value=_Response()):
        result = harvester.acquire(
            {"doi": "10.1016/j.synthetic.2026.0001", "title": "Synthetic"},
            "elsevier", vpn, "https://vpn.example/https/token/",
        )
    assert result["status"] == "FULL_TEXT_ONLY"
    assert Path(result["main_pdf"]).is_file()
    assert result["main_pdf_page_count"] >= 1
    assert any(call[0] == "Page.printToPDF" for call in vpn.cdp.calls)
    assert result["main_file"]["sha256"] == hashlib.sha256(Path(result["main_pdf"]).read_bytes()).hexdigest()


def test_wiley_pdfdirect_and_download_supplement_strategy(tmp_path):
    pdf_data = _pdf_bytes()
    si_data = _docx(tmp_path / "supplement.docx").read_bytes()
    harvester = PaperHarvester(tmp_path / "wiley", min_pdf_bytes=100)
    vpn = _FakeVPN(pdf_data, si_data)
    main, si = harvester.harvest_wiley(vpn, "https://onlinelibrary.wiley.com/", "10.1002/synthetic.1")
    assert main and Path(main).is_file()
    assert si and Path(si).suffix == ".docx"
    assert any("/doi/pdfdirect/" in item for item in vpn.fetched)
    assert any("/doi/full/" in item for item in vpn.visited)
    assert PaperHarvester.validate_supplementary(Path(si).read_bytes()) == (True, ".docx", "DOCX")


def test_iop_ecs_article_doi_pdf_strategy(tmp_path):
    harvester = PaperHarvester(tmp_path / "iop", min_pdf_bytes=100)
    vpn = _FakeVPN(_pdf_bytes())
    output = harvester.harvest_iop(vpn, "https://iopscience.iop.org/", "10.1088/0000-0000/1/1/1")
    assert output and Path(output).is_file()
    assert vpn.visited == []


def test_pdf_zip_and_docx_magic_bytes_and_html_or_truncated_pdf_rejection(tmp_path):
    harvester = PaperHarvester(tmp_path / "verify", min_pdf_bytes=100)
    assert harvester.validate_supplementary(_docx(tmp_path / "file.docx").read_bytes()) == (True, ".docx", "DOCX")
    with zipfile.ZipFile(tmp_path / "file.zip", "w") as archive:
        archive.writestr("notes.txt", "supplementary data")
    zip_bytes = (tmp_path / "file.zip").read_bytes()
    assert harvester.validate_supplementary(zip_bytes) == (True, ".zip", "ZIP")
    assert harvester.validate_supplementary(b"<html>403 access denied</html>")[0] is False
    assert harvester.validate_supplementary(b"%PDF-1.7 broken and truncated")[0] is False
    with pytest.raises(Exception):
        harvester._write_pdf("10.1000/bad", b"<html>200 login page</html>")
    with pytest.raises(Exception):
        harvester._write_pdf("10.1000/truncated", b"%PDF-1.7 broken")


def test_cached_pdf_is_revalidated_by_magic_pymupdf_size_sha_and_page_count(tmp_path):
    harvester = PaperHarvester(tmp_path, min_pdf_bytes=100)
    created = harvester._write_pdf("10.1000/cache", _pdf_bytes())
    assert harvester._cached_pdf("10.1000/cache") == created

    path = Path(created)
    path.write_bytes(b"%PDF-1.7 truncated")
    assert harvester._cached_pdf("10.1000/cache") is None
    assert any(item["stage"] == "CACHE_VALIDATION" for item in harvester.diagnostics)


def test_si_zip_path_traversal_and_size_limits(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escaped.pdf", b"%PDF-1.7" + b"x" * 120)
        archive.writestr("folder/safe.pdf", _pdf_bytes())
    extracted, unsupported = _extract_supported_zip_members(
        archive_path, tmp_path / "unpacked",
        max_member_bytes=100000, max_total_bytes=200000,
    )
    assert not (tmp_path / "escaped.pdf").exists()
    assert len(extracted) == 1
    assert any("unsafe archive path" in item for item in unsupported)

    huge = tmp_path / "huge.zip"
    with zipfile.ZipFile(huge, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.pdf", b"%PDF-" + b"x" * 5000)
    extracted, unsupported = _extract_supported_zip_members(
        huge, tmp_path / "limited", max_member_bytes=200, max_total_bytes=300,
    )
    assert extracted == []
    assert any("size limit" in item for item in unsupported)


def test_cookie_account_discovery_never_returns_cookie_values(tmp_path):
    secret = "DO_NOT_LOG_THIS_SESSION_TICKET"
    (tmp_path / "account01.json").write_text(json.dumps([{
        "name": "session", "value": secret, "domain": "vpn.example", "path": "/",
    }]), encoding="utf-8")
    (tmp_path / "invalid.json").write_text("{not-json}", encoding="utf-8")
    accounts = discover_cookie_accounts(tmp_path)
    assert len(accounts) == 1
    assert secret not in json.dumps(accounts)
    assert "account_id" in accounts[0]
    assert "cookie_file" in accounts[0]


def test_vpn_cookie_loader_keeps_secret_values_out_of_exception_text(tmp_path):
    secret = "DO_NOT_EXPOSE_COOKIE"
    path = tmp_path / "cookie.json"
    path.write_text(json.dumps([{
        "name": "session", "value": secret, "domain": "vpn.example",
    }]), encoding="utf-8")
    config = AcquisitionConfig.from_mapping({
        "cookie_dir": str(tmp_path), "output_dir": str(tmp_path / "out"),
    }, base_dir=tmp_path)
    session = VpnBrowserSession(path, config=config, workspace_dir=tmp_path)
    assert session._read_cookies()[0]["value"] == secret
    path.write_text("{", encoding="utf-8")
    with pytest.raises(BrowserSessionError) as error:
        session._read_cookies()
    assert secret not in str(error.value)


def test_source_package_main_only_is_valid_and_reusable(tmp_path):
    main = _pdf(tmp_path / "main.pdf", figure=True)
    result = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/main-only", title="Main only paper", config={"grobid_enabled": False},
    )
    package_dir = Path(result["package_dir"])
    package = result["package"]
    assert result["status"] == "PARTIAL_NO_SI"
    assert package["metadata"]["has_si"] is False
    assert (package_dir / "main_analysis.md").is_file()
    assert (package_dir / "si_analysis.md").is_file()
    assert (package_dir / "source_files" / package["inventory"]["main_pdf"]["path"].split("/")[-1]).is_file()
    assert (package_dir / "evidence_index.json").is_file()
    assert (package_dir / "PREPROCESSING_QC_REPORT.md").is_file()
    validate_source_package(package)

    second = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/main-only", title="Main only paper", config={"grobid_enabled": False},
    )
    assert second["action"] == "REUSED_UNCHANGED"


def test_source_package_si_docx_extracts_paragraphs_tables_media_contract(tmp_path):
    main = _pdf(tmp_path / "main.pdf")
    support = _docx(tmp_path / "support.docx")
    result = build_source_package(
        main_pdf=main, supplementary_files=[support], output_dir=tmp_path / "packages",
        doi="10.1000/docx-si", title="DOCX SI paper",
    )
    package_dir = Path(result["package_dir"])
    package = result["package"]
    assert result["status"] == "COMPLETE"
    assert package["metadata"]["has_si"] is True
    assert "Synthesis details" in (package_dir / "si_analysis.md").read_text(encoding="utf-8")
    assert any(item["doc_type"] == "SI" for item in package["tables"])
    si_table = next(item for item in package["tables"] if item["doc_type"] == "SI")
    assert si_table["source_file"] == support.name
    assert si_table["source_sha256"] == hashlib.sha256(support.read_bytes()).hexdigest()
    assert package["inventory"]["source_supplementary_files"][0]["sha256"] == hashlib.sha256(support.read_bytes()).hexdigest()
    validate_source_package(package)


def test_si_scanned_pages_are_explicitly_warned_and_grobid_falls_back(tmp_path):
    # An empty image-like page has no extractable text layer and is flagged as scanned.
    doc = pymupdf.open()
    doc.new_page()
    main = tmp_path / "scan.pdf"
    doc.save(main)
    doc.close()

    with patch.object(SourcePreprocessor, "_call_grobid", side_effect=RuntimeError("GROBID unavailable")):
        result = build_source_package(
            main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
            doi="10.1000/scanned", title="Scanned paper",
            config={"grobid_enabled": True},
        )
    assert result["status"] == "WARNING_SCANNED_PAGES"
    assert result["package"]["processing_summary"]["scanned_pages_detected"] >= 1
    assert result["package"]["processing_summary"]["grobid_status"] == "UNAVAILABLE_FALLBACK"


def test_package_cache_rebuilds_if_an_extracted_asset_sha_changes(tmp_path):
    main = _pdf(tmp_path / "main.pdf", figure=True)
    result = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/cache-assets",
    )
    package_dir = Path(result["package_dir"])
    asset = result["package"]["media_assets"][0]
    target = package_dir / asset["relative_path"]
    target.write_bytes(b"tampered")
    rebuilt = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/cache-assets",
    )
    assert rebuilt["action"] == "PROCESSED"
    assert hashlib.sha256((package_dir / asset["relative_path"]).read_bytes()).hexdigest() == asset["sha256"]


def test_source_package_pages_tables_and_figures_become_evidence_with_artifactrefs(tmp_path):
    main = _pdf(tmp_path / "main.pdf", figure=True)
    result = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/evidence", title="Evidence source",
    )
    package_dir = Path(result["package_dir"])
    package = result["package"]
    files = {}
    for path in package_dir.rglob("*"):
        if path.is_file():
            files[path.relative_to(package_dir).as_posix()] = {
                "artifact_id": "mock-artifact-" + str(len(files) + 1),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "verified": True,
                "mock": True,
                "artifact_ref": {
                    "artifact_id": "mock-artifact-" + str(len(files) + 1),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "format_id": "mock/source-file",
                    "media_type": "application/octet-stream",
                    "uri": "mock://data-analysis/artifact-" + str(len(files) + 1),
                    "storage_mode": "mock",
                    "source_system": "Mock:Data_analysis",
                    "mock": True,
                },
            }
    acquisition = {
        "records": [{
            "doi": "10.1000/evidence", "title": "Evidence source",
            "source_package_path": str(package_dir),
            "source_package_id": package["paper_id"],
            "source_package_sha256": hashlib.sha256((package_dir / "evidence_index.json").read_bytes()).hexdigest(),
            "artifact_registration_status": "REGISTERED",
            "registration": {
                "status": "REGISTERED", "mock_only": True,
                "artifacts": list(files.values()), "by_relative_path": files,
            },
        }],
    }
    rows = source_package_evidence(acquisition)
    assert any(item["evidence_type"] == "FULL_TEXT_PAGE" and item["page_number"] == 1 for item in rows)
    assert any(item["evidence_type"] == "EXTRACTED_FIGURE_ASSET" for item in rows)
    assert all(item["source_sha256"] for item in rows)
    page = next(item for item in rows if item["evidence_type"] == "FULL_TEXT_PAGE")
    assert page["source_artifact_ids"]
    assert page["artifact_registration_mock_only"] is True
    assert page["evidence_ref"]["contract_id"] == "pipeline-literature-evidence-ref"
    assert list(page["evidence_ref"]["source_artifact_ids"]) == page["source_artifact_ids"]



def test_two_cookie_accounts_receive_distinct_temporary_profiles_and_ports(tmp_path, monkeypatch):
    from pipeline_contracts.literature_acquisition import vpn_session

    browser = tmp_path / "edge.exe"
    browser.write_bytes(b"mock executable")
    cookie_a = tmp_path / "a.json"
    cookie_b = tmp_path / "b.json"
    cookie_a.write_text(json.dumps([{"name": "session", "value": "A_SECRET", "domain": "vpn.example"}]), encoding="utf-8")
    cookie_b.write_text(json.dumps([{"name": "session", "value": "B_SECRET", "domain": "vpn.example"}]), encoding="utf-8")
    config = AcquisitionConfig.from_mapping({
        "browser_executable": str(browser), "output_dir": str(tmp_path / "out"),
        "cookie_dir": str(tmp_path), "browser_headless": True,
    }, base_dir=tmp_path)

    class _DebugResponse:
        status_code = 200
        def json(self):
            return [{"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}]

    class _Process:
        next_pid = 1000
        def __init__(self, args):
            self.args = list(args)
            self.pid = _Process.next_pid
            _Process.next_pid += 1
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0

    class _CDP:
        def __init__(self):
            self.calls = []
        def call(self, method, params=None, **kwargs):
            self.calls.append((method, params))
            return {}
        def close(self):
            pass

    processes = []
    clients = []
    def fake_popen(args, **kwargs):
        process = _Process(args)
        processes.append(process)
        return process
    def fake_cdp(url, timeout):
        client = _CDP()
        clients.append(client)
        return client

    monkeypatch.setattr(vpn_session.requests, "get", lambda *args, **kwargs: _DebugResponse())
    monkeypatch.setattr(vpn_session.subprocess, "Popen", fake_popen)
    profiles = []
    for account_id, cookie_file in (("a", cookie_a), ("b", cookie_b)):
        session = VpnBrowserSession(
            cookie_file, config=config, account_id=account_id,
            workspace_dir=tmp_path / "isolated", cdp_factory=fake_cdp,
        )
        session.__enter__()
        profiles.append(session.sandbox_profile)
        set_cookies = next(params for method, params in clients[-1].calls if method == "Network.setCookies")
        assert set_cookies["cookies"][0]["value"] in {"A_SECRET", "B_SECRET"}
        session.close()
        assert session.sandbox_profile is None

    assert profiles[0] != profiles[1]
    assert all(not Path(profile).exists() for profile in profiles)
    assert len({arg.split("=", 1)[1] for proc in processes
                for arg in proc.args if arg.startswith("--remote-debugging-port=")}) == 2
    assert all(any(arg.startswith("--user-data-dir=") for arg in proc.args) for proc in processes)


def test_cdp_timeout_and_rate_limit_fail_closed(monkeypatch, tmp_path):
    import websocket
    from pipeline_contracts.literature_acquisition.vpn_session import CDPClient, PublisherAccessBlocked

    class _TimeoutSocket:
        def settimeout(self, value):
            pass
        def send(self, message):
            pass
        def recv(self):
            raise websocket.WebSocketTimeoutException()
        def close(self):
            pass
    monkeypatch.setattr(
        "pipeline_contracts.literature_acquisition.vpn_session.websocket.create_connection",
        lambda *args, **kwargs: _TimeoutSocket(),
    )
    client = CDPClient("ws://127.0.0.1/devtools/page/test", timeout=1)
    with pytest.raises(BrowserSessionError):
        client.call("Page.navigate", {"url": "https://publisher.example"}, timeout=0.01)

    config = AcquisitionConfig.from_mapping({"output_dir": str(tmp_path / "out")}, base_dir=tmp_path)
    session = VpnBrowserSession(tmp_path / "cookie.json", config=config)
    class _RateLimitedCDP:
        def eval(self, *args, **kwargs):
            return {"status": 429, "data": None, "ctype": "text/html"}
    session.cdp = _RateLimitedCDP()
    with pytest.raises(PublisherAccessBlocked) as error:
        session.fetch_binary("https://publisher.example/article.pdf")
    assert error.value.status == 429


def test_one_account_worker_failure_does_not_cancel_other_account(tmp_path):
    from pipeline_contracts.literature_acquisition.acquisition_service import LiteratureAcquisitionService
    from pipeline_contracts.literature_acquisition.vpn_session import BrowserUnavailable

    main = _pdf(tmp_path / "main.pdf")
    config = AcquisitionConfig.from_mapping({
        "enabled": True, "output_dir": str(tmp_path / "out"),
        "cookie_dir": str(tmp_path / "cookies"), "portal_url": "https://vpn.example",
        "publisher_resource_ids": {"elsevier": 42},
        "max_workers": 2, "min_delay_seconds": 0, "max_delay_seconds": 0,
        "preprocessing_enabled": False,
    }, base_dir=tmp_path)

    class _GoodSession:
        def __init__(self, cookie_file, **kwargs):
            self.cookie_file = cookie_file
        def __enter__(self):
            if self.cookie_file == "broken":
                raise BrowserUnavailable("mock account could not launch isolated Edge")
            return self
        def __exit__(self, *args):
            return False
        def get_proxy_base(self, *args, **kwargs):
            return "https://vpn.example/https/token/"

    class _Harvester:
        def __init__(self, output_dir):
            pass
        def acquire(self, target, publisher_key, vpn, publisher_base):
            return {
                "status": "FULL_TEXT_ONLY", "main_pdf": str(main),
                "si_file": None, "si_available": False,
                "diagnostics": [], "source_url": "https://www.sciencedirect.com/article/example",
            }

    service = LiteratureAcquisitionService(
        config, session_factory=_GoodSession, harvester_factory=_Harvester,
        account_discoverer=lambda _: [
            {"account_id": "account-01", "cookie_file": "broken"},
            {"account_id": "account-02", "cookie_file": "good"},
        ],
        sleeper=lambda _: None, random_uniform=lambda low, high: 0,
    )
    records = [
        {"doi": "10.1016/j.example.1", "title": "Paper one",
         "source_urls": ["https://www.sciencedirect.com/science/article/example/1"]},
        {"doi": "10.1016/j.example.2", "title": "Paper two",
         "source_urls": ["https://www.sciencedirect.com/science/article/example/2"]},
    ]
    report = service.acquire(
        records, run_root=tmp_path / "run",
        context={"research_question": "Compare paper methods"}, enabled_override=True,
    )
    assert report["summary"]["processed"] == 2
    assert any(item.get("status") == "UNAVAILABLE" for item in report["records"])
    assert any(item.get("main_pdf") == str(main) for item in report["records"])



def test_corrupt_si_pdf_is_preserved_but_main_only_package_survives(tmp_path):
    main = _pdf(tmp_path / "main.pdf", "MAIN paper remains readable.")
    bad_si = tmp_path / "support.pdf"
    bad_si.write_bytes(b"%PDF-1.7 truncated SI payload")
    result = build_source_package(
        main_pdf=main, supplementary_files=[bad_si],
        output_dir=tmp_path / "packages",
        doi="10.1000/corrupt-si", title="SI extraction failure test",
    )
    package = result["package"]
    package_dir = Path(result["package_dir"])
    assert result["status"] == "PARTIAL_SI_UNSUPPORTED"
    assert package["metadata"]["has_si"] is True
    assert package["processing_summary"]["total_main_pages"] >= 1
    assert package["processing_summary"]["total_si_pages"] == 0
    assert package["inventory"]["source_supplementary_files"][0]["sha256"] == hashlib.sha256(bad_si.read_bytes()).hexdigest()
    assert (package_dir / package["inventory"]["source_supplementary_files"][0]["relative_path"]).is_file()
    assert "MAIN paper remains readable" in (package_dir / "main_analysis.md").read_text(encoding="utf-8")
    assert "SI preprocessing failure" in (package_dir / "PREPROCESSING_QC_REPORT.md").read_text(encoding="utf-8")
    validate_source_package(package)


def test_required_si_evidence_gap_blocks_a_scientific_recommendation():
    from pipeline_contracts.scientific_planning.literature_engine import _build_decision_proposals

    issues = [{
        "issue_id": "issue-si-required", "classification": "GENUINE_SCIENTIFIC_DECISION",
        "affected_fields": ["method.spin_resolution"],
        "description": "Which spin method should be used?",
        "related_planning_objects": [],
    }]
    specs = [{
        "field_path": "method.spin_resolution",
        "options": [{
            "option_id": "option-a", "label": "Alternative A", "value": "A",
        }],
    }]
    evidence = [{
        "evidence_id": "abstract-from-paper-with-missing-si",
        "doi": "10.1000/si-required",
        "requires_si": True,
        "si_dependency_status": "MISSING_REQUIRED_SI_EVIDENCE",
        "polarity": "SUPPORTS",
    }]
    assessments = {
        "issue-si-required": {
            "recommended_option_id": "option-a",
            "reason": "The mock assessor recommended this option.",
            "evidence_ids": ["abstract-from-paper-with-missing-si"],
            "option_assessments": [{
                "option_id": "option-a",
                "supporting_evidence_ids": ["abstract-from-paper-with-missing-si"],
                "reason": "The support was drawn from the abstract.",
            }],
        },
    }
    proposal = _build_decision_proposals(issues, specs, evidence, assessments)[0]
    assert proposal["assessment"]["status"] == "BLOCKED_REQUIRED_SI_EVIDENCE_MISSING"
    assert proposal["assessment"]["option_id"] is None
    assert proposal["assessment"]["missing_required_si_evidence_ids"] == [
        "abstract-from-paper-with-missing-si"
    ]


def test_external_skill_payload_omits_locally_acquired_fulltext_without_consent():
    from pipeline_contracts.scientific_planning.literature_engine import _external_evidence_matrix

    matrix = [
        {"evidence_id": "metadata-abstract", "databases": ["crossref"]},
        {"evidence_id": "fulltext-page", "databases": ["publisher-full-text-acquisition"],
         "evidence_type": "FULL_TEXT_PAGE", "local_source_path": "private/source/main.pdf"},
        {"evidence_id": "si-table", "databases": ["deterministic-source-preprocessing"],
         "evidence_type": "NATIVE_TABLE", "local_source_path": "private/source/si.pdf"},
    ]
    default = _external_evidence_matrix(matrix, allow_local_evidence=False)
    permitted = _external_evidence_matrix(matrix, allow_local_evidence=True)
    assert [item["evidence_id"] for item in default] == ["metadata-abstract"]
    assert {item["evidence_id"] for item in permitted} == {
        "metadata-abstract", "fulltext-page", "si-table",
    }


def test_no_data_analysis_api_leaves_evidence_local_unregistered_without_fake_ids(tmp_path):
    main = _pdf(tmp_path / "main.pdf")
    result = build_source_package(
        main_pdf=main, supplementary_files=[], output_dir=tmp_path / "packages",
        doi="10.1000/unregistered",
    )
    package_dir = Path(result["package_dir"])
    report = {
        "records": [{
            "doi": "10.1000/unregistered", "source_package_id": result["paper_id"],
            "source_package_path": str(package_dir),
            "source_package_sha256": hashlib.sha256((package_dir / "evidence_index.json").read_bytes()).hexdigest(),
            "artifact_registration_status": "LOCAL_UNREGISTERED",
            "registration": {
                "status": "LOCAL_UNREGISTERED", "mock_only": False,
                "artifacts": [], "by_relative_path": {},
            },
        }],
    }
    rows = source_package_evidence(report)
    assert rows
    assert all(item["artifact_registration_status"] == "LOCAL_UNREGISTERED" for item in rows)
    assert all(item["source_artifact_ids"] == [] for item in rows)
    assert all(item["evidence_ref"] is None for item in rows)

def test_researchplan_determines_whether_si_is_a_blocking_dependency():
    config = AcquisitionConfig.from_mapping({"si_policy": "auto"}, base_dir=".")
    required, basis = decide_si_requirement(config, context={"research_question": "Does the conclusion depend on Supporting Information table S2?"})
    assert required is True
    assert "RESEARCH_QUESTION" in basis
    optional, _ = decide_si_requirement(config, context={"research_question": "Compare adsorption energy using reported main text methods"})
    assert optional is False
    forced, basis = decide_si_requirement(
        AcquisitionConfig.from_mapping({"si_policy": "required"}, base_dir="."),
        context={},
    )
    assert forced and basis == "SI_REQUIRED_BY_CONFIGURATION"


def test_source_package_registration_e2e_marks_mock_artifacts_and_links_evidence(tmp_path):
    from pipeline_contracts.literature_acquisition.acquisition_service import LiteratureAcquisitionService

    main = _pdf(tmp_path / "main.pdf", figure=True)
    si = _pdf(tmp_path / "support.pdf", "Supporting Information Figure S1. Supplementary method.")
    api = _MockDataAnalysis(tmp_path / "data-analysis-project" / "artifacts")

    class _Session:
        def __init__(self, *args, **kwargs):
            self.args = args
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get_proxy_base(self, publisher_key, *, resource_id=None, portal_url=None):
            assert resource_id == 123
            assert portal_url == "https://vpn.example"
            return "https://vpn.example/https/redacted/"

    class _Harvester:
        def __init__(self, output_dir):
            self.output_dir = output_dir
        def acquire(self, target, publisher_key, vpn, publisher_base):
            return {
                "status": "FULL_TEXT_PLUS_SI", "doi": target["doi"],
                "publisher": publisher_key, "main_pdf": str(main),
                "main_pdf_page_count": 1, "si_file": str(si),
                "si_available": True, "si_content_type": "PDF",
                "source_url": "https://www.elsevier.com/article/public",
                "acquired_at": "2026-11-28T00:00:00+00:00",
                "main_file": {"sha256": hashlib.sha256(main.read_bytes()).hexdigest()},
                "si_file_metadata": {"sha256": hashlib.sha256(si.read_bytes()).hexdigest()},
                "diagnostics": [], "method": "mock-publisher-contract",
            }

    formats = {
        "pdf": "mock/pdf", "json": "mock/json", "markdown": "mock/markdown",
        "zip": "mock/zip", "docx": "mock/docx", "image": "mock/image",
        "csv": "mock/csv", "text": "mock/text", "binary": "mock/binary",
    }
    config = AcquisitionConfig.from_mapping({
        "enabled": True, "output_dir": str(tmp_path / "acquisition"),
        "cookie_dir": str(tmp_path / "cookies"),
        "portal_url": "https://vpn.example",
        "publisher_resource_ids": {"elsevier": 123},
        "max_workers": 1, "min_delay_seconds": 0, "max_delay_seconds": 0,
        "preprocessing_enabled": True, "grobid_enabled": False,
        "artifact_format_ids": formats,
    }, base_dir=tmp_path)
    service = LiteratureAcquisitionService(
        config, data_analysis_api=api,
        data_analysis_project_root=tmp_path / "data-analysis-project",
        session_factory=_Session, harvester_factory=_Harvester,
        account_discoverer=lambda _: [{"account_id": "account-01", "cookie_file": "not-read-by-mock"}],
        sleeper=lambda _: None, random_uniform=lambda low, high: 0,
    )
    report = service.acquire(
        [{
            "doi": "10.1016/j.mock.2026.1", "title": "Synthetic publisher paper",
            "publisher": "Elsevier BV", "source_urls": ["https://www.sciencedirect.com/science/article/example"],
        }],
        run_root=tmp_path / "project-run",
        context={"research_question": "Does SI support the supplementary mechanistic detail?"},
        profile={}, enabled_override=True,
        project_run_id="mock-project-run-01",
    )
    assert report["status"] == "COMPLETE"
    record = next(item for item in report["records"] if item.get("doi"))
    assert record["artifact_registration_status"] == "REGISTERED"
    assert record["registration"]["mock_only"] is True
    assert record["si_dependency_status"] == "SATISFIED"
    package_dir = Path(record["source_package_path"])
    assert (package_dir / "source_files").is_dir()
    assert (package_dir / "evidence_index.json").is_file()
    assert record["source_package_sha256"]

    evidence_rows = source_package_evidence(report)
    assert evidence_rows
    assert any(item["doc_type"] == "MAIN" and item["source_artifact_ids"] for item in evidence_rows)
    assert any(item["doc_type"] == "SI" and item["source_artifact_ids"] for item in evidence_rows)
    assert all(item["artifact_registration_mock_only"] is True for item in evidence_rows)
    assert report["security"]["cookie_contents_logged"] is False
    assert report["security"]["daily_browser_profile_used"] is False

    # Continue the same offline acquisition into the existing ScientificResearchEngine
    # and write a normal, still-pending Decision Dossier for this same Project Run.
    from pipeline_contracts.scientific_planning import literature_engine as literature_module
    from pipeline_contracts.scientific_planning.literature_engine import ScientificResearchEngine

    profile = {
        "scientific_planning": {
            "intent": {
                "research_question": "How does surface oxygen coverage affect adsorption energy?",
                "research_goal": {"research_object": "oxide surface", "target_conclusion": "relative adsorption energy"},
            },
            "scientific_decisions": [{
                "field_path": "method.spin_resolution",
                "options": [
                    {"option_id": "spin-a", "label": "Restricted", "value": "restricted"},
                    {"option_id": "spin-b", "label": "Unrestricted", "value": "unrestricted"},
                ],
            }],
        },
    }
    manifest = {
        "source_document": {"sha256": "a" * 64},
        "systems": [{"name": "synthetic oxide surface"}],
        "claims": [], "evidence": [], "diagnostics": [],
        "unresolved_definitions": [{
            "code": "METHOD_PARAMETER_MISSING",
            "field_path": "method.spin_resolution",
            "description": "The spin-resolution policy is not declared.",
            "evidence_ids": [],
        }],
        "unresolved_structured_fields": [], "profile_reconciliation": [],
        "confirmations": [],
    }

    class _Lifecycle:
        def __init__(self):
            self.saved = []
        def manifest(self, run_id):
            return manifest
        def approved_scientific_decisions(self, run_id):
            return []
        def research_dossiers(self, run_id):
            return []
        def persist_research_dossier(self, run_id, dossier_id, dossier_sha256,
                                     json_path, markdown_path, metadata):
            self.saved.append({
                "run_id": run_id, "dossier_id": dossier_id,
                "dossier_sha256": dossier_sha256, "json_path": json_path,
                "markdown_path": markdown_path, "metadata": metadata,
            })

    class _Pipeline:
        def __init__(self):
            self.root = tmp_path / "project-run"
            self.lifecycle = _Lifecycle()
        def _run_root(self, run_id):
            path = self.root / run_id
            path.mkdir(parents=True, exist_ok=True)
            return path

    class _Engine(ScientificResearchEngine):
        def _profile_and_bundle(self, run_id, profile_path):
            return profile, None

    class _ReplayAcquisition:
        def __init__(self, config, **kwargs):
            self.config = config
        def acquire(self, records, **kwargs):
            return report

    search_record = {
        "title": "Synthetic publisher paper", "authors": ["A. Author"],
        "year": 2026, "doi": "10.1016/j.mock.2026.1",
        "abstract": "Synthetic metadata abstract only.",
        "publisher": "Elsevier BV", "database": "crossref",
        "database_sources": ["crossref"],
        "source_records": [{
            "database": "crossref", "source_url": "https://doi.org/10.1016/j.mock.2026.1",
            "publisher": "Elsevier BV",
        }],
        "version_relationships": [], "crossref_update_to": [],
    }
    pipeline_stub = _Pipeline()
    with patch.object(
        literature_module, "_search_with_lookup",
        return_value=([search_record], [{
            "database": "crossref", "query": "synthetic question",
            "status": "COMPLETE", "returned_count": 1,
        }]),
    ), patch.object(literature_module, "_reconcile_identifiers", return_value={"status": "MOCK_METADATA_VERIFIED"}):
        engine = _Engine(
            pipeline_stub, max_records=10, max_calls=2,
            full_text_service_factory=_ReplayAcquisition,
        )
        dossier_result = engine.run(
            "mock-project-run-01",
            full_text_enabled=True,
            literature_acquisition_config={
                "enabled": True, "output_dir": str(tmp_path / "acquisition"),
            },
            data_analysis_api=api,
            data_analysis_project_root=tmp_path / "data-analysis-project",
        )
    dossier = json.loads(Path(dossier_result["json_path"]).read_text(encoding="utf-8"))
    assert dossier["project_run_id"] == "mock-project-run-01"
    assert dossier["approval_state"] == "PENDING"
    assert dossier["execution_authority"]["scientific_decisions_approved"] is False
    assert dossier["search"]["literature_acquisition"]["status"] == "COMPLETE", (
        dossier["search"]["literature_acquisition"]
    )
    assert any(item.get("evidence_type") == "FULL_TEXT_PAGE" for item in dossier["evidence_matrix"])
    assert any(item.get("source_artifact_ids") for item in dossier["evidence_matrix"])
    assert all(
        item.get("artifact_registration_mock_only") is True
        for item in dossier["evidence_matrix"]
        if item.get("source_artifact_ids")
    )
    assert pipeline_stub.lifecycle.saved[0]["dossier_sha256"] == dossier["dossier_sha256"]

    # Persist reviewable Mock-only Source Package + Decision Dossier for CI artifact upload.
    demo_value = os.environ.get("LITERATURE_ACQUISITION_ARTIFACT_DIR")
    if demo_value:
        demo_root = Path(demo_value).expanduser().resolve()
        package_destination = demo_root / "source_package"
        package_destination.parent.mkdir(parents=True, exist_ok=True)
        if package_destination.exists():
            shutil.rmtree(package_destination)
        shutil.copytree(package_dir, package_destination)
        dossier_destination = demo_root / "decision_dossier"
        dossier_destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dossier_result["json_path"], dossier_destination / "decision_dossier.json")
        shutil.copy2(dossier_result["markdown_path"], dossier_destination / "decision_dossier.md")
        (demo_root / "demo_summary.json").write_text(json.dumps({
            "execution_mode": "MOCK_ONLY",
            "project_run_id": "mock-project-run-01",
            "source_package_status": record["source_package_status"],
            "source_package_sha256": record["source_package_sha256"],
            "registered_artifact_count": len(record["registration"]["artifacts"]),
            "all_registered_artifacts_mock": record["registration"]["mock_only"],
            "evidence_count": len(dossier["evidence_matrix"]),
            "decision_dossier_sha256": dossier["dossier_sha256"],
            "approval_state": dossier["approval_state"],
            "scientific_decisions_approved": dossier["execution_authority"]["scientific_decisions_approved"],
            "cp2k_or_hpc_executed": False,
        }, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
