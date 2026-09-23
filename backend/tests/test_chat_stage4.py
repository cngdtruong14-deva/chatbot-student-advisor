"""Owner-run deterministic orchestration checks; no provider, DB or model needed."""
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from app.chat_service import dispatch, intent


class Stage4RoutingTests(unittest.TestCase):
    def setUp(self):
        self.user = {'id': 'owner-fixture', 'role': 'student'}
        for target, value in [('app.api.transaction', lambda: nullcontext(None)),
                              ('app.api.one', lambda *a, **k: {'revision': 1, 'id': 'demo'})]:
            p = patch(target, value); p.start(); self.addCleanup(p.stop)

    def test_source_answer_keeps_original_goal_and_slots(self):
        with patch('app.personal_academics.goal', return_value={'data': {'required_future_gpa': '3.9'}}) as goal:
            first = dispatch('mục tiêu GPA 3 với 5 tín chỉ', self.user)
            self.assertEqual(first['status'], 'needs_clarification')
            second = dispatch('bảng điểm cá nhân', self.user, first)
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(str(goal.call_args.args[0].target_gpa), '3')
            self.assertEqual(str(goal.call_args.args[0].future_gpa_credits), '5')

    def test_personal_goal_multiturn(self):
        with patch('app.personal_academics.goal', return_value={'data': {}}) as goal:
            first = dispatch('mục tiêu GPA tự khai 3,2', self.user)
            second = dispatch('30 tín chỉ', self.user, first)
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(str(goal.call_args.args[0].target_gpa), '3.2')
            self.assertEqual(str(goal.call_args.args[0].future_gpa_credits), '30')

    def test_cancel_clears_context(self):
        first = dispatch('mục tiêu GPA tự khai 3', self.user)
        result = dispatch('hủy', self.user, first)
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('context', result)

    def test_clarification_limit(self):
        previous = {'status': 'needs_clarification', 'context': {
            'tool': 'required_gpa', 'params': {'source': 'personal'}, 'rounds': 4}}
        result = dispatch('30 tín chỉ', self.user, previous)
        self.assertNotIn('context', result)
        self.assertIn('4 lượt', result['answer'])

    def test_index_unavailable_does_not_leak_exception(self):
        with patch('app.api.own_student', return_value=None), patch('app.knowledge.search', return_value={
                'retrieval_status': 'unavailable', 'reason': 'PRIVATE_PATH_OR_SECRET'}):
            result = dispatch('Thủ tục xin giấy xác nhận?', self.user)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['citations'], [])
        self.assertNotIn('PRIVATE_PATH_OR_SECRET', str(result))

    def test_provider_timeout_has_no_fabricated_evidence(self):
        with patch('app.api.own_student', return_value=None), patch('app.knowledge.search', side_effect=TimeoutError):
            result = dispatch('Thủ tục xin giấy xác nhận?', self.user)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['cards'], [])

    def test_topic_switch_does_not_reuse_academic_slots(self):
        first = dispatch('mục tiêu GPA tự khai 3', self.user)
        evidence = {'status': 'insufficient_evidence', 'generation_status': 'provider_unavailable',
                    'citations': [], 'answer': ''}
        with patch('app.api.own_student', return_value=None), patch('app.knowledge.search', return_value=evidence) as search:
            result = dispatch('Thủ tục xin giấy xác nhận?', self.user, first)
        search.assert_called_once()
        self.assertNotIn('context', result)

    def test_ambiguous_policy_reference_requires_antecedent(self):
        with patch('app.knowledge.search') as search:
            result = dispatch('Cái điều kiện ấy là sao?', self.user, corpus_scope='utt_corpus')
        search.assert_not_called()
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertIn('nêu rõ chủ đề', result['answer'])

    def test_short_memory_keeps_scholarship_topic_for_followup(self):
        answered = {'status': 'answered', 'generation_status': 'completed', 'citations': [],
                    'answer': 'Có điều kiện.', 'rag_mode': 'approved_grounded_capstone_high_stakes'}
        with patch('app.knowledge.resolve_actor_scope', return_value={'major': None, 'cohort': None, 'resolved': True}), \
             patch('app.knowledge.search', return_value=answered) as search:
            first = dispatch('Ai không được xét học bổng?', self.user, corpus_scope='utt_corpus')
            second = dispatch('Nếu kỳ trước em bị kỷ luật thì sao?', self.user, first, corpus_scope='utt_corpus')
        self.assertEqual(first['context']['topic'], 'scholarship')
        self.assertEqual(second['context']['topic'], 'scholarship')
        self.assertIn('Về học bổng khuyến khích học tập', search.call_args.args[0])

    def test_policy_query_rewrites_are_bounded(self):
        evidence = {'status': 'insufficient_evidence', 'generation_status': 'insufficient_evidence',
                    'citations': [], 'answer': None}
        with patch('app.knowledge.resolve_actor_scope', return_value={'major': None, 'cohort': None, 'resolved': True}), \
             patch('app.knowledge.search', return_value=evidence) as search:
            dispatch('Những ai không được xét học bổng khuyến khích học tập?', self.user,
                     corpus_scope='utt_corpus')
        self.assertEqual(search.call_args.args[0],
            'Điều kiện được xét học bổng khuyến khích học tập và các trường hợp không đủ điều kiện.')

    def test_unsupported_a_minus_is_not_silently_converted(self):
        self.assertEqual(intent('Nếu 12 tín tới đều A- thì sao?'), 'simulate')
        result = dispatch('Nếu 12 tín tới đều A- thì sao?', self.user)
        self.assertEqual(result['status'], 'needs_clarification')
