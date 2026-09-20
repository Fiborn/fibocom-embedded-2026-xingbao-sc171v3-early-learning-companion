"""HTTP helpers adapted from pc5.py for modular DashScope clients."""

from __future__ import annotations

import os
import json
import time
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from core.settings import AppSettings


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"
_PROXY_ENV_NAMES = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def enforce_direct_network_env() -> None:
    """Prevent HTTP and DashScope WebSocket clients from inheriting proxies."""
    for name in _PROXY_ENV_NAMES:
        os.environ.pop(name, None)
    # Libraries that honour NO_PROXY will now also explicitly bypass any
    # system-level proxy configuration for every destination.
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def proxy_dict(proxy: str) -> dict[str, str]:
    if not proxy:
        return {}
    return {"http": proxy, "https": proxy}


def import_requests() -> Any:
    try:
        import requests

        return requests
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError("Missing dependency: requests") from exc


class NetworkClient:
    """Retrying HTTP client with optional proxy auto-selection."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        requests_module: Any | None = None,
    ) -> None:
        self.settings = settings or AppSettings.load()
        if self.settings.proxy_mode == "none":
            enforce_direct_network_env()
        self.requests = requests_module or import_requests()
        self.http = self._build_http_client(self.requests)
        self._selected_proxies: dict[str, str] | None = None
        self._selected_proxy_label: str | None = None
        self._proxy_lock = threading.Lock()

    @property
    def selected_proxy_label(self) -> str | None:
        return self._selected_proxy_label

    def select_proxies(self, force: bool = False) -> dict[str, str]:
        if self._selected_proxies is not None and not force:
            return self._selected_proxies

        with self._proxy_lock:
            if self._selected_proxies is not None and not force:
                return self._selected_proxies

            if self.settings.proxy_mode == "none":
                return self._remember_proxy({}, "direct")

            if self.settings.proxy_mode == "manual":
                label = self.settings.manual_proxy or "direct"
                return self._remember_proxy(proxy_dict(self.settings.manual_proxy), label)

            candidates = list(self.settings.auto_proxy_candidates)
            for env_name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
                value = os.environ.get(env_name, "").strip()
                if value and value not in candidates:
                    candidates.insert(0, value)

            headers = {"Authorization": "Bearer dummy", "Content-Type": "application/json"}
            for candidate in candidates:
                proxies = proxy_dict(candidate)
                label = candidate or "direct"
                try:
                    response = self.http.get(
                        DASHSCOPE_BASE_URL,
                        headers=headers,
                        proxies=proxies,
                        timeout=6,
                        verify=True,
                    )
                    if response.status_code < 500:
                        return self._remember_proxy(proxies, label)
                except Exception:
                    continue

            fallback = candidates[0] if candidates else ""
            return self._remember_proxy(proxy_dict(fallback), fallback or "direct")

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        timeout: int = 60,
        retries: int = 3,
    ) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                proxies = self.select_proxies()
                if method.upper() == "POST":
                    response = self.http.post(
                        url,
                        headers=headers,
                        json=payload,
                        proxies=proxies,
                        timeout=timeout,
                    )
                elif method.upper() == "GET":
                    response = self.http.get(
                        url,
                        headers=headers,
                        proxies=proxies,
                        timeout=timeout,
                    )
                else:
                    raise ValueError(f"Unsupported method: {method}")

                text_preview = response.text[:800] if response.text else ""
                if not response.ok:
                    raise RuntimeError(f"HTTP {response.status_code}: {text_preview}")
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError("Response JSON is not an object.")
                return data
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(1.0)
                    self.select_proxies(force=True)

        raise RuntimeError(f"Network request failed: {url}; last error: {last_error}")

    def download_file(
        self,
        url: str,
        out_path: Path,
        timeout: int = 120,
        retries: int = 3,
        interrupt_event: threading.Event | None = None,
    ) -> None:
        last_error: Exception | None = None
        attempts = max(1, int(retries))
        for attempt in range(1, attempts + 1):
            try:
                if interrupt_event is not None and interrupt_event.is_set():
                    raise RuntimeError("Download cancelled.")
                response = self.http.get(
                    url,
                    proxies=self.select_proxies(),
                    timeout=timeout,
                    stream=True,
                )
                if not response.ok:
                    raise RuntimeError(f"Download failed HTTP {response.status_code}")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with out_path.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if interrupt_event is not None and interrupt_event.is_set():
                            raise RuntimeError("Download cancelled.")
                        if chunk:
                            file.write(chunk)
                return
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(1.0)
                self.select_proxies(force=True)
        raise RuntimeError(f"Download failed: {url}; last error: {last_error}")

    def stream_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        timeout: int = 120,
        retries: int = 3,
    ) -> Iterator[dict[str, Any]]:
        """Yield JSON objects from a server-sent event response."""
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                proxies = self.select_proxies()
                if method.upper() != "POST":
                    raise ValueError(f"Unsupported streaming method: {method}")

                response = self.http.post(
                    url,
                    headers=headers,
                    json=payload,
                    proxies=proxies,
                    timeout=timeout,
                    stream=True,
                )
                if not response.ok:
                    text_preview = response.text[:800] if response.text else ""
                    raise RuntimeError(f"HTTP {response.status_code}: {text_preview}")

                for raw_line in response.iter_lines(decode_unicode=True):
                    line = _normalize_sse_line(raw_line)
                    if not line:
                        continue
                    if line == "[DONE]":
                        return
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        raise RuntimeError("Stream JSON item is not an object.")
                    yield data
                return
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(1.0)
                    self.select_proxies(force=True)

        raise RuntimeError(f"Streaming request failed: {url}; last error: {last_error}")

    def _remember_proxy(self, proxies: dict[str, str], label: str) -> dict[str, str]:
        self._selected_proxies = proxies
        self._selected_proxy_label = label
        return proxies

    @staticmethod
    def _build_http_client(requests_module: Any) -> Any:
        session_factory = getattr(requests_module, "Session", None)
        if session_factory is None:
            return requests_module
        try:
            session = session_factory()
            # ``requests`` otherwise merges HTTP(S)_PROXY from its process
            # environment even when callers pass an empty proxy dictionary.
            if hasattr(session, "trust_env"):
                session.trust_env = False
            return session
        except Exception:
            return requests_module


def _normalize_sse_line(raw_line: Any) -> str:
    if raw_line is None:
        return ""
    if isinstance(raw_line, bytes):
        line = raw_line.decode("utf-8", errors="replace")
    else:
        line = str(raw_line)
    line = line.strip()
    if not line or line.startswith(":"):
        return ""
    if line.startswith("data:"):
        return line[5:].strip()
    return line
