# API H0 local

`run_h0_api.sh` starts the FastAPI compatibility facade on `127.0.0.1:8000`
and connects it to an already-running local H0 Router. The launcher rejects a
non-loopback Router URL and binds the facade to loopback.

## Authentication and upstream credentials

For local compatibility, `NEXUS_API_TOKEN` or `NEXUS_API_TOKEN_FILE` enables a
single shared credential. The Compose product path uses the recommended
per-client registry via `NEXUS_API_CLIENTS_FILE`: a mode-`0600` JSON file holds
SHA-256 token digests, client IDs, scopes and per-minute quotas, never plaintext
client keys. When a registry path is set, the API fails closed on missing,
invalid or permissively readable files and does not accept the shared-token
fallback. Clients may send `Authorization: Bearer <token>` (preferred) or
`X-API-Key: <token>`. `/health` and `/ready` remain exempt for process
supervision.

From the `NEXUS/` directory, issue a least-privilege key:

```sh
python3 nexus/api/manage_api_clients.py --registry .secrets/api_clients.json \
  add --id integration --scopes inference,models:read,jobs:read \
  --rate-limit-per-minute 30
```

The new token is printed once; store it in a secret manager. List client IDs,
scopes and quotas without revealing keys, or revoke by ID:

```sh
python3 nexus/api/manage_api_clients.py --registry .secrets/api_clients.json list
python3 nexus/api/manage_api_clients.py --registry .secrets/api_clients.json revoke --id integration
docker compose --env-file .env.h0 -f compose.h0.yml up -d --force-recreate api web
```

Recreate API/WEB after registry changes because Compose file-backed secrets may
remain bound to the previous file inode. The bootstrap registry grants the BFF
token `auth:session`, `inference`, `models:read` and `jobs:read`; it does not grant admin.

## Browser accounts and shared sessions

Compose uses a private Valkey service for opaque browser sessions and distributed inference quotas. Provision accounts from `NEXUS/` with a terminal password prompt; passwords are never command arguments or printed:

```sh
python3 nexus/api/manage_api_users.py --registry .secrets/api_users.json \
  add --id alice --scopes inference,models:read,jobs:read --rate-limit-per-minute 30
python3 nexus/api/manage_api_users.py --registry .secrets/api_users.json list
python3 nexus/api/manage_api_users.py --registry .secrets/api_users.json set-password --id alice
python3 nexus/api/manage_api_users.py --registry .secrets/api_users.json remove --id alice
docker compose --env-file .env.h0 -f compose.h0.yml up -d --force-recreate api web
```

The registry is mode 0600 in a mode 0700 operator directory and stores scrypt password hashes. Session cookies are HttpOnly, SameSite=Lax, host-only and expire after one hour by default. Production uses `__Host-nexus_session; Secure; Path=/`; loopback Compose uses a separate HTTP-only development cookie because its ports bind only to loopback. The API requires exact configured origins for login/logout and ignores forwarded headers. Production API and Valkey must stay private behind a TLS ingress; configure the exact HTTPS origin in `NEXUS_AUTH_ALLOWED_ORIGINS`.

Valkey stores only SHA-256 session-token keys, session identity/scope metadata, and counters; raw session tokens exist only in the browser cookie and BFF/API request path. Sessions are revalidated against the current user registry on every request, so password reset, account removal, scope changes, and quota changes invalidate old sessions. If Valkey is unavailable, login, session authentication and quota-protected inference fail closed. API replicas share this store; local Compose enables AOF persistence with `noeviction`.

The Python and TypeScript SDKs default to `http://127.0.0.1:8000`, the FastAPI
facade. Pass the configured token as `api_key` / `apiKey`; both send
`X-API-Key`. Direct access to the Router on port 18080 is for trusted local
development and bypasses this facade's client-token and quota checks. The
separate HTML UI served by `nexus-web/h0_local.py` remains loopback-only in
local development and connects directly to the Router. In `compose.h0.yml`, the
UI instead proxies same-origin browser requests through this authenticated API;
its server reads `api.token` from a mounted secret and does not expose it to the
browser. The API receives only the client registry digest file, not the BFF's
plaintext token. `GET /jobs/{job_id}` exposes native job status/results through
the same scoped facade. Each API-created Router job stores its authenticated
`client_id`; status and result lookups are restricted to that owner, while a
client with the `admin` scope may inspect any job. A different client receives
404 so the API does not reveal whether another client's job ID exists. Legacy
jobs without an owner are not visible through the scoped API.

For an H0 Router running in remote/authenticated mode, set
`NEXUS_H0_CLIENT_TOKEN` to its client token. This service credential is sent to
the Router; the API never forwards the caller's token upstream. HTTPS Router
connections require this separate service credential. Docker deployments can
use `NEXUS_H0_CLIENT_TOKEN_FILE` to read that mounted service token without
placing its value in environment variables. The API's multi-client registry is
configured by `NEXUS_API_CLIENTS_FILE`.
The Router URL must use HTTP only on loopback or verified HTTPS; redirects are
rejected, and an optional `NEXUS_H0_ROUTER_CA_FILE` configures a private CA.
Never place either token in source control or logs.

## Request limits

The facade rejects request bodies larger than 1 MiB before JSON parsing and
allows at most 8 concurrent inference requests per process by default. Set
`NEXUS_API_MAX_BODY_BYTES` (1 KiB–16 MiB) and
`NEXUS_API_MAX_INFLIGHT_INFERENCES` (1–128) to adjust those bounds.

Chat and cognitive inference routes use a fixed-window limit. Local compatibility
mode can use an in-process bucket. Compose and Helm require Valkey/Redis and
atomically increment shared counters per principal; in registry mode each
technical client or user has its own 1–10000 requests/minute quota. Responses
include `X-RateLimit-*` headers; excess requests receive HTTP 429 and
`Retry-After`. Set `NEXUS_API_REQUIRE_DISTRIBUTED_RATE_LIMIT=1` to require the
shared backend; a backend outage returns 503.

Health endpoints intentionally bypass the inference quota. H0's Router remains
responsible for job admission, worker authentication, durable receipts, and
ledger state. Health reports process liveness; readiness checks that the
Router responds. Neither endpoint returns the upstream URL.

Browser login uses two shared Valkey fixed-window limits: 120 attempts per
source address and 10 attempts per provisioned account per minute. Unknown
usernames share a separate bucket. This keeps a shared BFF address from making
one user's failed attempts lock out every other user. The source address is
the address observed by the API; deployments behind a proxy should restrict
API reachability to trusted proxy paths and configure that network boundary.

## Regression tests

From the repository's `NEXUS` directory, with the H0 cryptography dependency and
the API lock installed:

```sh
python3 -m pip install --require-hashes --only-binary=:all: -r nexus/h0/requirements-h0.txt
python3 -m pip install --require-hashes -r nexus/api/requirements-h0.lock
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s nexus/api/tests -v
```
