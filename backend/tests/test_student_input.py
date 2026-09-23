import unittest
from pydantic import ValidationError
from app.api import SelfReportedPreview, self_reported_preview, APIError
from fastapi.testclient import TestClient
from app.main import app
from app.api import actor
from unittest.mock import patch


class StudentInputTests(unittest.TestCase):
    def test_pol01_two_scales_weighted_per_course(self):
        result = self.preview([self.row('8', '3'), self.row('5', '2', code='CS02')], policy='POL-01-demo')
        self.assertEqual(result['summary']['gpa_10'], '6.800000')
        self.assertEqual(result['summary']['gpa_4'], '2.700000')
        self.assertEqual(result['summary']['policy_version'], 'POL-01-demo')
        self.assertEqual(result['goal']['policy_version'], 'POL-01-demo')
        self.assertFalse(result['persisted'])

    def test_pol01_retake_highest_and_zero(self):
        result = self.preview([self.row('8'), self.row('4', attempt=2)], policy='POL-01-demo')
        self.assertEqual(result['summary']['gpa_4'], '3.500000')
        self.assertEqual(result['summary']['gpa_credits'], '3.000000')
        result = self.preview([self.row('0')], policy='POL-01-demo')
        self.assertEqual(result['summary']['gpa_4'], '0.000000')

    def test_v2_preview_uses_latest_attempt_and_excludes_pe(self):
        result = self.preview([self.row('9'), self.row('4', attempt=2), self.row('9', '1', code='PE101')],
                              policy='ACADEMIC-DEMO-2.0.0', future_gpa_credits='3', target_gpa='2')
        self.assertEqual(result['summary']['gpa_4'], '1.000000')
        self.assertEqual(result['summary']['gpa_10'], '4.000000')
        self.assertEqual(result['summary']['earned_credits'], '4.000000')
        self.assertEqual(result['goal']['policy_version'], 'ACADEMIC-DEMO-2.0.0')

    def test_http_auth_validation_and_no_transcript_writes(self):
        client = TestClient(app)
        payload = dict(courses=[self.row()])
        self.assertEqual(client.post('/api/v1/academic/self-reported/preview', json=payload).status_code, 401)
        app.dependency_overrides[actor] = lambda: {'role': 'student'}
        try:
            with patch('app.api.transaction', side_effect=AssertionError('Preview must not access transcript')):
                response = client.post('/api/v1/academic/self-reported/preview', json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()['data']['persisted'])
                self.assertEqual(client.post('/api/v1/academic/self-reported/preview', json={**payload, 'student_id': 'other'}).status_code, 422)
        finally:
            app.dependency_overrides.pop(actor, None)

    def preview(self, courses, **kwargs):
        body = SelfReportedPreview(courses=courses, **kwargs)
        return self_reported_preview(body, {'role': 'student'})['data']

    def row(self, score='8', credits='3', attempt=1, code='CS01'):
        return dict(code=code, score=score, credits=credits, attempt=attempt)

    def test_weighted_gpa(self):
        result = self.preview([self.row(), self.row('5', '2', code='CS02')])
        self.assertEqual(result['summary']['cumulative_gpa'], '2.720000')
        self.assertEqual(result['summary']['earned_credits'], '5.000000')
        self.assertEqual(result['summary']['data_origin'], 'self_reported')
        self.assertFalse(result['persisted'])

    def test_retake_and_goal(self):
        result = self.preview([self.row('2'), self.row('8', attempt=2)], target_gpa='3.6', future_gpa_credits='3')
        self.assertEqual(result['summary']['gpa_credits'], '3.000000')
        self.assertEqual(result['goal']['required_future_gpa'], '4.000000')

    def test_zero_score(self):
        result = self.preview([self.row('0')])
        self.assertEqual(result['summary']['cumulative_gpa'], '0.000000')
        self.assertEqual(result['summary']['earned_credits'], '0.000000')

    def test_duplicate_or_changed_credits(self):
        for row in [self.row(code='cs01'), self.row(credits='4', attempt=2)]:
            with self.assertRaises(APIError): self.preview([self.row(), row])

    def test_invalid_input(self):
        for row in [self.row('11'), self.row('-1'), self.row(credits='0'), self.row('NaN'), self.row(attempt=0)]:
            with self.assertRaises(ValidationError): self.preview([row])
        with self.assertRaises(ValidationError): self.preview([])

    def test_non_student_denied(self):
        with self.assertRaises(APIError) as error:
            self_reported_preview(SelfReportedPreview(courses=[self.row()]), {'role': 'advisor'})
        self.assertEqual(error.exception.status, 403)


if __name__ == '__main__': unittest.main()
