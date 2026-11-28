"""Isolated Edge/Chromium CDP sessions for authorized WebVPN publisher access.

Directly migrated from chem-literature/core/vpn_session.py at
e099406adb689281c0337bcacc7868c3ccdbc438, with configurable routing and
credential-safe diagnostics. It never opens or mutates a user's daily profile.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import requests
import websocket

from .contracts import AcquisitionConfig


BLOCK_MARKERS = (
    "just a moment", "verify you are human", "captcha", "checking your browser",
    "non human", "unusual traffic", "access denied", "too many requests",
    "cf-chl", "restricted access", "automated requests",
)


class BrowserSessionError(RuntimeError):
    pass


class PublisherAccessBlocked(BrowserSessionError):
    def __init__(self, status: int | None, reason: str):
        self.status = status
        self.reason = reason
        super().__init__(f"publisher access blocked{f' (HTTP {status})' if status else ''}: {reason}")


class BrowserUnavailable(BrowserSessionError):
    pass


def discover_cookie_accounts(cookie_dir: str | Path) -> list[dict[str, str]]:
    """Discover local account Cookie JSON files without returning names or values to logs."""
    root = Path(cookie_dir).expanduser()
    if not root.is_dir():
        return []
    accounts = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies") if isinstance(payload, Mapping) else payload
            if not isinstance(cookies, list) or not cookies:
                continue
            valid = all(
                isinstance(item, Mapping) and
                all(key in item for key in ("name", "value", "domain")) and
                bool(str(item.get("name") or "")) and
                bool(str(item.get("domain") or ""))
                for item in cookies
            )
            if not valid:
                continue
            accounts.append({
                "account_id": f"account-{len(accounts) + 1:02d}",
                "cookie_file": str(path.resolve()),
            })
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            # Never echo file contents or parser excerpts; Cookie values are credentials.
            continue
    return accounts


def resolve_browser_executable(configured: str | None = None) -> str | None:
    if configured:
        candidate = Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
        return str(candidate) if candidate.is_file() else None

    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        ]
        relative = (
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Google/Chrome/Application/chrome.exe"),
        )
        for root in roots:
            if root:
                for rel in relative:
                    candidate = Path(root) / rel
                    if candidate.is_file():
                        return str(candidate.resolve())
        return shutil.which("msedge") or shutil.which("chrome")
    return shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable") or shutil.which("google-chrome") or shutil.which("chromium")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


class CDPClient:
    """Small bounded CDP client; no unbounded websocket receive loop."""

    def __init__(self, ws_url: str, timeout: int = 30):
        self.timeout = max(1, int(timeout))
        self.ws = websocket.create_connection(
            ws_url, timeout=self.timeout, suppress_origin=True,
            http_proxy_host=None, http_proxy_port=None,
        )
        self.ws.settimeout(self.timeout)
        self.msg_id = 0
        self._lock = threading.Lock()

    def call(self, method: str, params: Mapping[str, Any] | None = None,
             *, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            self.msg_id += 1
            current_id = self.msg_id
            self.ws.send(json.dumps({"id": current_id, "method": method, "params": dict(params or {})}))
            deadline = time.monotonic() + (float(timeout) if timeout is not None else self.timeout)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserSessionError(f"CDP call timed out: {method}")
                self.ws.settimeout(remaining)
                try:
                    message = json.loads(self.ws.recv())
                except websocket.WebSocketTimeoutException as exc:
                    raise BrowserSessionError(f"CDP call timed out: {method}") from exc
                except (websocket.WebSocketConnectionClosedException, OSError) as exc:
                    raise BrowserSessionError(f"CDP connection lost during {method}") from exc
                if message.get("id") != current_id:
                    continue
                if "error" in message:
                    # Do not include page contents, cookies, or arbitrary protocol payloads.
                    raise BrowserSessionError(f"CDP call failed: {method}")
                return dict(message.get("result") or {})

    def eval(self, expression: str, await_promise: bool = False,
             *, timeout: float | None = None) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": bool(await_promise),
        }, timeout=timeout)
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise BrowserSessionError("JavaScript evaluation failed")
        return remote.get("value")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.cdp:
                self.cdp.close()
                self.cdp = None
            if self.proc:
                process = self.proc
                self.proc = None
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, timeout=5, check=False,
                            )
                        else:
                            process.kill()
                            process.wait(timeout=3)
                    except Exception:
                        # Do not leak the session profile path or credentials in diagnostics.
                        pass
        finally:
            if self._profile_temp:
                try:
                    self._profile_temp.cleanup()
                except Exception:
                    pass
                self._profile_temp = None
            self.sandbox_profile = None

    def recover(self):
        """Perform one bounded restart of this isolated account session."""
        self.close()
        self._closed = False
        self.prefix_cache.clear()
        return self.__enter__()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.cdp:
            self.cdp.close()
            self.cdp = None
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                        capture_output=True, timeout=5, check=False,
                    )
                else:
                    try:
                        self.proc.kill()
                        self.proc.wait(timeout=3)
                    except Exception:
                        pass
            self.proc = None
        if self._profile_temp:
            self._profile_temp.cleanup()
            self._profile_temp = None
        self.sandbox_profile = None

    def navigate(self, url: str, wait_secs: float = 8) -> tuple[str, str, str]:
        if not self.cdp:
            raise BrowserSessionError("isolated CDP session is not connected")
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("publisher navigation requires an absolute HTTP(S) URL")
        self.cdp.call("Page.navigate", {"url": str(url)})
        if wait_secs > 0:
            time.sleep(min(float(wait_secs), 20.0))
        ready_deadline = time.monotonic() + 12.0
        ready = False
        while time.monotonic() < ready_deadline:
            state = self.cdp.eval("document.readyState", timeout=5)
            if state == "complete":
                ready = True
                break
            time.sleep(0.25)
        if not ready:
            raise BrowserSessionError("publisher page did not reach document.readyState=complete")
        href = str(self.cdp.eval("location.href") or "")
        title = str(self.cdp.eval("document.title") or "")
        body = str(self.cdp.eval("document.body ? document.body.innerText.slice(0, 3000) : ''") or "")
        visible = f"{title}\n{body}".casefold()
        marker = next((item for item in BLOCK_MARKERS if item in visible), None)
        if marker:
            raise PublisherAccessBlocked(None, "publisher challenge/access restriction detected")
        if "access denied" in visible or "forbidden" in visible:
            raise PublisherAccessBlocked(403, "publisher returned an access-denied page")
        return href, title, body.casefold()

    def get_proxy_base(self, publisher_key: str, *, resource_id: int | None = None,
                       portal_url: str | None = None) -> str:
        if publisher_key in self.prefix_cache:
            return self.prefix_cache[publisher_key]
        rid = resource_id or self.config.publisher_resource_ids.get(publisher_key)
        portal = (portal_url or self.config.portal_url or "").rstrip("/")
        if not portal or not rid:
            raise ValueError(f"WebVPN portal URL and resource ID for {publisher_key!r} must be configured")
        parsed_portal = urlparse(portal)
        if parsed_portal.scheme not in {"http", "https"} or not parsed_portal.hostname:
            raise ValueError("portal_url must be an absolute HTTP(S) URL")
        visit_url = f"{portal}/user/resource/visit?id={int(rid)}"
        href, _, _ = self.navigate(visit_url, wait_secs=8)
        visited = urlparse(href)
        if visited.hostname and visited.hostname.casefold() == (parsed_portal.hostname or "").casefold():
            parts = [part for part in visited.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"https", "http"}:
                base = f"{parsed_portal.scheme}://{parsed_portal.netloc}/{parts[0]}/{parts[1]}/"
            else:
                raise BrowserSessionError("WebVPN visit did not expose a configured publisher proxy route")
        else:
            base = href.split("?", 1)[0]
            if not base.endswith("/"):
                base += "/"
        self.prefix_cache[publisher_key] = base
        return base

    def fetch_binary(self, url: str, *, max_bytes: int | None = None) -> tuple[bytes | None, str]:
        if not self.cdp:
            raise BrowserSessionError("isolated CDP session is not connected")
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("binary retrieval requires an absolute HTTP(S) URL")
        maximum = int(max_bytes or self.config.max_download_bytes)
        fetch_js = """(async () => {
          try {
            const response = await fetch(URL_VALUE, {credentials: 'include', redirect: 'follow'});
            const ctype = response.headers.get('content-type') || '';
            if (!response.ok) return {status: response.status, data: null, ctype};
            const declared = Number(response.headers.get('content-length') || 0);
            if (declared > MAX_BYTES) return {status: 413, data: null, ctype};
            const buffer = await response.arrayBuffer();
            if (buffer.byteLength > MAX_BYTES) return {status: 413, data: null, ctype};
            const bytes = new Uint8Array(buffer);
            let binary = '';
            const step = 32768;
            for (let i=0; i<bytes.length; i+=step) {
              binary += String.fromCharCode.apply(null, bytes.subarray(i, i+step));
            }
            return {status: response.status, data: btoa(binary), ctype};
          } catch (error) {
            return {status: 0, data: null, ctype: ''};
          }
        })()""".replace("URL_VALUE", json.dumps(str(url))).replace("MAX_BYTES", str(maximum))
        raw = self.cdp.eval(fetch_js, await_promise=True, timeout=self.config.cdp_timeout_seconds)
        if not isinstance(raw, Mapping):
            raise BrowserSessionError("publisher binary fetch returned an invalid CDP result")
        status = int(raw.get("status") or 0)
        ctype = str(raw.get("ctype") or "")
        self.last_http_status = status
        self.last_content_type = ctype
        if status in {401, 403, 407, 429, 451, 503}:
            raise PublisherAccessBlocked(status, "publisher binary endpoint refused or throttled the request")
        if status == 413:
            raise BrowserSessionError("publisher binary exceeded configured maximum download size")
        if status == 0:
            raise BrowserSessionError("publisher binary request failed or CDP transport was interrupted")
        if status == 404:
            return None, ctype
        data = raw.get("data")
        if status != 200 or not data:
            return None, ctype
        import base64
        try:
            result = base64.b64decode(str(data), validate=True)
        except Exception:
            raise BrowserSessionError("publisher binary response could not be decoded") from None
        if len(result) > maximum:
            raise BrowserSessionError("publisher binary exceeded configured maximum download size")
        return result, ctype
