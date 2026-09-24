import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import azure.functions as func
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import function_app as gateway


class GatewayRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, outcome):
        payload = json.dumps({
            'model': 'fixture-model', 'temperature': 0, 'max_tokens': 1200,
            'messages': [{'role': 'system', 'content': 'private evidence'},
                         {'role': 'user', 'content': 'private question'}],
        }).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(b'fixture-secret', stamp.encode() + b'\n' + payload,
                             hashlib.sha256).hexdigest()
        req = func.HttpRequest('POST', 'https://fixture/api/v1/chat/completions',
            headers={'x-gateway-timestamp': stamp, 'x-gateway-signature': signature,
                     'x-request-id': 'trace-fixture-01'}, body=payload)
        client = AsyncMock()
        client.__aenter__.return_value = client
        if isinstance(outcome, Exception):
            client.post.side_effect = outcome
        else:
            client.post.return_value = outcome
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'fixture-api-key',
                'GATEWAY_SHARED_SECRET': 'fixture-secret', 'GEMINI_MODEL': 'fixture-model'}), \
                patch.object(gateway, 'check_rate_limit'), \
                patch.object(gateway.httpx, 'AsyncClient', return_value=client), \
                self.assertLogs(gateway.logger, level='INFO') as logs:
            result = await gateway.chat_completions.build().get_user_function()(req)
        text = '\n'.join(logs.output)
        for secret in ('fixture-api-key', 'fixture-secret', 'private evidence', 'private question'):
            self.assertNotIn(secret, text)
        self.assertIn('trace-fixture-01', text)
        self.assertEqual(client.post.call_args.kwargs['headers']['X-Request-ID'], 'trace-fixture-01')
        return result, text

    async def test_timeout_is_distinct_from_upstream_http_504(self):
        result, logs = await self.invoke(httpx.ReadTimeout('private question'))
        self.assertEqual(result.status_code, 504)
        self.assertEqual(json.loads(result.get_body())['error']['code'], 'UPSTREAM_TIMEOUT')
        self.assertIn('exception_type=ReadTimeout', logs)
        result, logs = await self.invoke(httpx.Response(504, json={'error': {'code': 'DEADLINE'}}))
        self.assertEqual(result.status_code, 504)
        self.assertIn('http_status=504', logs)
        self.assertNotIn('exception_type=ReadTimeout', logs)

    async def test_transport_failure(self):
        result, logs = await self.invoke(httpx.ConnectError('fixture-api-key'))
        self.assertEqual(result.status_code, 502)
        self.assertIn('exception_type=ConnectError', logs)

    async def test_success(self):
        result, logs = await self.invoke(httpx.Response(200, json={'choices': []}))
        self.assertEqual(result.status_code, 200)
        self.assertIn('http_status=200', logs)
