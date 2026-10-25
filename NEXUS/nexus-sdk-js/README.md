# NEXUS TypeScript SDK

TypeScript client for the local NEXUS OpenAI-compatible gateway.

```ts
import NexusClient from '@nexus-network/sdk';

const nexus = new NexusClient({ baseURL: 'http://127.0.0.1:18080' });
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
The Router binds to loopback and H0 does not authenticate API keys; do not
expose it to the Internet. For a browser UI, see
[`NEXUS/nexus-web/README_H0.md`](../nexus-web/README_H0.md).
