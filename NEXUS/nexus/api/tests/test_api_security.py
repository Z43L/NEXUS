"""Regression tests for the local API facade's authentication and quotas."""

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.responses import Response

from nexus.api.core import api_server


class FakeRequest:
    def __init__(self, path="/v1/chat/completions", method="POST", headers=None,
                 host="127.0.0.1"):
        self.url = SimpleNamespace(path=path)
        self.method = method
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}
        self.client = SimpleNamespace(host=host)


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        api_server._rate_buckets.clear()

    def test_auth_accepts_bearer_and_api_key_and_rejects_bad_token(self):
        request = FakeRequest(headers={"Authorization": "Bearer local-secret"})
        with patch.dict(os.environ, {"NEXUS_API_TOKEN": "local-secret"}):
            api_server._enforce_client_auth(request)
            with self.assertRaises(api_server.HTTPException) as caught:
                api_server._enforce_client_auth(FakeRequest(headers={"Authorization": "Bearer wrong"}))
            self.assertEqual(caught.exception.status_code, 401)
            api_server._enforce_client_auth(FakeRequest(headers={"X-API-Key": "local-secret"}))

    def test_upstream_service_token_overrides_caller_but_caller_can_be_forwarded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(api_server._upstream_auth("caller-token"), "caller-token")
        with patch.dict(os.environ, {"NEXUS_H0_CLIENT_TOKEN": "router-token"}):
            self.assertEqual(api_server._upstream_auth("caller-token"), "router-token")

    def test_rate_limit_allows_exact_quota_then_rejects_and_isolates_tokens(self):
        request = FakeRequest(headers={"Authorization": "Bearer token-a"})
        with patch.dict(os.environ, {
            "NEXUS_API_TOKEN": "token-a",
            "NEXUS_API_RATE_LIMIT_PER_MINUTE": "2",
        }):
            first = api_server._consume_rate_limit(request)
            second = api_server._consume_rate_limit(request)
            third = api_server._consume_rate_limit(request)
            other = api_server._consume_rate_limit(
                FakeRequest(headers={"Authorization": "Bearer token-b"})
            )
        self.assertTrue(first[3])
        self.assertTrue(second[3])
        self.assertFalse(third[3])
        self.assertTrue(other[3])
        self.assertEqual(second[1], 0)

    def test_middleware_returns_auth_and_quota_statuses_with_retry_headers(self):
        async def invoke():
            request = FakeRequest(headers={"Authorization": "Bearer token-a"})

            async def next_response(_request):
                return Response("ok", status_code=200)

            with patch.dict(os.environ, {
                "NEXUS_API_TOKEN": "token-a",
                "NEXUS_API_RATE_LIMIT_PER_MINUTE": "1",
            }):
                unauthenticated = await api_server.local_api_controls(
                    FakeRequest(), next_response
                )
                permitted = await api_server.local_api_controls(request, next_response)
                limited = await api_server.local_api_controls(request, next_response)
            return unauthenticated, permitted, limited

        unauthenticated, permitted, limited = asyncio.run(invoke())
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(permitted.status_code, 200)
        self.assertEqual(permitted.headers["x-ratelimit-remaining"], "0")
        self.assertEqual(limited.status_code, 429)
        self.assertIn("retry-after", limited.headers)

    def test_gateway_error_handler_preserves_router_error_envelope(self):
        async def invoke():
            return await api_server.preserve_gateway_error(
                None,
                api_server.HTTPException(
                    status_code=504,
                    detail={"error": {
                        "type": "job_timeout", "job_id": "job_123",
                        "message": "still pending",
                    }},
                ),
            )

        response = asyncio.run(invoke())
        self.assertEqual(response.status_code, 504)
        self.assertEqual(
            json.loads(response.body),
            {"error": {
                "type": "job_timeout", "job_id": "job_123",
                "message": "still pending",
            }},
        )

    def test_timeout_parser_rejects_non_integral_numbers_and_booleans(self):
        for value in (1.5, True, None, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(api_server.HTTPException) as caught:
                api_server._bounded_timeout(value, "timeout_s")
            self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(api_server._bounded_timeout("1801", "timeout_s"), 1800)


if __name__ == "__main__":
    unittest.main()
