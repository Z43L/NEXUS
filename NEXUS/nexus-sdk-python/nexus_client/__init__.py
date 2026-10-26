"""Async Python client for the local NEXUS OpenAI-compatible gateway."""

from __future__ import annotations

import asyncio
from ipaddress import ip_address
import json
from typing import Any, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HTTP_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("base_url must be a valid HTTP(S) origin") from None
    if (parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or port == 0):
        raise ValueError("base_url must be a valid HTTP(S) origin")
    if parsed.scheme == "http":
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host.lower() == "localhost"
        if not loopback:
            raise ValueError("base_url must use HTTPS unless it targets loopback")
    return value.rstrip("/")


class NexusAPIError(RuntimeError):
    """An HTTP or gateway error returned by NEXUS."""

    def __init__(self, message: str, status_code: int, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class NexusClient:
    """Async client for `POST /v1/chat/completions`.

    By default requests go through the FastAPI facade on loopback, which can
    require `NEXUS_API_TOKEN`. Set `base_url` to the Router URL only for a
    trusted local development setup that intentionally bypasses that facade.
    """

    def __init__(self, api_key: Optional[str] = None,
                 base_url: str = DEFAULT_BASE_URL, timeout: float = 300):
        self.api_key = api_key
        self.base_url = _validate_base_url(base_url)
        self.timeout = timeout

    async def __aenter__(self) -> "NexusClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    async def chat(self, messages: str | Sequence[dict[str, str]], *,
                   model: str = "", max_tokens: int = 256,
                   temperature: float = 0.3, timeout_s: int = 300) -> dict[str, Any]:
        """Create a non-streaming chat completion and return the OpenAI-style payload."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, int)
                or not 1 <= timeout_s <= 1800):
            raise ValueError("timeout_s must be an integer from 1 to 1800")
        return await self._request("POST", "/v1/chat/completions", timeout=max(
            self.timeout, timeout_s + 10
        ), json={
            "model": model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout_s": timeout_s,
        })

    async def query(self, query: str, **kwargs) -> dict[str, Any]:
        """Send a knowledge question as an ordinary inference request."""
        return await self.chat(query, **kwargs)

    async def infer(self, task: str, **kwargs) -> dict[str, Any]:
        """Send an inference task as an ordinary chat completion."""
        return await self.chat(task, **kwargs)

    async def _request(self, method: str, endpoint: str, *, timeout: Optional[float] = None,
                       **kwargs) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        url = f"{self.base_url}{endpoint}"
        body = kwargs.get("json")
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method=method, headers=headers)
        return await asyncio.to_thread(self._send, req, timeout or self.timeout)

    def _send(self, request: Request, timeout: float) -> dict[str, Any]:
        try:
            with _HTTP_OPENER.open(request, timeout=timeout) as response:
                status = response.status
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        except URLError as exc:
            raise NexusAPIError(str(exc.reason), 0) from exc
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        if status < 200 or status >= 300:
            raise NexusAPIError(_error_message(payload), status, payload)
        return payload


def _error_message(payload: Any) -> str:
    """Extract errors from Router, FastAPI, and OpenAI-compatible envelopes."""
    if not isinstance(payload, dict):
        return str(payload) if payload else "NEXUS request failed"
    error = payload.get("error")
    detail = payload.get("detail")
    if not error and isinstance(detail, dict):
        error = detail.get("error", detail)
    elif not error:
        error = detail
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or error)
    return str(error or "NEXUS request failed")


__all__ = ["NexusClient", "NexusAPIError", "DEFAULT_BASE_URL"]
