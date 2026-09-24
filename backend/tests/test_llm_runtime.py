import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.llm_runtime import OpenAICompatibleProvider, ProviderConfig, config_from_env, prompt_sha256
from advisor_core.rag import evidence_response


def match():
    return {"chunk":{"chunk_id":"chunk-1","version_id":"v1","source":"database","section":"Hoc lai","text":"Hoc lai duoc tinh theo DEMO-1.","data_origin":"synthetic"},"score":0.9}


class LLMRuntimeTests(unittest.TestCase):
    def config(self):
        return ProviderConfig("https://provider.invalid/v1","fixture-model","test-secret",3,True)

    def transport(self,payload,status=200):
        return httpx.MockTransport(lambda request:httpx.Response(status,json=payload))

    def test_valid_grounded_generation(self):
        content=json.dumps({"answer":"Theo DEMO-1, quy tac hoc lai duoc ap dung.","claims":[{"text":"Quy tac hoc lai","citation_ids":["chunk-1"]}]})
        provider=OpenAICompatibleProvider(self.config(),self.transport({"choices":[{"message":{"content":content}}]}))
        result=evidence_response([match()],"Hoc lai?",provider)
        self.assertEqual(result["status"],"answered")
        self.assertEqual(result["generation_status"],"completed")
        self.assertEqual(result["claims"][0]["citation_ids"],["chunk-1"])

    def test_rejects_hallucinated_citation(self):
        content=json.dumps({"answer":"Sai","claims":[{"text":"Sai","citation_ids":["not-retrieved"]}]})
        provider=OpenAICompatibleProvider(self.config(),self.transport({"choices":[{"message":{"content":content}}]}))
        result=evidence_response([match()],"Hoc lai?",provider)
        self.assertEqual(result["status"],"insufficient_evidence")
        self.assertEqual(result["generation_status"],"provider_error")
        self.assertIsNone(result["answer"])

    def test_provider_absent_and_error_are_safe(self):
        absent=OpenAICompatibleProvider(ProviderConfig("","","",3))
        self.assertEqual(absent.generate("x",[match()])["status"],"provider_unavailable")
        failing=OpenAICompatibleProvider(self.config(),self.transport({"error":"rate"},429))
        self.assertEqual(failing.generate("x",[match()])["status"],"rate_limited")

    def test_authentication_failures_are_distinct_and_safe(self):
        for status in (401, 403):
            with self.subTest(status=status):
                provider=OpenAICompatibleProvider(self.config(),self.transport({"error":"auth"},status))
                self.assertEqual(provider.generate("x",[match()])["status"],"authentication_error")

    def test_timeout_is_distinct_and_safe(self):
        def timeout(request):
            raise httpx.ReadTimeout("fixture timeout", request=request)
        provider=OpenAICompatibleProvider(self.config(),httpx.MockTransport(timeout))
        self.assertEqual(provider.generate("x",[match()])["status"],"timeout")

    def test_empty_provider_content_fails_closed(self):
        for content in ("", "   "):
            with self.subTest(content=content):
                provider=OpenAICompatibleProvider(self.config(),self.transport({"choices":[{"message":{"content":content}}]}))
                self.assertEqual(provider.generate("x",[match()])["status"],"provider_error")

    def test_gemini_uses_explicit_local_configuration(self):
        # Mock configuration only; this is not a Gemini quality/smoke test.
        with patch.dict(os.environ, {"RAG_LLM_PROVIDER":"gemini", "RAG_LLM_ENABLED":"1", "RAG_LLM_MODEL":"owner-selected", "GEMINI_API_KEY":"fixture-key"}, clear=True):
            config = config_from_env()
        self.assertTrue(config.configured)
        self.assertEqual(config.base_url, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(config.timeout_seconds, 12)
        self.assertEqual(config.rate_limit_retries, 1)

    def test_rate_limit_retry_budget_is_bounded(self):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(429, json={'error': 'busy'})
        provider = OpenAICompatibleProvider(self.config(), httpx.MockTransport(respond))
        result = provider.generate('x', [match()])
        self.assertEqual(result['status'], 'rate_limited')
        self.assertEqual(len(calls), 2)

    def test_gateway_configuration_signs_exact_payload_without_gemini_key(self):
        calls=[]
        content=json.dumps({'answer':'supported','claims':[{'text':'supported','citation_ids':['chunk-1']}]})
        def respond(request):
            calls.append(request)
            self.assertNotIn('authorization', request.headers)
            self.assertRegex(request.headers['x-gateway-timestamp'], r'^\d+$')
            self.assertRegex(request.headers['x-gateway-signature'], r'^[a-f0-9]{64}$')
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':content}}]})
        with patch.dict(os.environ, {
            'RAG_LLM_PROVIDER':'gemini','RAG_LLM_ENABLED':'1','RAG_LLM_MODEL':'owner-selected',
            'RAG_LLM_GATEWAY_URL':'https://gateway.invalid/v1',
            'RAG_LLM_GATEWAY_SECRET':'gateway-fixture','RAG_LLM_PROMPT_VERSION':'v3',
        }, clear=True):
            config=config_from_env()
        self.assertTrue(config.gateway_mode)
        self.assertEqual(config.api_key,'gateway-fixture')
        result=OpenAICompatibleProvider(config,httpx.MockTransport(respond)).generate('x',[match()],prompt_version='v3')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(calls),1)

    def test_malformed_json_container_fails_closed(self):
        for value in ('[]', 'null', '42'):
            provider = OpenAICompatibleProvider(self.config(), self.transport({'choices': [{'message': {'content': value}}]}))
            self.assertEqual(provider.generate('x', [match()])['status'], 'provider_error')

    def test_empty_evidence_never_calls_provider(self):
        def fail(request):
            raise AssertionError('External request without evidence')
        provider = OpenAICompatibleProvider(self.config(), httpx.MockTransport(fail))
        self.assertEqual(provider.generate('x', [])['status'], 'insufficient_evidence')

    def test_prompt_version_is_fail_closed_and_prompt_hash_is_stable(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig("https://provider.invalid/v1", "fixture-model", "test-secret", 3, True, "v3"),
            self.transport({"choices": []}),
        )
        result = provider.generate("x", [match()], prompt_version="other")
        self.assertEqual(result["failure_reason"], "PROMPT_VERSION_MISMATCH")
        self.assertRegex(prompt_sha256(), r"^[a-f0-9]{64}$")

    def test_truncated_or_malformed_provider_envelope_fails_closed(self):
        valid=json.dumps({'answer':'x','claims':[{'text':'x','citation_ids':['chunk-1']}]})
        for payload in ([], None, {'choices':[None]}, {'choices':[{'finish_reason':'length','message':{'content':valid}}]}):
            with self.subTest(payload=payload):
                provider=OpenAICompatibleProvider(self.config(),self.transport(payload))
                self.assertEqual(provider.generate('x',[match()])['status'],'provider_error')

    def test_length_truncation_retries_once_with_larger_concise_request(self):
        calls=[]
        valid=json.dumps({'answer':'x','claims':[{'text':'x','citation_ids':['chunk-1']}]})
        def respond(request):
            calls.append(json.loads(request.content))
            if len(calls) == 1:
                return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{'}}]})
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':valid}}]})
        result=OpenAICompatibleProvider(self.config(),httpx.MockTransport(respond)).generate('x',[match()])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['max_tokens'],1200)
        self.assertEqual(calls[1]['max_tokens'],2000)
        self.assertIn('Trả lời súc tích',calls[1]['messages'][0]['content'])

    def test_length_truncation_twice_fails_with_safe_reason(self):
        payload={'choices':[{'finish_reason':'length','message':{'content':'{'}}]}
        provider=OpenAICompatibleProvider(self.config(),self.transport(payload))
        result=provider.generate('x',[match()])
        self.assertEqual(result['status'],'provider_error')
        self.assertEqual(result['failure_reason'],'OUTPUT_TRUNCATED')

    def test_null_answer_discards_explanatory_claims(self):
        content=json.dumps({'answer':None,'claims':[{'text':'No evidence','citation_ids':['not-retrieved']}]})
        provider=OpenAICompatibleProvider(self.config(),self.transport({'choices':[{'message':{'content':content}}]}))
        self.assertEqual(provider.generate('x',[match()]),{'status':'insufficient_evidence','answer':None,'claims':[]})

    def test_null_answer_retries_once_with_identical_frozen_prompt(self):
        calls=[]
        null_content=json.dumps({'answer':None,'claims':[]})
        valid=json.dumps({'answer':'supported','claims':[{'text':'supported','citation_ids':['chunk-1']}]})
        def respond(request):
            calls.append(json.loads(request.content))
            content=null_content if len(calls)==1 else valid
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':content}}]})
        result=OpenAICompatibleProvider(self.config(),httpx.MockTransport(respond)).generate('x',[match()])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['messages'],calls[1]['messages'])
        self.assertEqual(calls[0]['max_tokens'],calls[1]['max_tokens'])

    def test_citations_must_be_in_actual_prompt(self):
        first, second = match(), match()
        first['chunk']['text'] = 'x' * 14000
        second['chunk']['chunk_id'] = 'omitted'
        content = json.dumps({'answer': 'unsupported', 'claims': [{'text': 'unsupported', 'citation_ids': ['omitted']}]})
        provider = OpenAICompatibleProvider(self.config(), self.transport({'choices': [{'message': {'content': content}}]}))
        self.assertEqual(provider.generate('x', [first, second])['status'], 'provider_error')


if __name__=="__main__":
    unittest.main()
