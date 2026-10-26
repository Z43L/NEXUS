# NEXUS H0 Helm chart

Private H0 path: Router with persistent SQLite state, H1 worker, authenticated API, and same-origin web BFF. All Services are `ClusterIP`; there is no public Ingress. Install in a dedicated namespace because internal DNS names `router` and `api` are fixed and the Router certificate must include DNS SAN `router`.

This is a deployment template, not evidence of a running Kubernetes deployment. Build and publish the images using repository Dockerfiles, pin them by immutable tag or digest, then set `images.routerWorker`, `images.api`, and `images.web`. No image is published by this chart. The chart expects an operator-managed Valkey/Redis service with TLS and ACL credentials; it does not create a datastore. The `nexus-api` Secret must set `redis.url` to a `rediss://` URL. The API rejects `redis://` in chart mode and requires certificate verification; add the issuing CA to the API image trust store if the managed service uses a private CA. The former `values-production.yaml` was removed because its image and secret assumptions were not deployable.

Create these Kubernetes Secrets in the target namespace before installation:

| Secret | Required keys |
| --- | --- |
| `nexus-router` | `tls.crt`, `tls.key`, `ca.crt`, `client.token`, `enrollment.token` |
| `nexus-worker` | `ca.crt`, `enrollment.token`, `atenea.api.key` |
| `nexus-api` | `ca.crt`, `client.token`, `api_clients.json`, `api_users.json`, `redis.url` |
| `nexus-web` | `api.token` |

The Router certificate must be signed by the supplied CA. Use the external Atenhea ENGINE origin in `atenea.url` over HTTPS for any remote engine; remote workers require `atenea.api.key` and send it as a bearer credential. Configure Atenhea with that same key and a TLS certificate before exposing it beyond loopback. Set `api.authAllowedOrigins`, `web.allowedHosts`, and `web.allowedOrigins` to exact values for the trusted HTTPS ingress. The chart creates no Ingress or TLS endpoint; the current BFF must sit behind that operator-managed HTTPS ingress. Secret values never go through Helm. Init containers copy Secret volume files into memory-backed volumes with owner-only permissions to preserve app checks. Kubernetes Secret encryption-at-rest and RBAC are cluster responsibilities.

The API requires `api_users.json` and `redis.url`. The user registry stores scrypt password hashes. Provision a user on a protected operator host with `python3 nexus/api/manage_api_users.py --registry /path/to/api_users.json add --id alice`; the command prompts for the password and shows it nowhere. Add `auth:session` to the BFF API client scopes. Recreate API pods after Secret changes so file-backed credentials refresh. API replicas share opaque sessions and fixed-window inference quotas through Valkey/Redis; loss of that store returns 503 rather than bypassing authentication or quotas.

Install with your private values file:

```sh
helm upgrade --install nexus ./charts/nexus -n nexus \
  --set-string images.routerWorker=registry.example/nexus-router-worker:PINNED \
  --set-string images.api=registry.example/nexus-api:PINNED \
  --set-string images.web=registry.example/nexus-web:PINNED \
  --set-string atenea.url=https://atenhea.internal \
  --set-string api.authAllowedOrigins=https://nexus.example.com \
  --set-string web.allowedHosts=nexus.example.com \
  --set-string web.allowedOrigins=https://nexus.example.com
```

Reach the UI through the configured TLS ingress. The worker needs egress to Atenhea. Worker replicas each get a PVC; the external engine must have capacity for the configured count.

Run `helm lint ./charts/nexus` and `helm template nexus ./charts/nexus -n nexus -f private-values.yaml` to validate chart structure and rendering. Those checks do not prove cluster admission, PVC provisioning, secret correctness, image availability, network connectivity, or runtime readiness. A Kubernetes cluster is required for those checks.
