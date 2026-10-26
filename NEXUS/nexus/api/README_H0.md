# API H0 local

`run_h0_api.sh` starts the FastAPI compatibility facade on `127.0.0.1:8000`
and connects it to an already-running local H0 Router. The launcher rejects a
non-loopback Router URL and binds the facade to loopback.

## Authentication and upstream credentials

Set `NEXUS_API_TOKEN` to require a bearer token on API requests. Clients may
send `Authorization: Bearer <token>` (preferred) or `X-API-Key: <token>`. The
API fails closed when no token is configured, including in local mode.
`/health` and `/ready` are exempt for local process supervision; all other
routes, including `/v1/models`, require the configured token.

The Python and TypeScript SDKs default to `http://127.0.0.1:8000`, the FastAPI
facade. Pass the configured token as `api_key` / `apiKey`; both send
`X-API-Key`. Direct access to the Router on port 18080 is for trusted local
development and bypasses this facade's client-token and quota checks. The
separate HTML UI served by `nexus-web/h0_local.py` remains loopback-only and
connects directly to the Router.

For an H0 Router running in remote/authenticated mode, set
`NEXUS_H0_CLIENT_TOKEN` to its client token. This service credential is sent to
the Router; the API never forwards the caller's token upstream. HTTPS Router
connections require this separate service credential. Docker deployments can
use `NEXUS_API_TOKEN_FILE` and `NEXUS_H0_CLIENT_TOKEN_FILE` to read mounted
secrets without placing their values in environment variables.
The Router URL must use HTTP only on loopback or verified HTTPS; redirects are
rejected, and an optional `NEXUS_H0_ROUTER_CA_FILE` configures a private CA.
Never place either token in source control or logs.

## Request limits

The facade rejects request bodies larger than 1 MiB before JSON parsing and
allows at most 8 concurrent inference requests per process by default. Set
`NEXUS_API_MAX_BODY_BYTES` (1 KiB–16 MiB) and
`NEXUS_API_MAX_INFLIGHT_INFERENCES` (1–128) to adjust those bounds.

Chat and cognitive inference routes use an in-process fixed-window limit of 60
requests per minute by default. Set `NEXUS_API_RATE_LIMIT_PER_MINUTE` to an
integer from 1 to 10000 to change it. Responses include `X-RateLimit-*`
headers; excess requests receive HTTP 429 and `Retry-After`. Buckets are keyed
by a hash of the required API credential. The limiter is process-local and
resets on restart, so it is suitable for this single-process local facade, not
a multi-instance public service.

Health endpoints intentionally bypass the inference quota. H0's Router remains
responsible for job admission, worker authentication, durable receipts, and
ledger state. Health reports process liveness; readiness checks that the
Router responds. Neither endpoint returns the upstream URL.

## Regression tests

From the repository's `NEXUS` directory, with the H0 cryptography dependency and
the API lock installed:

```sh
python3 -m pip install -r nexus/h0/requirements-h0.txt
python3 -m pip install --require-hashes -r nexus/api/requirements-h0.lock
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s nexus/api/tests -v
```
