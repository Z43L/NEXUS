import asyncio
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

from nexus_client import NexusAPIError, NexusClient


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b'{"choices": []}'


class NexusClientTests(unittest.TestCase):
    def test_default_model_allows_router_auto_selection(self):
        client = NexusClient()
        with patch("nexus_client.urlopen", return_value=_Response()) as open_url:
            asyncio.run(client.chat("hello"))
        payload = json.loads(open_url.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "")

    def test_request_deadline_covers_router_deadline(self):
        client = NexusClient(timeout=30)
        with patch("nexus_client.urlopen", return_value=_Response()) as open_url:
            asyncio.run(client.chat("slow job", timeout_s=1800))
        self.assertEqual(open_url.call_args.kwargs["timeout"], 1810)

    def test_client_timeout_can_extend_router_deadline(self):
        client = NexusClient(timeout=2000)
        with patch("nexus_client.urlopen", return_value=_Response()) as open_url:
            asyncio.run(client.chat("slow job", timeout_s=1800))
        self.assertEqual(open_url.call_args.kwargs["timeout"], 2000)

    def test_timeout_outside_router_range_is_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(NexusClient().chat("bad timeout", timeout_s=1801))

    def test_fastapi_wrapped_router_timeout_keeps_message_and_job_id(self):
        payload = {"detail": {"error": {
            "type": "job_timeout", "job_id": "job_123", "message": "still pending"
        }}}
        http_error = HTTPError("http://localhost", 504, "timeout", {},
                               io.BytesIO(json.dumps(payload).encode()))
        with patch("nexus_client.urlopen", side_effect=http_error):
            with self.assertRaises(NexusAPIError) as caught:
                NexusClient()._send(Request("http://localhost"), 1)
        self.assertEqual(str(caught.exception), "still pending")
        self.assertEqual(caught.exception.status_code, 504)
        self.assertEqual(caught.exception.payload["detail"]["error"]["job_id"], "job_123")


if __name__ == "__main__":
    unittest.main()
