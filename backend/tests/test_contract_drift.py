import json
from pathlib import Path
import unittest
from app.main import app


class ContractDriftTests(unittest.TestCase):
    def test_openapi_matches_reviewed_working_baseline(self):
        expected = json.loads(Path(__file__).with_name('openapi.snapshot.json').read_text(encoding='utf-8'))
        self.assertEqual(app.openapi(), expected, 'Review changes; regenerate snapshot/types explicitly, never auto-update in CI')

    def test_core_responses_have_explicit_schema(self):
        schema = app.openapi()
        for path, method in [('/academic/required-gpa', 'post'), ('/academic/target-score', 'post'),
                             ('/academic/simulations', 'post'), ('/students/{student_id}/academic-summary', 'get'),
                             ('/chat/sessions/{session_id}/messages', 'post'), ('/recommendations/courses', 'get')]:
            response = schema['paths']['/api/v1' + path][method]['responses']['200']['content']['application/json']['schema']
            self.assertIn('$ref', response)
        self.assertNotIn('requestBody', schema['paths']['/api/v1/recommendations/courses']['get'])

    def test_stage2_account_contract_is_explicit(self):
        schema = app.openapi()
        stage2 = [
            ('/api/v1/auth/register', 'post', 'Registration'),
            ('/api/v1/auth/recover', 'post', 'Recovery'),
            ('/api/v1/admin/account-invites', 'post', None),
            ('/api/v1/admin/accounts/{user_id}/recovery', 'post', None),
            ('/api/v1/account/profile', 'put', 'PersonalProfile'),
        ]
        for path, method, request_schema in stage2:
            operation = schema['paths'][path][method]
            response = operation['responses']['200']['content']['application/json']['schema']
            self.assertIn('$ref', response, f'{method.upper()} {path} needs a typed response')
            if request_schema:
                request = operation['requestBody']['content']['application/json']['schema']
                self.assertEqual(request['$ref'], '#/components/schemas/' + request_schema)
        profile_get = schema['paths']['/api/v1/account/profile']['get']['responses']['200']['content']['application/json']['schema']
        self.assertIn('$ref', profile_get)

    def test_stage2_inputs_forbid_privilege_and_ownership_fields(self):
        schemas = app.openapi()['components']['schemas']
        for name in ('Registration', 'Recovery', 'PersonalProfile'):
            self.assertFalse(schemas[name].get('additionalProperties', True), name)
        self.assertNotIn('role', schemas['Registration']['properties'])
        self.assertNotIn('student_id', schemas['Registration']['properties'])
        self.assertNotIn('user_id', schemas['PersonalProfile']['properties'])

    def test_stage3_contract_has_revision_and_typed_responses(self):
        schema = app.openapi()
        for path, method in [('/account/transcript','get'),('/account/transcript','put'),
                             ('/account/academic-summary','get'),('/account/simulations','post'),
                             ('/account/required-gpa','post'),('/account/target-score','post')]:
            response = schema['paths']['/api/v1'+path][method]['responses']['200']['content']['application/json']['schema']
            self.assertIn('$ref', response)
        body = schema['paths']['/api/v1/account/transcript']['put']['requestBody']['content']['application/json']['schema']
        dto = schema['components']['schemas'][body['$ref'].rsplit('/',1)[-1]]
        self.assertIn('expected_revision', dto['required'])
        self.assertFalse(dto['additionalProperties'])
        self.assertNotIn('user_id', dto['properties'])
