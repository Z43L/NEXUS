"""NEXUS HTTP API backed by the local H0 inference gateway.

The H0 router owns job dispatch, worker authentication, receipts and the local
ledger. This FastAPI app is a compatibility facade; it does not initialize the
unfinished legacy Weaviate/AGE/ReAct stack during startup.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from ipaddress import ip_address
import json
import hashlib
import hmac
import os
from pathlib import Path
import re
import ssl
import stat
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

def _validate_router_url(value: str) -> str:
    """Allow local HTTP for development and verified HTTPS for private deployments."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        raise RuntimeError("NEXUS_H0_ROUTER_URL is malformed") from None
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or port == 0):
        raise RuntimeError("NEXUS_H0_ROUTER_URL must be a plain HTTP(S) origin")
    if parsed.scheme == "http" and not loopback:
        raise RuntimeError("NEXUS_H0_ROUTER_URL must use HTTPS outside loopback")
    return value.rstrip("/")


H0_ROUTER_URL = _validate_router_url(
    os.environ.get("NEXUS_H0_ROUTER_URL", "http://127.0.0.1:18080")
)
_RATE_WINDOW_SECONDS = 60
_rate_lock = threading.Lock()
_rate_buckets: Dict[str, tuple[int, int]] = {}
_CLIENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_CLIENT_SCOPES = {"inference", "models:read", "jobs:read", "auth:session", "admin"}

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


def _load_api_clients() -> list[dict]:
    """Load a private registry containing token digests, never plaintext keys."""
    registry_path = os.environ.get("NEXUS_API_CLIENTS_FILE", "")
    if not registry_path:
        return []
    path = Path(registry_path)
    try:
        if path.is_symlink():
            raise ValueError("API client registry must not be a symlink")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("API client registry permissions must be 0600")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("API client registry is unavailable or invalid") from exc
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("clients"), list) or len(data["clients"]) > 1000):
        raise RuntimeError("API client registry schema is invalid")
    clients = []
    ids, hashes = set(), set()
    for client in data["clients"]:
        if not isinstance(client, dict):
            raise RuntimeError("API client registry entry is invalid")
        client_id = client.get("client_id")
        token_hash = client.get("token_sha256")
        scopes = client.get("scopes")
        quota = client.get("rate_limit_per_minute")
        if (not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id)
                or not isinstance(token_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", token_hash)
                or not isinstance(scopes, list) or not scopes
                or any(not isinstance(scope, str) or scope not in _CLIENT_SCOPES for scope in scopes)
                or len(set(scopes)) != len(scopes)
                or isinstance(quota, bool) or not isinstance(quota, int)
                or not 1 <= quota <= 10000
                or client_id in ids or token_hash in hashes):
            raise RuntimeError("API client registry entry is invalid")
        ids.add(client_id)
        hashes.add(token_hash)
        clients.append({
            "client_id": client_id,
            "token_sha256": token_hash,
            "scopes": frozenset(scopes),
            "rate_limit_per_minute": quota,
        })
    return clients


def _required_scope(request: Request) -> str:
    method = request.method.upper()
    path = request.url.path
    if method == "POST" and path in {
        "/v1/chat/completions", "/cognitive/query", "/cognitive/infer"
    }:
        return "inference"
    if method == "GET" and path == "/v1/models":
        return "models:read"
    if method == "GET" and path.startswith("/jobs/"):
        return "jobs:read"
    if path.startswith("/auth/"):
        return "auth:session"
    return "admin"


def _authenticate_client(request: Request, *, ignore_session: bool = False) -> dict:
    # A browser session takes precedence over the BFF's service credential, so
    # job ownership and quotas remain attached to the human account.
    cookies = getattr(request, "cookies", {})
    cookie_name = _session_cookie_name()
    if not ignore_session and cookies.get(cookie_name) and os.environ.get("NEXUS_API_USERS_FILE"):
        try:
            session = _resolve_user_session(cookies[cookie_name])
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Session service unavailable") from exc
        if session is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session",
                                headers={"WWW-Authenticate": "Bearer"})
        scope = _required_scope(request)
        if "admin" not in session["scopes"] and scope not in session["scopes"]:
            raise HTTPException(status_code=403, detail="User lacks required scope")
        return session
    registry_path = os.environ.get("NEXUS_API_CLIENTS_FILE", "")
    if registry_path:
        try:
            clients = _load_api_clients()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="API client registry is unavailable") from exc
        if not clients:
            raise HTTPException(status_code=503, detail="API client authentication is not configured")
        supplied = _client_authorization(request)
        if supplied is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        supplied_hash = hashlib.sha256(supplied.encode()).hexdigest()
        matched = None
        for client in clients:
            if hmac.compare_digest(supplied_hash, client["token_sha256"]):
                matched = client
        if matched is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scope = _required_scope(request)
        if "admin" not in matched["scopes"] and scope not in matched["scopes"]:
            raise HTTPException(status_code=403, detail="API client lacks required scope")
        return matched

    expected = _secret_value("NEXUS_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="API client authentication is not configured")
    supplied = _client_authorization(request)
    if supplied is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "client_id": "shared",
        "scopes": frozenset({"admin"}),
        "rate_limit_per_minute": _default_rate_limit(),
    }


def _enforce_client_auth(request: Request, *, ignore_session: bool = False) -> None:
    _authenticate_client(request, ignore_session=ignore_session)


def _default_rate_limit() -> int:
    try:
        limit = int(os.environ.get("NEXUS_API_RATE_LIMIT_PER_MINUTE", "60"))
    except ValueError:
        limit = 60
    return min(max(limit, 1), 10000)


def _consume_rate_limit(request: Request) -> tuple[int, int, int, bool]:
    """Process-local fixed-window limiter isolated by API client identity."""
    principal = _authenticate_client(request)
    limit = principal["rate_limit_per_minute"]
    try:
        redis = _redis_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Rate limit service unavailable") from exc
    if redis is not None:
        from nexus.api.auth.distributed_rate_limit import consume
        identity = hashlib.sha256(principal["client_id"].encode()).hexdigest()
        try:
            return consume(redis, f"nexus:quota:v1:{identity}", limit)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Rate limit service unavailable") from exc
    now = int(time.time())
    window = now // _RATE_WINDOW_SECONDS
    key = f"{principal['client_id']}:{window}"
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


def _secret_value(name: str) -> str:
    """Read a secret from an environment variable or a Docker-secret file."""
    value = os.environ.get(name, "")
    if value:
        return value.strip()
    path = os.environ.get(name + "_FILE", "")
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    except OSError as exc:
        raise RuntimeError(f"Configured secret file for {name} is unavailable") from exc


def _redis_tls_options(url: str, require_tls: bool) -> dict:
    """Validate the shared datastore URL and require certificate validation."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise RuntimeError("shared session and quota store URL is malformed") from None
    database = parsed.path[1:] if parsed.path.startswith("/") else "invalid"
    if (parsed.scheme not in {"redis", "rediss"} or not host
            or parsed.username is None or parsed.password is None
            or (parsed.path not in {"", "/"} and not database.isdecimal())
            or parsed.query or parsed.fragment or port == 0):
        raise RuntimeError("shared session and quota store URL is invalid")
    if require_tls and parsed.scheme != "rediss":
        raise RuntimeError("shared session and quota store requires verified TLS")
    return {"ssl_cert_reqs": "required"} if parsed.scheme == "rediss" else {}


@lru_cache(maxsize=1)
def _redis_client():
    """Return the shared Redis/Valkey client when sessions are configured."""
    url = _secret_value("NEXUS_REDIS_URL")
    if not url:
        if os.environ.get("NEXUS_API_USERS_FILE") or os.environ.get("NEXUS_API_REQUIRE_DISTRIBUTED_RATE_LIMIT") == "1":
            raise RuntimeError("shared session and quota store is not configured")
        return None
    try:
        from redis import Redis
        require_tls = os.environ.get("NEXUS_API_REDIS_REQUIRE_TLS") == "1"
        tls_options = _redis_tls_options(url, require_tls)
        return Redis.from_url(url, decode_responses=True, socket_connect_timeout=2,
                              socket_timeout=2, health_check_interval=30, **tls_options)
    except Exception as exc:
        raise RuntimeError("shared session and quota store is unavailable") from exc


def _resolve_user_session(token: str) -> dict | None:
    from nexus.api.auth.user_sessions import load_user_registry, resolve_session
    redis = _redis_client()
    if redis is None:
        raise RuntimeError("shared session and quota store is not configured")
    session = resolve_session(redis, token)
    if session is None:
        return None
    registry_path = os.environ.get("NEXUS_API_USERS_FILE", "")
    user = load_user_registry(registry_path).get(session["user_id"])
    if (user is None or user["client_id"] != session["client_id"]
            or user["scopes"] != session["scopes"]
            or user["rate_limit_per_minute"] != session["rate_limit_per_minute"]
            or user["password_scrypt"]["hash"] != session["auth_fingerprint"]):
        return None
    return session


def _session_cookie_name() -> str:
    return ("nexus_session" if os.environ.get("NEXUS_AUTH_COOKIE_SECURE", "1") == "0"
            else "__Host-nexus_session")


def _auth_origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin", "")
    configured = {item.strip().rstrip("/") for item in
                  os.environ.get("NEXUS_AUTH_ALLOWED_ORIGINS", "").split(",") if item.strip()}
    return bool(origin and configured and origin.rstrip("/") in configured)


@app.get("/auth/session")
async def get_auth_session(request: Request):
    """Return the active browser identity without exposing session material."""
    _authenticate_client(request, ignore_session=True)
    if not os.environ.get("NEXUS_API_USERS_FILE"):
        response = JSONResponse({"authenticated": False})
        response.headers["Cache-Control"] = "no-store"
        return response
    token = request.cookies.get(_session_cookie_name())
    if not token:
        response = JSONResponse({"authenticated": False})
        response.headers["Cache-Control"] = "no-store"
        return response
    try:
        session = _resolve_user_session(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    if session is None:
        response = JSONResponse({"authenticated": False})
    else:
        response = JSONResponse({"authenticated": True, "username": session["user_id"]})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/auth/login")
async def login(payload: Dict[str, Any], request: Request):
    """Create an opaque, shared browser session for a provisioned account."""
    if not _auth_origin_allowed(request):
        raise HTTPException(status_code=403, detail="Invalid origin")
    _authenticate_client(request, ignore_session=True)
    registry_path = os.environ.get("NEXUS_API_USERS_FILE", "")
    if not registry_path:
        raise HTTPException(status_code=503, detail="User authentication is not configured")
    from nexus.api.auth.user_sessions import (
        RegistryError, SessionStoreError, create_session, load_user_registry, verify_password,
    )
    from nexus.api.auth.distributed_rate_limit import RateLimitBackendError, consume
    username, password = payload.get("username"), payload.get("password")
    try:
        users = load_user_registry(registry_path)
    except RegistryError as exc:
        raise HTTPException(status_code=503, detail="User authentication is unavailable") from exc
    user = users.get(username) if isinstance(username, str) else None
    account_id = user["user_id"] if user else "<unknown>"
    try:
        redis = _redis_client()
        remote = getattr(getattr(request, "client", None), "host", "unknown") or "unknown"
        source_key = hashlib.sha256(remote.encode("utf-8", errors="replace")).hexdigest()
        account_key = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        ip_limit, ip_remaining, ip_reset, ip_allowed = consume(
            redis, f"nexus:login-ip:v1:{source_key}", 120
        )
        account_limit, account_remaining, account_reset, account_allowed = consume(
            redis, f"nexus:login-account:v1:{account_key}", 10
        )
    except (RuntimeError, RateLimitBackendError) as exc:
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc
    if not ip_allowed or not account_allowed:
        limit = min(ip_limit, account_limit)
        remaining = min(ip_remaining, account_remaining)
        reset = max(ip_reset, account_reset)
        raise HTTPException(status_code=429, detail="Too many login attempts",
                            headers={"Retry-After": str(max(1, reset - int(time.time()))),
                                     "X-RateLimit-Limit": str(limit),
                                     "X-RateLimit-Remaining": str(remaining),
                                     "X-RateLimit-Reset": str(reset)})
    if not await asyncio.to_thread(verify_password, password, user):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    try:
        previous = request.cookies.get(_session_cookie_name())
        if previous:
            from nexus.api.auth.user_sessions import revoke_session
            revoke_session(redis, previous)
        token = create_session(redis, user,
                               ttl_seconds=_bounded_env_int("NEXUS_AUTH_SESSION_TTL_SECONDS", 3600,
                                                            300, 2_592_000))
    except (RuntimeError, SessionStoreError) as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    secure = os.environ.get("NEXUS_AUTH_COOKIE_SECURE", "1") != "0"
    response = JSONResponse({"authenticated": True, "username": user["user_id"]})
    response.set_cookie(_session_cookie_name(), token, max_age=_bounded_env_int(
        "NEXUS_AUTH_SESSION_TTL_SECONDS", 3600, 300, 2_592_000), httponly=True,
        secure=secure, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/auth/logout")
async def logout(request: Request):
    """Revoke the shared session and expire the host-only browser cookie."""
    if not _auth_origin_allowed(request):
        raise HTTPException(status_code=403, detail="Invalid origin")
    _authenticate_client(request, ignore_session=True)
    token = request.cookies.get(_session_cookie_name())
    if token and os.environ.get("NEXUS_API_USERS_FILE"):
        from nexus.api.auth.user_sessions import revoke_session
        try:
            revoke_session(_redis_client(), token)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    secure = os.environ.get("NEXUS_AUTH_COOKIE_SECURE", "1") != "0"
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(_session_cookie_name(), path="/", httponly=True,
                           secure=secure, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@lru_cache(maxsize=1)
def _tls_context() -> ssl.SSLContext:
    ca_file = os.environ.get("NEXUS_H0_ROUTER_CA_FILE")
    return ssl.create_default_context(cafile=ca_file or None)


def _open_upstream(request: urllib.request.Request, timeout: int):
    # Router endpoints never need redirects. Refusing them prevents credentials
    # from being forwarded to a different authority after an upstream response.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect(),
        urllib.request.HTTPSHandler(context=_tls_context())
    )
    return opener.open(request, timeout=timeout)


class _RequestBodyTooLarge(Exception):
    pass


class RequestSafetyMiddleware:
    """Bound request bytes and in-flight inference work before JSON parsing."""

    def __init__(self, app, max_body_bytes: int = 1_048_576,
                 max_inflight_inferences: int = 8):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.inference_slots = threading.BoundedSemaphore(max_inflight_inferences)

    async def _respond(self, send, status: int, message: str, headers=None):
        body = json.dumps({"detail": message}, separators=(",", ":")).encode()
        response_headers = [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode())]
        if headers:
            response_headers.extend(headers)
        await send({"type": "http.response.start", "status": status,
                    "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method != "OPTIONS" and path not in {"/health", "/ready"}:
            try:
                _enforce_client_auth(
                    Request(scope, receive=receive), ignore_session=path.startswith("/auth/")
                )
            except HTTPException as exc:
                auth_headers = []
                if exc.headers:
                    auth_headers = [(name.lower().encode(), value.encode())
                                    for name, value in exc.headers.items()]
                return await self._respond(send, exc.status_code, str(exc.detail), auth_headers)

        headers = scope.get("headers", [])
        length_values = [value for name, value in headers if name.lower() == b"content-length"]
        if len(length_values) > 1:
            return await self._respond(send, 400, "Invalid Content-Length")
        if length_values:
            try:
                declared_length = int(length_values[0])
            except ValueError:
                return await self._respond(send, 400, "Invalid Content-Length")
            if declared_length < 0:
                return await self._respond(send, 400, "Invalid Content-Length")
            if declared_length > self.max_body_bytes:
                return await self._respond(send, 413, "Request body too large")

        inference = method == "POST" and path in {
            "/v1/chat/completions", "/cognitive/query", "/cognitive/infer"
        }
        acquired = self.inference_slots.acquire(blocking=False) if inference else False
        if inference and not acquired:
            return await self._respond(send, 503, "Inference capacity is full",
                                       [(b"retry-after", b"1")])

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._respond(send, 413, "Request body too large")
        finally:
            if acquired:
                self.inference_slots.release()


def _upstream_auth() -> Optional[str]:
    """Return only the server-to-server credential; never forward client tokens."""
    service_token = _secret_value("NEXUS_H0_CLIENT_TOKEN")
    if service_token:
        return service_token
    if urlsplit(H0_ROUTER_URL).scheme == "https":
        raise HTTPException(
            status_code=503,
            detail="H0 gateway service authentication is not configured",
        )
    return None


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
                  client: Optional[dict] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    upstream_token = _upstream_auth()
    if upstream_token:
        headers["Authorization"] = f"Bearer {upstream_token}"
    if client:
        headers["X-Nexus-Client-ID"] = client["client_id"]
        if "admin" in client["scopes"]:
            headers["X-Nexus-Client-Admin"] = "1"
    request = urllib.request.Request(
        f"{H0_ROUTER_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _open_upstream(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise HTTPException(
                status_code=502, detail="H0 gateway redirects are not allowed"
            ) from exc
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


def _get_gateway(path: str, client: Optional[dict] = None) -> Dict[str, Any]:
    headers = {}
    upstream_token = _upstream_auth()
    if upstream_token:
        headers["Authorization"] = f"Bearer {upstream_token}"
    if client:
        headers["X-Nexus-Client-ID"] = client["client_id"]
        if "admin" in client["scopes"]:
            headers["X-Nexus-Client-Admin"] = "1"
    request = urllib.request.Request(f"{H0_ROUTER_URL}{path}", headers=headers, method="GET")
    try:
        with _open_upstream(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = 502 if 300 <= exc.code < 400 else exc.code
        raise HTTPException(status_code=status, detail="H0 gateway request failed") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway is unavailable") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="H0 gateway returned invalid JSON") from exc


async def _complete(messages: list, parameters: Optional[Dict[str, Any]], timeout: int,
                    client: Optional[dict] = None):
    params = parameters or {}
    payload = {
        "model": params.get("model", ""),
        "messages": messages,
        "temperature": params.get("temperature", 0.3),
        "max_tokens": params.get("max_tokens", 256),
        "timeout_s": timeout,
    }
    return await asyncio.to_thread(_post_gateway, payload, timeout + 5, client)


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
    client = _authenticate_client(request)
    return await asyncio.to_thread(_post_gateway, forwarded, timeout + 5, client)


@app.get("/v1/models")
async def list_models(request: Request):
    client = _authenticate_client(request)
    return await asyncio.to_thread(_get_gateway, "/v1/models", client)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """Return the status/result for a native H0 job identifier."""
    if not re.fullmatch(r"job_[0-9]{1,12}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    client = _authenticate_client(request)
    return await asyncio.to_thread(_get_gateway, f"/jobs/{job_id}", client)


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
    result = await _complete([{"role": "user", "content": query}], None, 300,
                             _authenticate_client(request))
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
    result = await _complete([{"role": "user", "content": task}], parameters, timeout,
                             _authenticate_client(request))
    return StandardResponse(
        success=True,
        data={"inference_result": result},
        request_id=str(uuid4()),
        timestamp=datetime.now(),
    )


def _gateway_ready() -> bool:
    try:
        if os.environ.get("NEXUS_API_CLIENTS_FILE"):
            if not _load_api_clients():
                return False
        elif not _secret_value("NEXUS_API_TOKEN"):
            return False
        if os.environ.get("NEXUS_API_USERS_FILE"):
            from nexus.api.auth.user_sessions import load_user_registry
            load_user_registry(os.environ["NEXUS_API_USERS_FILE"])
        if (os.environ.get("NEXUS_API_USERS_FILE")
                or os.environ.get("NEXUS_API_REQUIRE_DISTRIBUTED_RATE_LIMIT") == "1"):
            redis = _redis_client()
            if redis is None or not redis.ping():
                return False
        if urlsplit(H0_ROUTER_URL).scheme == "https":
            if not _secret_value("NEXUS_H0_CLIENT_TOKEN"):
                return False
            _tls_context()
    except (OSError, RuntimeError, ssl.SSLError):
        return False
    request = urllib.request.Request(f"{H0_ROUTER_URL}/ready", method="GET")
    try:
        with _open_upstream(request, timeout=2) as response:
            result = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and result.get("ok") is True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeDecodeError):
        return False


@app.get("/health", response_model=StandardResponse, tags=["System"])
async def health_check():
    return StandardResponse(
        success=True,
        data={"status": "healthy"},
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
        data={"status": "ready"},
        request_id="readiness_check",
        timestamp=datetime.now(),
    )


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


app.add_middleware(
    RequestSafetyMiddleware,
    max_body_bytes=_bounded_env_int("NEXUS_API_MAX_BODY_BYTES", 1_048_576, 1024, 16_777_216),
    max_inflight_inferences=_bounded_env_int(
        "NEXUS_API_MAX_INFLIGHT_INFERENCES", 8, 1, 128
    ),
)
