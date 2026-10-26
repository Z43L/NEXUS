# NEXUS TypeScript SDK

TypeScript client for the local NEXUS OpenAI-compatible gateway.

```ts
import NexusClient from '@nexus-network/sdk';

const nexus = new NexusClient({
  baseURL: 'http://127.0.0.1:8000',
  apiKey: process.env.NEXUS_API_TOKEN,
});
const result = await nexus.chat('Resume el siguiente capítulo', {
  model: 'model-id-from-v1-models',
  maxTokens: 256,
});
console.log(result.choices[0].message.content);
```

Build with `npm ci && npm run build`. `model` is optional; when omitted, the
Router dispatches to any registered worker model. H0 accepts text-only,
non-streaming chat requests. Knowledge upload and streaming are not supported.
`timeoutSeconds` sets the Router's job deadline (1–1800 seconds); the SDK's
per-request HTTP timeout is at least ten seconds longer. The constructor's
`timeout` can extend the HTTP deadline further.
The SDK defaults to the local FastAPI facade on port 8000. Start the H0 Router,
then start `nexus/api/run_h0_api.sh` with `NEXUS_API_TOKEN` configured; the
facade validates this client token and applies local quotas. Set `baseURL` to
`http://127.0.0.1:18080` only for trusted local development that intentionally
bypasses the facade. Never embed a shared API token into a browser bundle. For a browser UI, see
[`NEXUS/nexus-web/README_H0.md`](../nexus-web/README_H0.md).
The SDK rejects HTTP for non-loopback `baseURL` values. In Node.js, it disables
ambient proxy settings and redirects so credentials and prompts stay on the
configured API authority.
