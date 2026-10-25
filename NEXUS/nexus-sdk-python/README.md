# NEXUS Python SDK

Async convenience client for the local NEXUS gateway. Requires Python 3.10 or
newer and has no runtime dependencies outside the standard library.

Install from a checkout of this repository:

```sh
python -m pip install ./NEXUS/nexus-sdk-python
```

Or from the `NEXUS` directory use `python -m pip install ./nexus-sdk-python`.

```python
import asyncio
from nexus_client import NexusClient

async def main():
    async with NexusClient(base_url="http://127.0.0.1:18080") as nexus:
        result = await nexus.chat("Resume la historia de NEXUS", max_tokens=256)
        print(result["choices"][0]["message"]["content"])

asyncio.run(main())
```

The client calls `POST /v1/chat/completions`. H0 supports text messages and
non-streaming responses only. `query()` and `infer()` are convenience aliases
for chat; knowledge upload and streaming are not implemented by H0. The default
empty model lets the Router select any compatible registered worker; pass
`model=` explicitly when you need a particular announced model.
`timeout_s` is the Router's job deadline (1–1800 seconds); the SDK sets its
HTTP transport deadline to at least ten seconds beyond that deadline. The
client-level `timeout` can extend the transport deadline further.

Run the client regression tests from the repository's `NEXUS` directory with
`PYTHONPATH=./nexus-sdk-python python -m unittest discover -s nexus-sdk-python/tests -v`.

H0 binds to loopback and does not authenticate API keys. Keep it local; do not
expose it to the Internet. `api_key` is only sent as `X-API-Key` when an
authenticated reverse proxy is configured in front of the gateway.
