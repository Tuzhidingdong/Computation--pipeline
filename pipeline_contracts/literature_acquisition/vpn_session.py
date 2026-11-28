"""Isolated Edge/Chromium CDP sessions for authorized WebVPN publisher access.

Directly migrated from chem-literature/core/vpn_session.py at
e099406adb689281c0337bcacc7868c3ccdbc438, with configurable routing and
credential-safe diagnostics. It never opens or mutates a user's daily profile.
"""
from __future__ import annotations

import base64
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
        super().__init__(
            f"publisher access blocked{f' (HTTP {status})' if status else ''}: {reason}"
        )


class BrowserUnavailable(BrowserSessionError):
    pass


def discover_cookie_accounts(cookie_dir: str | Path) -> list[dict[str, str]]:
    """Discover local Cookie JSON accounts without returning names/values to logs."""
    root = Path(cookie_dir).expanduser()
    if not root.is_dir():
        return []
    accounts: list[dict[str, str]] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            cookies = payload.get("cookies") if isinstance(payload, Mapping) else payload
            if not isinstance(cookies, list) or not cookies:
                continue
            valid = all(
                isinstance(item, Mapping)
                and all(key in item for key in ("name", "value", "domain"))
                and bool(str(item.get("name") or ""))
                and bool(str(item.get("domain") or ""))
                for item in cookies
            )
            if not valid:
                continue
            accounts.append({
                "account_id": f"account-{len(accounts) + 1:02d}",
                "cookie_file": str(path.resolve()),
            })
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            # Never echo Cookie file contents or parser excerpts; values are credentials.
            continue
    return accounts


def resolve_browser_executable(configured: str | None = None) -> str | None:
    """Resolve an explicitly configured binary or a platform browser installation."""
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
    return (
        shutil.which("microsoft-edge")
        or shutil.which("microsoft-edge-stable")
        or shutil.which("google-chrome")
        or shutil.which("chromium")
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


class CDPClient:
    """Small bounded CDP client; no unbounded websocket receive loop."""

    def __init__(self, ws_url: str, timeout: int = 30):
        self.timeout = max(1, int(timeout))
        self.ws = websocket.create_connection(
            ws_url,
            timeout=self.timeout,
            suppress_origin=True,
            http_proxy_host=None,
            http_proxy_port=None,
        )
        self.ws.settimeout(self.timeout)
        self.msg_id = 0
        self._lock = threading.Lock()

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.msg_id += 1
            current_id = self.msg_id
            self.ws.send(json.dumps({
                "id": current_id,
                "method": method,
                "params": dict(params or {}),
            }))
            deadline = time.monotonic() + (
                float(timeout) if timeout is not None else self.timeout
            )
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserSessionError(f"CDP call timed out: {method}")
                self.ws.settimeout(remaining)
                try:
                    message = json.loads(self.ws.recv())
                except websocket.WebSocketTimeoutException as exc:
                    raise BrowserSessionError(f"CDP call timed out: {method}") from exc
                except (
                    websocket.WebSocketConnectionClosedException,
                    OSError,
                ) as exc:
                    raise BrowserSessionError(
                        f"CDP connection lost during {method}"
                    ) from exc
                if message.get("id") != current_id:
                    continue
                if "error" in message:
                    # Do not include response payloads, cookies or page content.
                    raise BrowserSessionError(f"CDP call failed: {method}")
                return dict(message.get("result") or {})

    def eval(
        self,
        expression: str,
        await_promise: bool = False,
        *,
        timeout: float | None = None,
    ) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": bool(await_promise),
        }, timeout=timeout)
        remote = result.get("result") or {}
        if remote.get("subtype") == "error":
            raise BrowserSessionError("JavaScript evaluation failed")
        return remote.get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


class VpnBrowserSession:
    """One Cookie account, browser process, temporary profile and CDP port."""

    def __init__(
        self,
        cookie_file: str | Path,
        *,
        config: AcquisitionConfig,
        account_id: str = "account",
        workspace_dir: str | Path | None = None,
        cdp_factory=CDPClient,
    ):
        self.cookie_file = Path(cookie_file).expanduser().resolve()
        self.config = config
        self.account_id = str(account_id)
        self.workspace_dir = Path(
            workspace_dir or config.output_dir
        ).expanduser().resolve()
        self.cdp_factory = cdp_factory
        self.sandbox_port = _free_port()
        self.sandbox_profile: str | None = None
        self._profile_temp: tempfile.TemporaryDirectory | None = None
        self.proc: subprocess.Popen | None = None
        self.cdp: CDPClient | None = None
        self.prefix_cache: dict[str, str] = {}
        self.last_http_status: int | None = None
        self.last_content_type: str | None = None
        self.browser_executable: str | None = None
        self._closed = False

    def _read_cookies(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.cookie_file.read_text(encoding="utf-8"))
            cookies = payload.get("cookies") if isinstance(payload, Mapping) else payload
            if not isinstance(cookies, list) or not cookies:
                raise ValueError("Cookie array missing")
            result: list[dict[str, Any]] = []
            for cookie in cookies:
                if not isinstance(cookie, Mapping):
                    raise ValueError("Cookie record invalid")
                name = cookie.get("name")
                value = cookie.get("value")
                domain = cookie.get("domain")
                if not all(isinstance(item, str) and item for item in (name, value, domain)):
                    raise ValueError("Cookie fields missing")
                result.append(dict(cookie))
            return result
        except Exception:
            # Do not expose the JSON parser's excerpt; it might contain Cookie values.
            raise BrowserSessionError(
                "Cookie file is unreadable or has an unsupported format"
            ) from None

    def __enter__(self):
        self._closed = False
        self.prefix_cache.clear()
        self.last_http_status = None
        self.last_content_type = None

        if not self.cookie_file.is_file() or self.cookie_file.is_symlink():
            raise BrowserUnavailable(
                "configured Cookie account file is missing or not a regular file"
            )
        cookies = self._read_cookies()
        self.browser_executable = resolve_browser_executable(
            self.config.browser_executable
        )
        if not self.browser_executable:
            raise BrowserUnavailable(
                "configured Edge/Chromium executable is unavailable"
            )

        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._profile_temp = tempfile.TemporaryDirectory(
            prefix="pipeline-literature-cdp-",
            dir=str(self.workspace_dir),
        )
        self.sandbox_profile = self._profile_temp.name

        args = [
            self.browser_executable,
            f"--remote-debugging-port={self.sandbox_port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={self.sandbox_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-component-update",
            "--window-position=-32000,-32000",
            "--window-size=1280,900",
        ]
        if self.config.browser_headless:
            args.append("--headless=new")
        args.append("about:blank")

        try:
            self.proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=(os.name != "nt"),
            )
            ws_url = self._wait_for_debugger()
            self.cdp = self.cdp_factory(
                ws_url, timeout=self.config.cdp_timeout_seconds
            )
            self.cdp.call("Page.enable")
            self.cdp.call("Network.enable")

            cookie_params = []
            for cookie in cookies:
                item = {
                    key: cookie[key]
                    for key in (
                        "name", "value", "domain", "path", "secure", "httpOnly"
                    )
                    if key in cookie
                }
                if cookie.get("sameSite") in {"Strict", "Lax", "None"}:
                    item["sameSite"] = cookie["sameSite"]
                if not cookie.get("session"):
                    try:
                        expires = float(cookie.get("expires", -1) or -1)
                    except (TypeError, ValueError):
                        expires = -1
                    if expires > 0:
                        item["expires"] = expires
                cookie_params.append(item)

            self.cdp.call("Network.setCookies", {"cookies": cookie_params})
            return self
        except Exception:
            self.close()
            raise

    def _wait_for_debugger(self) -> str:
        endpoint = f"http://127.0.0.1:{self.sandbox_port}/json"
        deadline = time.monotonic() + self.config.browser_start_timeout_seconds
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                break
            try:
                response = requests.get(endpoint, timeout=1.5)
                if response.status_code == 200:
                    pages = [
                        item for item in response.json()
                        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
                    ]
                    if pages:
                        return str(pages[0]["webSocketDebuggerUrl"])
            except Exception:
                pass
            time.sleep(0.25)
        raise BrowserUnavailable(
            f"isolated browser did not expose CDP on port {self.sandbox_port}"
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

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
                                capture_output=True,
                                timeout=5,
                                check=False,
                            )
                        else:
                            process.kill()
                            process.wait(timeout=3)
                    except Exception:
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

    def navigate(
        self, url: str, wait_secs: float = 8
    ) -> tuple[str, str, str]:
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
            raise BrowserSessionError(
                "publisher page did not reach document.readyState=complete"
            )

        href = str(self.cdp.eval("location.href") or "")
        title = str(self.cdp.eval("document.title") or "")
        body = str(
            self.cdp.eval(
                "document.body ? document.body.innerText.slice(0, 3000) : ''"
            ) or ""
        )
        visible = f"{title}\n{body}".casefold()
        marker = next((item for item in BLOCK_MARKERS if item in visible), None)
        if marker:
            raise PublisherAccessBlocked(
                None, "publisher challenge/access restriction detected"
            )
        if "access denied" in visible or "forbidden" in visible:
            raise PublisherAccessBlocked(403, "publisher returned an access-denied page")
        return href, title, body.casefold()

    def get_proxy_base(
        self,
        publisher_key: str,
        *,
        resource_id: int | None = None,
        portal_url: str | None = None,
    ) -> str:
        if publisher_key in self.prefix_cache:
            return self.prefix_cache[publisher_key]
        rid = resource_id or self.config.publisher_resource_ids.get(publisher_key)
        portal = (portal_url or self.config.portal_url or "").rstrip("/")
        if not portal or not rid:
            raise ValueError(
                f"WebVPN portal URL and resource ID for {publisher_key!r} must be configured"
            )
        parsed_portal = urlparse(portal)
        if parsed_portal.scheme not in {"http", "https"} or not parsed_portal.hostname:
            raise ValueError("portal_url must be an absolute HTTP(S) URL")
        visit_url = f"{portal}/user/resource/visit?id={int(rid)}"
        href, _, _ = self.navigate(visit_url, wait_secs=8)
        visited = urlparse(href)
        if (
            visited.hostname
            and visited.hostname.casefold() == parsed_portal.hostname.casefold()
        ):
            parts = [part for part in visited.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"https", "http"}:
                base = (
                    f"{parsed_portal.scheme}://{parsed_portal.netloc}/"
                    f"{parts[0]}/{parts[1]}/"
                )
            else:
                raise BrowserSessionError(
                    "WebVPN visit did not expose a configured publisher proxy route"
                )
        else:
            base = href.split("?", 1)[0]
            if not base.endswith("/"):
                base += "/"
        self.prefix_cache[publisher_key] = base
        return base

    def fetch_binary(
        self,
        url: str,
        *,
        max_bytes: int | None = None,
    ) -> tuple[bytes | None, str]:
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
        })()""".replace("URL_VALUE", json.dumps(str(url))).replace(
            "MAX_BYTES", str(maximum)
        )
        raw = self.cdp.eval(
            fetch_js,
            await_promise=True,
            timeout=self.config.cdp_timeout_seconds,
        )
        if not isinstance(raw, Mapping):
            raise BrowserSessionError("publisher binary fetch returned an invalid CDP result")
        status = int(raw.get("status") or 0)
        ctype = str(raw.get("ctype") or "")
        self.last_http_status = status
        self.last_content_type = ctype
        if status in {401, 403, 407, 429, 451, 503}:
            raise PublisherAccessBlocked(
                status, "publisher binary endpoint refused or throttled the request"
            )
        if status == 413:
            raise BrowserSessionError(
                "publisher binary exceeded configured maximum download size"
            )
        if status == 0:
            raise BrowserSessionError(
                "publisher binary request failed or CDP transport was interrupted"
            )
        if status == 404:
            return None, ctype
        data = raw.get("data")
        if status != 200 or not data:
            return None, ctype
        try:
            result = base64.b64decode(str(data), validate=True)
        except Exception:
            raise BrowserSessionError(
                "publisher binary response could not be decoded"
            ) from None
        if len(result) > maximum:
            raise BrowserSessionError(
                "publisher binary exceeded configured maximum download size"
            )
        return result, ctype
