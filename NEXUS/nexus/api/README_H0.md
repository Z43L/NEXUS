# API H0 local

`run_h0_api.sh` starts the FastAPI compatibility facade on `127.0.0.1:8000`
and connects it to an already-running local H0 Router. The launcher rejects a
non-loopback Router URL and binds the facade to loopback.

## Authentication and upstream credentials

Set `NEXUS_API_TOKEN` to require the same bearer token on API requests. Clients
may send `Authorization: Bearer <token>` (preferred) or `X-API-Key: <token>`.
If it is unset, the launcher remains a loopback-only development service.
`/health` and `/ready` are exempt for local process supervision; all other
routes, including `/v1/models`, require the configured token.

For an H0 Router running in remote/authenticated mode, set
`NEXUS_H0_CLIENT_TOKEN` to its client token. This service credential is sent to
the Router and takes precedence over the caller's bearer token. If it is
unset, an incoming bearer token is forwarded as-is, which allows a shared
credential to authenticate through both layers. Never place either token in
source control or logs.

## Request limits

Chat and cognitive inference routes use an in-process fixed-window limit of 60
requests per minute by default. Set `NEXUS_API_RATE_LIMIT_PER_MINUTE` to an
integer from 1 to 10000 to change it. Responses include `X-RateLimit-*`
headers; excess requests receive HTTP 429 and `Retry-After`. With API auth
enabled, buckets are keyed by a hash of the credential; in local open mode,
they are keyed by client address. The limiter is process-local and resets on
restart, so it is suitable for this single-process local facade, not a
multi-instance public service.

Health endpoints intentionally bypass the inference quota. H0's Router remains
responsible for job admission, worker authentication, durable receipts, and
ledger state.

## Regression tests

From the repository's `NEXUS` directory, with `requirements-h0.lock` installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s nexus/api/tests -v
```
