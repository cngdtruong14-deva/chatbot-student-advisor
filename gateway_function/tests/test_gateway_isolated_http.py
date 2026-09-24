"""Real loopback HTTP integration; synthetic credentials/data, no cloud or DB."""
import asyncio
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import azure.functions as func

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'gateway_function')]
import function_app as gateway
from app.llm_runtime import OpenAICompatibleProvider, ProviderConfig


class IsolatedHTTPTests(unittest.TestCase):
    def test_backend_gateway_upstream_over_loopback(self):
        state = {'mode': 'success', 'ids': []}

        class QuietHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # Expected when exercising client timeouts.

        class Upstream(QuietHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                state['ids'].append(self.headers.get('X-Request-ID'))
                mode = state['mode']
                if mode in ('slow', 'client_timeout'):
                    time.sleep(1.4)
                if mode == 'http504':
                    self.reply(504, b'{"error":{"code":"DEADLINE"}}')
                    return
                citation = 'wrong-id' if mode == 'bad_citation' else 'chunk-1'
                content = json.dumps({'answer': 'Fixture answer', 'claims': [
                    {'text': 'Fixture answer', 'citation_ids': [citation]}]})
                self.reply(200, json.dumps({'choices': [{'message': {'content': content}}]}).encode())

        class Gateway(QuietHandler):
            def do_POST(self):
                req = func.HttpRequest('POST', 'http://localhost' + self.path,
                    headers=dict(self.headers), body=self.rfile.read(int(self.headers['Content-Length'])))
                response = asyncio.run(gateway.chat_completions.build().get_user_function()(req))
                self.reply(response.status_code, response.get_body())

        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        proxy = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        for server in (upstream, proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic-key',
                    'GATEWAY_SHARED_SECRET': 'synthetic-shared', 'GEMINI_MODEL': 'fixture-model',
                    'GATEWAY_UPSTREAM_TIMEOUT_SECONDS': '1', 'NO_PROXY': '127.0.0.1,localhost'}), \
                    patch.object(gateway, 'UPSTREAM_URL', f'http://127.0.0.1:{upstream.server_port}/chat'), \
                    patch.object(gateway, 'check_rate_limit'):
                for mode, expected, reason in (
                    ('success', 'completed', None),
                    ('http504', 'timeout', 'PROVIDER_HTTP_TIMEOUT'),
                    ('slow', 'timeout', 'PROVIDER_HTTP_TIMEOUT'),
                    ('client_timeout', 'timeout', 'PROVIDER_TIMEOUT'),
                    ('bad_citation', 'provider_error', 'PROVIDER_RESPONSE_INVALID'),
                    ('success', 'completed', None),
                ):
                    with self.subTest(mode=mode):
                        state['mode'] = mode
                        provider = OpenAICompatibleProvider(ProviderConfig(
                            f'http://127.0.0.1:{proxy.server_port}/api/v1', 'fixture-model',
                            'synthetic-shared', 0.25 if mode == 'client_timeout' else 3,
                            enabled=True, gateway_mode=True, rate_limit_retries=0))
                        started = time.monotonic()
                        result = provider.generate('Synthetic question', [{'chunk': {
                            'chunk_id': 'chunk-1', 'text': 'Fixture answer'}}])
                        elapsed = time.monotonic() - started
                        self.assertEqual(result['status'], expected)
                        self.assertEqual(result.get('failure_reason'), reason)
                        self.assertLess(elapsed, 4)
                        print(f'LOOPBACK mode={mode} status={result["status"]} elapsed={elapsed:.3f}s')
                        if mode == 'client_timeout':
                            time.sleep(1.5)  # Let only this synthetic in-flight call finish.
                # The short client budget can expire before the request reaches
                # upstream (e.g. during local TLS/client initialization).
                self.assertIn(len(state['ids']), (5, 6))
                self.assertEqual(len(set(state['ids'])), len(state['ids']))
                self.assertTrue(all(state['ids']))
        finally:
            for server in (proxy, upstream):
                server.shutdown()
                server.server_close()
