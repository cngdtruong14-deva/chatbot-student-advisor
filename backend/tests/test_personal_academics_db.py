"""Disposable DB only; rollback all fixture writes. Owner executes this suite."""
import os
import copy
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app import api
from app.store import engine, one, run
from app.test_safety import require_test_environment
from tests.test_personal_academics import fixture


@unittest.skipUnless(os.environ.get('ADVISOR_TEST_DATABASE') == '1', 'isolated disposable database only')
class PersonalAcademicDBTests(unittest.TestCase):
    def setUp(self):
        require_test_environment()
        self.conn = engine().connect()
        self.addCleanup(self.conn.close)
        outer = self.conn.begin()
        self.addCleanup(outer.rollback)
        self.users = []
        for _ in range(2):
            uid = uuid4()
            run(self.conn, "INSERT INTO app.users(id,email,password_hash,role) VALUES(:u,:e,'test-only','student')", u=uid, e=f'{uid}@test.invalid')
            run(self.conn, "INSERT INTO app.onboarding_profiles(user_id,display_name) VALUES(:u,'Fixture')", u=uid)
            self.users.append({'id':uid,'role':'student'})
        self.user = self.users[0]
        @contextmanager
        def isolated():
            with self.conn.begin_nested():
                yield self.conn
        for name in ('app.personal_academics.transaction', 'app.api.transaction'):
            p = patch(name, isolated); p.start(); self.addCleanup(p.stop)
        overrides = app.dependency_overrides.copy()
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(overrides)))
        app.dependency_overrides[api.actor] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def save(self, payload=None, revision=0):
        return self.client.put('/api/v1/account/transcript', json={
            'expected_revision':revision, 'transcript':fixture() if payload is None else payload})

    def test_owner_isolation_conflict_and_history(self):
        self.assertEqual(self.save().status_code, 200)
        stale = self.save()
        self.assertEqual(stale.status_code, 409)

        self.assertEqual(stale.json()['error']['code'], 'ACADEMIC_REVISION_CONFLICT')
        row = one(self.conn, 'SELECT count(*) AS n FROM app.personal_transcript_history WHERE user_id=:u', u=self.user['id'])
        self.assertEqual(row['n'], 1)
        self.user = self.users[1]
        view = self.client.get('/api/v1/account/transcript').json()['data']
        self.assertEqual(view['revision'], 0)
        self.assertEqual(view['transcript']['attempts'], [])
        bad = self.client.put('/api/v1/account/transcript', json={
            'expected_revision':0,'transcript':fixture(),'user_id':str(self.users[0]['id'])})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(one(self.conn, 'SELECT count(*) AS n FROM app.students WHERE user_id=:u', u=self.user['id'])['n'], 0)

    def test_goal_zero_future_and_impossible_target(self):
        self.assertEqual(self.save().status_code, 200)
        response = self.client.post('/api/v1/account/required-gpa', json={'target_gpa':'4','future_gpa_credits':'1'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['data']['required_future_gpa'], '13.500000')
        self.assertEqual(response.json()['data']['feasibility'], 'impossible')
        response = self.client.post('/api/v1/account/required-gpa', json={'target_gpa':'3','future_gpa_credits':'0'})
        self.assertIsNone(response.json()['data']['required_future_gpa'])
        self.assertEqual(response.json()['data']['feasibility'], 'completed_target_not_met')

    def test_simulation_does_not_write_and_goal_uses_saved_revision(self):
        self.assertEqual(self.save().status_code, 200)
        before = self.client.get('/api/v1/account/transcript').json()['data']
        scenario = copy.deepcopy(fixture())
        scenario['attempts'][3]['score'] = '10'
        response = self.client.post('/api/v1/account/simulations', json={'expected_revision':1,'transcript':scenario})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['data']['persisted'])
        self.assertEqual(response.json()['data']['after']['summary']['gpa_4'], '3.600000')
        self.assertEqual(self.client.get('/api/v1/account/transcript').json()['data'], before)
        self.assertEqual(one(self.conn, 'SELECT count(*) AS n FROM app.personal_transcript_history WHERE user_id=:u', u=self.user['id'])['n'], 1)
        goal = self.client.post('/api/v1/account/required-gpa', json={'expected_revision':1,'target_gpa':'3','future_gpa_credits':'5'})
        self.assertEqual(goal.status_code, 200, goal.text)
        # (3*(5+5)-10.5)/5 = 3.9.
        self.assertEqual(goal.json()['data']['required_future_gpa'], '3.900000')
        stale = self.client.post('/api/v1/account/required-gpa', json={'expected_revision':0,'target_gpa':'3','future_gpa_credits':'5'})
        self.assertEqual(stale.status_code, 409)

    def test_chat_rest_parity_for_personal_summary(self):
        from app.chat_service import dispatch
        self.assertEqual(self.save().status_code, 200)
        rest = self.client.get('/api/v1/account/academic-summary').json()['data']
        chat = dispatch('GPA bảng điểm tự khai của tôi', self.user)
        self.assertEqual(chat['status'], 'completed')
        self.assertEqual(chat['cards'][0]['data']['summary'], rest['summary'])
        self.assertEqual(chat['cards'][0]['data']['academic_revision'], rest['academic_revision'])

        # The ordinary user wording must resolve to the saved account-owned
        # transcript even without an app.students link or an explicit source.
        natural = dispatch('GPA của tôi hiện tại là bao nhiêu?', self.user)
        self.assertEqual(natural['status'], 'completed')
        self.assertEqual(natural['cards'][0]['data']['summary'], rest['summary'])

    def test_personal_plan_uses_saved_transcript_and_course_plan_fails_closed(self):
        from app.chat_service import dispatch
        self.assertEqual(self.save().status_code, 200)
        goal = self.client.post('/api/v1/account/required-gpa', json={
            'target_gpa':'3', 'future_gpa_credits':'5'}).json()['data']
        self.assertEqual(goal['academic_revision'], 1)
        self.assertEqual(goal['required_future_gpa'], '3.900000')
        recommendation = dispatch('gợi ý môn nên học', self.user)
        self.assertEqual(recommendation['status'], 'needs_clarification')
        self.assertEqual(recommendation['cards'], [])
        self.assertIn('chưa đủ dữ liệu chương trình/tiên quyết', recommendation['answer'].lower())

    def test_chat_personal_whatif_followup_and_no_write(self):
        from app.chat_service import dispatch
        self.assertEqual(self.save().status_code, 200)
        before = self.client.get('/api/v1/account/transcript').json()['data']
        first = dispatch('mô phỏng tự khai CS1 được 10', self.user)
        self.assertEqual(first['status'], 'needs_clarification')
        result = dispatch('CS1 lần 2 được 10', self.user, first)
        self.assertEqual(result['status'], 'completed')
        data = result['cards'][0]['data']
        self.assertFalse(data['persisted'])
        self.assertEqual(data['after']['summary']['gpa_4'], '3.600000')
        self.assertEqual(self.client.get('/api/v1/account/transcript').json()['data'], before)

    def test_chat_personal_letter_projection_and_course_lookup(self):
        from app.chat_service import dispatch
        self.assertEqual(self.save().status_code, 200)
        before = self.client.get('/api/v1/account/transcript').json()['data']
        projected = dispatch('giả sử bảng điểm tự khai có thêm 5 tín chỉ đều đạt A', self.user)
        self.assertEqual(projected['status'], 'completed')
        self.assertEqual(projected['cards'][0]['data']['projection']['projected_gpa'], '3.050000')
        self.assertIn('A (4)', projected['answer'])
        lookup = dispatch('điểm môn CS1 trong bảng điểm tự khai', self.user)
        self.assertEqual(lookup['status'], 'completed')
        self.assertIn('CS1 — Course 1', lookup['answer'])
        self.assertIn('8/10', lookup['answer'])
        self.assertIn('5/10', lookup['answer'])
        self.assertEqual(self.client.get('/api/v1/account/transcript').json()['data'], before)

    def test_chat_whatif_rejects_changed_revision(self):
        from app.chat_service import dispatch
        self.assertEqual(self.save().status_code, 200)
        first = dispatch('mô phỏng tự khai CS1 được 10', self.user)
        self.assertEqual(self.save(revision=1).status_code, 200)
        result = dispatch('CS1 lần 2 được 10', self.user, first)
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertEqual(result['cards'], [])
        self.assertIn('đã thay đổi', result['answer'])

    def test_profile_required_and_non_student_forbidden(self):
        uid = uuid4()
        run(self.conn, "INSERT INTO app.users(id,email,password_hash,role) VALUES(:u,:e,'test-only','student')", u=uid,e=f'{uid}@test.invalid')
        self.user = {'id':uid, 'role':'student'}
        response = self.save()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'PERSONAL_PROFILE_REQUIRED')
        self.user = {'id':uid, 'role':'advisor'}
        self.assertEqual(self.client.get('/api/v1/account/transcript').status_code, 403)
