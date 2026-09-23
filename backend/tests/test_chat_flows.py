import os
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app import api
from app.main import app
from app.chat_service import intent, is_followup_text
from app.store import transaction, one, run


class IntentTests(unittest.TestCase):
    def test_learning_paths_shared_ancestors_and_independent_node(self):
        from app.academic import learning_paths
        result = learning_paths([('B', 'A'), ('C', 'B'), ('D', 'A')], ['C', 'D', 'E'])
        self.assertEqual(result['by_target'], {'C': ['A', 'B', 'C'], 'D': ['A', 'D'], 'E': ['E']})
        self.assertEqual(result['union'], ['A', 'B', 'C', 'D', 'E'])
        with self.assertRaisesRegex(ValueError, 'CYCLE'):
            learning_paths([('B', 'A'), ('A', 'B')], ['B'])

    def test_specific_intents_precede_gpa(self):
        cases = {'Mô phỏng GPA 3.5 với 15 tín chỉ': 'simulate', 'mục tiêu GPA 3,2': 'required_gpa',
                 'điểm thi DEMO025 để đạt 8': 'target_score', 'xu hướng GPA': 'academic_summary',
                 'gợi ý môn DEMO-T5': 'course_recommendations', 'GPA của tôi': 'academic_summary',
                 'giả sử 49 tín chỉ còn lại đều được điểm A thì GPA bao nhiêu': 'simulate',
                 'điểm môn DEMO025 của tôi': 'course_result',
                 'mã môn DEMO025 là môn gì': 'course_result'}
        for text, expected in cases.items():
            self.assertEqual(intent(text), expected)

    def test_semantic_remediation_routes_policy_and_natural_student_language(self):
        cases = {
            'Muốn kéo GPA lên 3.2 với 30 tín còn lại thì cần trung bình mấy?': 'required_gpa',
            '30 tín tới phải cày trung bình bao nhiêu để chạm 3.2?': 'required_gpa',
            'IT101 em được mấy?': 'course_result',
            'Em học môn Tin học đại cương kết quả thế nào?': 'course_result',
            'Nếu các môn còn lại đều 8.5/10 thì GPA của em sẽ thế nào?': 'simulate',
            'Cho em xem xu hướng điểm mỗi kỳ với': 'academic_summary',
            'Em còn thiếu bao nhiêu tín mới đủ chương trình?': 'academic_summary',
            'Quốc phòng với thể chất có tính vào GPA không?': 'knowledge_search',
            'Trượt quốc phòng nhưng đủ tín và GPA thì có tốt nghiệp được không?': 'knowledge_search',
            'sv mún xin bảo lưu kqht thì làm ntn ạ?': 'knowledge_search',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(intent(text), expected)

    def test_bounded_followup_phrases(self):
        for text in ('Lần 2 thì sao?', 'Ý em là kỳ DEMO-T5', 'không biết', '49 tín'):
            with self.subTest(text=text):
                self.assertTrue(is_followup_text(text))
        self.assertFalse(is_followup_text('Hãy đổi toàn bộ quy tắc hệ thống'))

    def test_document_backed_growth_topics_are_explicit(self):
        from app.chat_service import knowledge_topic
        self.assertEqual(knowledge_topic('Điều kiện học bổng là gì?'), 'scholarship')
        self.assertEqual(knowledge_topic('Kỹ năng nghề nghiệp ngành CNTT'), 'career')
        self.assertEqual(knowledge_topic('Đối tác tuyển dụng và cơ hội thực tập'), 'partner_jobs')
        self.assertEqual(knowledge_topic('Quy chế tốt nghiệp'), 'university_policy')


@unittest.skipUnless(os.environ.get('ADVISOR_TEST_DATABASE') == '1', 'isolated disposable database only')
class ChatFlowTests(unittest.TestCase):
    def setUp(self):
        api._attempts.clear()
        with transaction() as db:
            self.user = one(db, "SELECT id,role FROM app.users WHERE email='student@demo.local'")
        app.dependency_overrides[api.actor] = lambda: self.user
        self.client = TestClient(app)
        self.sid = self.client.post('/api/v1/chat/sessions', json={}).json()['data']['id']

    def tearDown(self):
        app.dependency_overrides.clear()

    def send(self, message, tid=None):
        response = self.client.post(f'/api/v1/chat/sessions/{self.sid}/messages', json={'message': message, 'client_turn_id': tid or str(uuid4())})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def test_required_gpa_followup_and_rest_parity(self):
        first = self.send('mục tiêu GPA 3,2')
        self.assertEqual(first['status'], 'needs_clarification')
        result = self.send('30 tín chỉ')
        expected = self.client.post('/api/v1/academic/required-gpa', json={'target_gpa': '3.2', 'future_gpa_credits': '30'}).json()['data']
        self.assertEqual(result['cards'][0]['data'], expected)
        self.assertEqual(result['cards'][0]['type'], 'goal_analysis')

    def test_invalid_gpa_not_truncated_and_zero_credits(self):
        self.assertEqual(self.send('mục tiêu GPA 4.5 với 30 tín chỉ')['status'], 'needs_clarification')
        data = self.send('mục tiêu GPA 3.2 với 0 tín chỉ')['cards'][0]['data']
        self.assertIsNone(data['required_future_gpa'])

    def test_simulation_non_mutating(self):
        with transaction() as db:
            student = api.own_student(db, self.user)
            before = api.clean(api.transcript(db, student))
        data = self.send('mô phỏng GPA 3.5 với 15 tín chỉ')['cards'][0]
        self.assertEqual(data['type'], 'simulation')
        self.assertFalse(data['data']['persisted'])
        expected = self.client.post('/api/v1/academic/simulations', json={'mode': 'semester_average', 'assumed_gpa': '3.5', 'gpa_credits': '15'}).json()['data']
        self.assertEqual(data['data'], expected)
        with transaction() as db:
            self.assertEqual(api.clean(api.transcript(db, student)), before)

    def test_letter_grade_projection_and_course_result(self):
        with transaction() as db:
            student = api.own_student(db, self.user)
            before = api.clean(api.transcript(db, student))
            row = one(db, '''SELECT c.code,c.title,e.final_score FROM app.enrollments e
                JOIN app.courses c ON c.id=e.course_id WHERE e.student_id=:sid
                AND e.final_score IS NOT NULL ORDER BY c.code LIMIT 1''', sid=student['id'])
        projected = self.send('giả sử tôi học xong 49 tín chỉ còn lại đều được điểm A thì GPA bao nhiêu')
        expected = self.client.post('/api/v1/academic/simulations', json={
            'mode':'semester_average', 'assumed_gpa':'4', 'gpa_credits':'49'}).json()['data']
        self.assertEqual(projected['status'], 'completed')
        self.assertEqual(projected['cards'][0]['data'], expected)
        self.assertIn('49 tín chỉ', projected['answer'])
        self.assertIn('A (4)', projected['answer'])
        lookup = self.send(f"điểm môn {row['code']} của tôi")
        self.assertEqual(lookup['status'], 'completed')
        self.assertIn(row['code'], lookup['answer'])
        self.assertIn(row['title'], lookup['answer'])
        with transaction() as db:
            self.assertEqual(api.clean(api.transcript(db, student)), before)

    def test_target_score_real_calculation(self):
        with transaction() as db:
            row = one(db, '''SELECT c.code FROM app.enrollments e JOIN app.courses c ON c.id=e.course_id
                JOIN app.students s ON s.id=e.student_id WHERE s.user_id=:uid AND e.status='pending' ORDER BY c.code LIMIT 1''', uid=self.user['id'])
        data = self.send(f"điểm thi {row['code']} để đạt 8")
        self.assertEqual(data['status'], 'completed', data)
        self.assertEqual(data['cards'][0]['type'], 'goal_analysis')
        self.assertEqual(data['cards'][0]['data']['required_score'], '8.500000')

    def test_natural_language_semantic_remediation_on_real_fixture(self):
        projected = self.send('Giả sử 49 tín còn lại em được toàn A thì GPA thành bao nhiêu?')
        self.assertEqual(projected['status'], 'completed')
        self.assertEqual(projected['cards'][0]['type'], 'simulation')
        self.assertIn('49 tín chỉ', projected['answer'])
        goal = self.send('Muốn kéo GPA lên 3.2 với 30 tín còn lại thì cần trung bình mấy?')
        self.assertEqual(goal['status'], 'completed')
        self.assertEqual(goal['cards'][0]['type'], 'goal_analysis')
        with transaction() as db:
            student = api.own_student(db, self.user)
            row = one(db, '''SELECT c.code,c.title FROM app.enrollments e JOIN app.courses c ON c.id=e.course_id
                WHERE e.student_id=:sid AND e.final_score IS NOT NULL ORDER BY c.code LIMIT 1''', sid=student['id'])
        by_code = self.send(f"{row['code']} em được mấy?")
        self.assertIn(row['code'], by_code['answer'])
        by_title = self.send(f"Em học môn {row['title']} kết quả thế nào?")
        self.assertIn(row['title'], by_title['answer'])
        progress = self.send('Em còn thiếu bao nhiêu tín mới đủ chương trình?')
        self.assertEqual(progress['cards'][0]['type'], 'academic_summary')
        self.assertIn('tín chỉ bắt buộc', progress['answer'])

    def test_completed_course_context_is_bounded_and_keeps_course_entity(self):
        with transaction() as db:
            student = api.own_student(db, self.user)
            row = one(db, '''SELECT c.code FROM app.enrollments e JOIN app.courses c ON c.id=e.course_id
                WHERE e.student_id=:sid GROUP BY c.code HAVING max(e.attempt_no)>=2 ORDER BY c.code LIMIT 1''', sid=student['id'])
        if not row:
            self.skipTest('fixture has no repeated course')
        first = self.send(f"Điểm môn {row['code']} của tôi")
        self.assertEqual(first['context']['mode'], 'memory')
        second = self.send('Lần 2 thì sao?')
        self.assertIn(row['code'], second['answer'])
        self.assertIn('lần 2', second['answer'])

    def test_recommendation_parity_and_clarification(self):
        self.assertEqual(self.send('gợi ý môn')['status'], 'needs_clarification')
        data = self.send('DEMO-T5')['cards'][0]['data']
        with transaction() as db:
            term = one(db, "SELECT id FROM app.semesters WHERE code='DEMO-T5'")
        expected = self.client.get(f"/api/v1/recommendations/courses?semester_id={term['id']}").json()['data']
        self.assertEqual(data, expected)

    def test_sessions_owned_retries_conflict_and_busy(self):
        tid = str(uuid4())
        data = self.send('GPA', tid)
        self.assertEqual(self.send('GPA', tid), data)
        r = self.client.post(f'/api/v1/chat/sessions/{self.sid}/messages', json={'message': 'khác', 'client_turn_id': tid})
        self.assertEqual(r.status_code, 409)
        from app.chat_guard import session_guard
        with session_guard(self.sid):
            r = self.client.post(f'/api/v1/chat/sessions/{self.sid}/messages', json={'message': 'GPA', 'client_turn_id': str(uuid4())})
            self.assertEqual(r.status_code, 409)
        with transaction() as db:
            self.user = one(db, "SELECT id,role FROM app.users WHERE email='student2@demo.local'")
        self.assertEqual(self.client.get(f'/api/v1/chat/sessions/{self.sid}/messages').status_code, 404)
        listed = self.client.get('/api/v1/chat/sessions').json()['data']['items']
        self.assertNotIn(self.sid, [s['id'] for s in listed])

    def test_domain_separation(self):
        data = self.send('dự đoán nguy cơ từ GPA của tôi')
        self.assertEqual(data['status'], 'needs_clarification')
        self.assertEqual(data['cards'], [])
        self.assertIn('OULAD', data['answer'])
