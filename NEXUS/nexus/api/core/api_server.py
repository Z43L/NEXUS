"""NEXUS HTTP API backed by the local H0 inference gateway.

The H0 router owns job dispatch, worker authentication, receipts and the local
ledger. This FastAPI app is a compatibility facade; it does not initialize the
unfinished legacy Weaviate/AGE/ReAct stack during startup.
"""

from __future__ import annotations

import asyncio
import json
import os
import hashlib
import hmac
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

H0_ROUTER_URL = os.environ.get("NEXUS_H0_ROUTER_URL", "http://127.0.0.1:18080").rstrip("/")
_RATE_WINDOW_SECONDS = 60
_rate_lock = threading.Lock()
_rate_buckets: Dict[str, tuple[int, int]] = {}

app = FastAPI(
    title="NEXUS API",
    description="Compatibility API backed by the local NEXUS H0 gateway",
    version="1.1.0",
)


@app.exception_handler(HTTPException)
async def preserve_gateway_error(request: Request, exc: HTTPException):
    """Keep the Router's OpenAI error envelope intact across this facade."""
    del request
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "NEXUS_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


def _client_authorization(request: Request) -> Optional[str]:
    """Return one syntactically valid client credential for upstream forwarding."""
    authorization = request.headers.get("authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    api_key = request.headers.get("x-api-key", "").strip()
    return api_key or None


def _enforce_client_auth(request: Request) -> None:
    expected = os.environ.get("NEXUS_API_TOKEN", "")
    if not expected:
        return
    supplied = _client_authorization(request)
    if supplied is None or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _consume_rate_limit(request: Request) -> tuple[int, int, int, bool]:
    """Process-local fixed-window limiter for inference endpoints."""
    try:
        limit = int(os.environ.get("NEXUS_API_RATE_LIMIT_PER_MINUTE", "60"))
    except ValueError:
        limit = 60
    limit = min(max(limit, 1), 10000)
    now = int(time.time())
    window = now // _RATE_WINDOW_SECONDS
    # Without a configured API token, arbitrary caller-supplied keys must not
    # let a local client evade the shared per-address budget.
    credential = _client_authorization(request) if os.environ.get("NEXUS_API_TOKEN") else None
    identity = hashlib.sha256(credential.encode()).hexdigest() if credential else (
        request.client.host if request.client else "unknown"
    )
    key = f"{identity}:{window}"
    with _rate_lock:
        # Keep memory bounded when clients create many distinct identities.
        expired = [
            candidate
            for candidate in _rate_buckets
            if not candidate.endswith(f":{window}")
        ]
        for old_key in expired:
            _rate_buckets.pop(old_key, None)
        count, _ = _rate_buckets.get(key, (0, window))
        count += 1
        _rate_buckets[key] = (count, window)
    reset = (window + 1) * _RATE_WINDOW_SECONDS
    return limit, max(0, limit - count), reset, count <= limit


@app.middleware("http")
async def local_api_controls(request: Request, call_next):
    # Health/readiness stay usable by local process supervisors. CORS preflight
    # is not an inference request and must not consume a rate-limit slot.
    if request.method == "OPTIONS" or request.url.path in {"/health", "/ready"}:
        return await call_next(request)
    try:
        _enforce_client_auth(request)
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    if request.method == "POST" and request.url.path in {
        "/v1/chat/completions", "/cognitive/query", "/cognitive/infer"
    }:
        limit, remaining, reset, allowed = _consume_rate_limit(request)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(max(1, reset - int(time.time()))),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset),
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        return response
    return await call_next(request)


class StandardResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    request_id: str
    timestamp: datetime


def _upstream_auth(authorization: Optional[str]) -> Optional[str]:
    # An explicit service credential takes precedence over the caller's token.
    return os.environ.get("NEXUS_H0_CLIENT_TOKEN") or authorization


def _bounded_timeout(value: Any, field: str) -> int:
    """Parse a whole-number timeout and clamp it to the Router's supported range."""
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        raise HTTPException(status_code=422, detail=f"{field} must be an integer")
    try:
        timeout = int(value)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail=f"{field} must be an integer") from None
    return min(max(timeout, 1), 1800)


def _post_gateway(payload: Dict[str, Any], timeout: int,
                  authorization: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    upstream_token = _upstream_auth(authorization)
    if upstream_token:
        headers["Authorization"] = f"Bearer {upstream_token}"
    request = urllib.request.Request(
        f"{H0_ROUTER_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            detail = {"message": "H0 gateway request failed"}
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway is unavailable") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway returned invalid JSON") from exc
    return result


def _get_gateway(path: str, authorization: Optional[str] = None) -> Dict[str, Any]:
    headers = {}
    upstream_token = _upstream_auth(authorization)
    if upstream_token:
        headers["Authorization"] = f"Bearer {upstream_token}"
    request = urllib.request.Request(f"{H0_ROUTER_URL}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="H0 gateway request failed") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway is unavailable") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway returned invalid JSON") from exc


async def _complete(messages: list, parameters: Optional[Dict[str, Any]], timeout: int,
                    authorization: Optional[str] = None):
    params = parameters or {}
    payload = {
        "model": params.get("model", ""),
        "messages": messages,
        "temperature": params.get("temperature", 0.3),
        "max_tokens": params.get("max_tokens", 256),
        "timeout_s": timeout,
    }
    return await asyncio.to_thread(_post_gateway, payload, timeout + 5, authorization)


@app.post("/v1/chat/completions")
async def chat_completions(payload: Dict[str, Any], request: Request):
    """Proxy the basic non-streaming OpenAI-compatible H0 chat request."""
    if payload.get("stream"):
        raise HTTPException(status_code=400, detail="H0 gateway does not support streaming")
    if payload.get("tools"):
        raise HTTPException(status_code=400, detail="H0 gateway does not support tools")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=422, detail="messages must be a non-empty array")
    timeout = _bounded_timeout(payload.get("timeout_s", 300), "timeout_s")
    forwarded = dict(payload)
    forwarded["timeout_s"] = timeout
    return await asyncio.to_thread(
        _post_gateway, forwarded, timeout + 5, _client_authorization(request)
    )


@app.get("/v1/models")
async def list_models(request: Request):
    return await asyncio.to_thread(
        _get_gateway, "/v1/models", _client_authorization(request)
    )


@app.post("/cognitive/query", response_model=StandardResponse, tags=["Cognitive Functions"])
async def query_knowledge(payload: Dict[str, Any], request: Request):
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=422, detail="query must be a non-empty string")
    context = payload.get("context")
    if context is not None:
        if not isinstance(context, dict):
            raise HTTPException(status_code=422, detail="context must be an object")
        query += "\n\nContext:\n" + json.dumps(context, ensure_ascii=False)
    result = await _complete(
        [{"role": "user", "content": query}], None, 300,
        _client_authorization(request),
    )
    return StandardResponse(
        success=True,
        data={"results": result},
        request_id=str(uuid4()),
        timestamp=datetime.now(),
    )


@app.post("/cognitive/infer", response_model=StandardResponse, tags=["Cognitive Functions"])
async def perform_inference(payload: Dict[str, Any], request: Request):
    task = payload.get("task")
    if not isinstance(task, str) or not task.strip():
        raise HTTPException(status_code=422, detail="task must be a non-empty string")
    timeout = _bounded_timeout(payload.get("timeout", 60), "timeout")
    parameters = payload.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise HTTPException(status_code=422, detail="parameters must be an object")
    result = await _complete(
        [{"role": "user", "content": task}], parameters, timeout,
        _client_authorization(request),
    )
    return StandardResponse(
        success=True,
        data={"inference_result": result},
        request_id=str(uuid4()),
        timestamp=datetime.now(),
    )


def _gateway_ready() -> bool:
    request = urllib.request.Request(f"{H0_ROUTER_URL}/ready", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            result = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and result.get("ok") is True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeDecodeError):
        return False


@app.get("/health", response_model=StandardResponse, tags=["System"])
async def health_check():
    return StandardResponse(
        success=True,
        data={"status": "healthy", "gateway_url": H0_ROUTER_URL},
        request_id="health_check",
        timestamp=datetime.now(),
    )


@app.get("/ready", response_model=StandardResponse, tags=["System"])
async def readiness_check():
    ready = await asyncio.to_thread(_gateway_ready)
    if not ready:
        raise HTTPException(status_code=503, detail="H0 gateway is not ready")
    return StandardResponse(
        success=True,
        data={"status": "ready", "gateway_url": H0_ROUTER_URL},
        request_id="readiness_check",
        timestamp=datetime.now(),
    )
