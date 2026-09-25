"""Independent numeric expectations for self-reported v2. Not executed by author."""
import copy
import unittest
from pydantic import ValidationError
from app.personal_academics import PersonalTranscript, PersonalTarget, summarize, calculate_target
from advisor_core.academic_policy_v2 import project_gpa_4


def fixture():
    return {'terms': [
        {'code':'T1','start_date':'2024-01-01','end_date':'2024-06-30'},
        {'code':'T2','start_date':'2024-07-01','end_date':'2024-12-31'}],
        'attempts': [
            {'code':'CS1','title':'Course 1','term':'T1','attempt':1,'credits':'3','score':'8','status':'graded','available_on':'2024-06-01'},
            {'code':'CS2','title':'Course 2','term':'T1','attempt':1,'credits':'2','score':None,'status':'absent_or_barred'},
            {'code':'PE101','title':'PE','term':'T1','attempt':1,'credits':'1','score':'3','status':'graded','available_on':'2024-06-01'},
            {'code':'CS1','title':'Course 1','term':'T2','attempt':2,'credits':'3','score':'5','status':'graded','available_on':'2024-12-01'},
            {'code':'CS2','title':'Course 2','term':'T2','attempt':2,'credits':'2','score':'7','status':'graded','available_on':'2024-12-01'},
            {'code':'PE101','title':'PE','term':'T2','attempt':2,'credits':'1','score':'4','status':'graded','available_on':'2024-12-01'},
        ], 'required_credits':'10'}


class PersonalAcademicTests(unittest.TestCase):
    def test_future_gpa_projection_is_four_point_only_and_non_mutating(self):
        summary = summarize(PersonalTranscript.model_validate(fixture()), 2).summary.model_dump()
        result = project_gpa_4(summary, '4', '5')
        self.assertEqual(result['current_gpa'], '2.100000')
        self.assertEqual(result['projected_gpa'], '3.050000')
        self.assertEqual(result['projected_gpa_credits'], '10.000000')
        self.assertEqual(summary['gpa_4'], '2.100000')

    def test_latest_lower_score_replaces_old_and_non_gpa_still_earns_credit(self):
        result = summarize(PersonalTranscript.model_validate(fixture()), 2)
        # (5*3 + 7*2)/5=5.8; (1.5*3 + 3*2)/5=2.1, PE adds 1 earned credit only.
        self.assertEqual(result.summary.gpa_10, '5.800000')
        self.assertEqual(result.summary.gpa_4, '2.100000')
        self.assertEqual(result.summary.gpa_credits, '5.000000')
        self.assertEqual(result.summary.earned_credits, '6.000000')
        self.assertEqual(result.remaining_credits, '4.000000')
        self.assertEqual(result.data_origin, 'self_reported')

    def test_unknown_date_uses_declared_term_for_ui_without_claiming_complete_history(self):
        result = summarize(PersonalTranscript.model_validate(fixture()), 1)
        first = result.semester_history[0]
        # The absent result has no exact date, but its declared T1 membership is
        # enough for the self-reported term summary. Coverage remains partial.
        self.assertEqual(first.cumulative.gpa_4, '2.100000')
        self.assertEqual(first.cumulative.gpa_10, '4.800000')
        self.assertEqual(first.unknown_result_dates, 1)
        self.assertEqual(first.coverage, 'partial')
        self.assertIsNone(result.trend_4)

    def test_pending_retake_does_not_replace_resolved_score(self):
        payload = fixture()
        payload['attempts'].append({'code':'CS1','title':'Pending','term':'T2','attempt':3,'credits':'3','status':'pending'})
        result = summarize(PersonalTranscript.model_validate(payload), 1)
        self.assertEqual(result.summary.gpa_4, '2.100000')
        self.assertEqual(result.summary.pending_attempts, 1)

    def test_term_gpa_remains_available_when_all_resolved_rows_lack_exact_dates(self):
        payload = fixture()
        for attempt in payload['attempts']:
            if attempt['status'] != 'pending':
                attempt['available_on'] = None
        result = summarize(PersonalTranscript.model_validate(payload), 1)
        self.assertEqual(result.semester_history[0].term.gpa_4, '2.100000')
        self.assertEqual(result.semester_history[1].term.gpa_4, '2.100000')
        self.assertEqual(result.semester_history[1].cumulative.gpa_4, '2.100000')
        self.assertEqual(result.semester_history[0].coverage, 'partial')
        self.assertEqual(result.semester_history[1].coverage, 'partial')
        self.assertIsNone(result.trend_4)

    def test_absence_is_zero_but_pending_is_not_zero(self):
        payload = fixture()
        payload['attempts'] = payload['attempts'][:3]
        result = summarize(PersonalTranscript.model_validate(payload), 1)
        self.assertEqual(result.summary.gpa_4, '2.100000')
        self.assertEqual(result.summary.gpa_10, '4.800000')
        self.assertEqual(result.summary.non_gpa_incomplete_courses, ['PE101'])

    def test_no_gpa_courses_and_empty_transcript_have_no_gpa(self):
        payload = fixture()
        payload['attempts'] = [payload['attempts'][-1]]
        for source in (payload, {}):
            result = summarize(PersonalTranscript.model_validate(source), 0)
            self.assertIsNone(result.summary.gpa_4)
            self.assertIsNone(result.summary.gpa_10)

    def test_validation_duplicate_credits_status_and_order(self):
        original = fixture()
        for key, value in [('credits','4'),('term','T1'),('score',None),('attempt',True)]:
            payload = copy.deepcopy(original)
            payload['attempts'][3][key] = value
            if key == 'term':
                payload['attempts'][0]['term'] = 'T2'
                payload['attempts'][0]['available_on'] = '2024-08-01'
            with self.subTest(key=key), self.assertRaises(ValidationError):
                PersonalTranscript.model_validate(payload)
        payload = fixture()
        payload['attempts'].append(copy.deepcopy(payload['attempts'][0]))
        with self.assertRaises(ValidationError):
            PersonalTranscript.model_validate(payload)

    def test_target_one_unknown_independent_expected(self):
        result = calculate_target(PersonalTarget(target_score='8', components=[
            {'weight':'0.4','score':'7'}, {'weight':'0.6','score':None}]))
        self.assertEqual(result.required_score, '8.666667')
        self.assertEqual(result.feasibility, 'achievable')
        self.assertFalse(result.persisted)
        with self.assertRaises(ValidationError):
            PersonalTarget(target_score='8', components=[{'weight':'.4'}, {'weight':'.6'}])

    def test_grade_boundaries_on_four_point_scale(self):
        for score, expected in [('3.999999','0.000000'),('4','1.000000'),('5','1.500000'),
                                ('5.5','2.000000'),('6.5','2.500000'),('7','3.000000'),
                                ('8','3.500000'),('8.5','4.000000')]:
            payload = fixture()
            payload['attempts'] = [dict(payload['attempts'][0], score=score)]
            with self.subTest(score=score):
                self.assertEqual(summarize(PersonalTranscript.model_validate(payload), 0).summary.gpa_4, expected)

    def test_target_impossible_and_invalid_weights(self):
        result = calculate_target(PersonalTarget(target_score='10', components=[
            {'weight':'.5','score':'2'},{'weight':'.5'}]))
        self.assertEqual(result.required_score, '18.000000')
        self.assertEqual(result.feasibility, 'impossible')
        with self.assertRaises(ValidationError):
            PersonalTarget(target_score='8', components=[{'weight':'.4','score':'7'},{'weight':'.5'}])
