import os
import unittest
from decimal import Decimal

from app.career import build_skill_profile, calculate_gap, resolve_career
from app.career_data import (
    CAREERS, CAREER_SKILLS, CERTIFICATIONS, EXCLUDED_COURSES, SKILLS,
    load_course_skills, validate_reference_data,
)
from app.chat_service import intent
from app.seed_httt_career_demo import load_rows as load_demo_rows


class CareerReferenceTests(unittest.TestCase):
    def test_reference_data_is_complete_and_versioned(self):
        mappings = load_course_skills()
        catalog = {row['course_code'] for row in mappings} | EXCLUDED_COURSES
        validate_reference_data(catalog)
        self.assertEqual(len(SKILLS), 27)
        self.assertEqual(len(CAREERS), 6)
        self.assertEqual(len(CAREER_SKILLS), 39)
        self.assertEqual(len(CERTIFICATIONS), 8)
        self.assertEqual(len(mappings), 91)
        self.assertEqual(len({row['course_code'] for row in mappings}), 47)
        self.assertEqual(len(EXCLUDED_COURSES), 25)
        self.assertEqual({row['course_code'] for row in mappings} | EXCLUDED_COURSES, catalog)

    def test_demo_grade_fixture_has_reviewable_shape_and_retake(self):
        rows = load_demo_rows()
        self.assertEqual(len(rows), 17)
        attempts = [row for row in rows if row['course_code'] == 'DC3HT60']
        self.assertEqual([(row['attempt_no'], row['final_score']) for row in attempts], [('1', '3.5'), ('2', '8.0')])

    def test_career_router_and_aliases_do_not_hijack_gpa(self):
        self.assertEqual(intent('Những kỹ năng nào cần có cho định hướng nghề nghiệp?'), 'career')
        self.assertEqual(intent('Tôi thiếu gì để làm Data Analyst?'), 'career')
        self.assertEqual(intent('Tôi phù hợp nghề nào trong ngành HTTT?'), 'career')
        self.assertEqual(intent('GPA của tôi'), 'academic_summary')
        self.assertEqual(resolve_career('CR04'), 'CR04')
        self.assertEqual(resolve_career('Em muốn làm quản trị CSDL'), 'CR05')


class CareerScoringTests(unittest.TestCase):
    def mappings(self):
        base = {"credits": Decimal('3'), "category": "Technical"}
        return [
            {**base, "course_id": "A", "course_code": "A", "course_title": "A", "skill_code": "SK01", "skill_name": "Skill 1", "contribution_weight": Decimal('1')},
            {**base, "course_id": "B", "course_code": "B", "course_title": "B", "skill_code": "SK01", "skill_name": "Skill 1", "contribution_weight": Decimal('1')},
            {**base, "course_id": "C", "course_code": "C", "course_title": "C", "skill_code": "SK02", "skill_name": "Skill 2", "contribution_weight": Decimal('1')},
        ]

    def test_only_latest_passed_attempt_is_evidence(self):
        attempts = [
            {"course_id": "A", "attempt_no": 1, "status": "graded", "final_score": Decimal('8'), "minimums_met": True},
            {"course_id": "A", "attempt_no": 2, "status": "graded", "final_score": Decimal('3'), "minimums_met": True},
            {"course_id": "B", "attempt_no": 1, "status": "graded", "final_score": Decimal('6'), "minimums_met": True},
            {"course_id": "C", "attempt_no": 1, "status": "P", "final_score": None, "minimums_met": True},
        ]
        profile = build_skill_profile(self.mappings(), attempts)
        skills = {row['skill_id']: row for row in profile['skills']}
        self.assertEqual([row['course_code'] for row in skills['SK01']['evidence_courses']], ['B'])
        self.assertEqual(skills['SK01']['proficiency_5'], '3.000000')
        self.assertTrue(skills['SK02']['matched'])
        self.assertIsNone(skills['SK02']['proficiency_5'])

    def test_match_is_weighted_binary_coverage_and_unknown_is_missing(self):
        profile = build_skill_profile(self.mappings(), [
            {"course_id": "B", "attempt_no": 1, "status": "graded", "final_score": Decimal('7'), "minimums_met": True},
        ])
        requirements = [
            {"skill_id": "SK01", "skill_name": "Skill 1", "category": "Technical", "importance_weight": Decimal('.6'), "required_level": None},
            {"skill_id": "SK02", "skill_name": "Skill 2", "category": "Technical", "importance_weight": Decimal('.4'), "required_level": None},
        ]
        result = calculate_gap({"career_code": "T", "title": "Test"}, requirements, profile, [])
        self.assertEqual(result['match_score'], '60.000000')
        self.assertEqual([row['skill_id'] for row in result['missing_skills']], ['SK02'])
        self.assertEqual(result['recommended_courses'][0]['course_code'], 'C')


@unittest.skipUnless(os.environ.get('ADVISOR_TEST_DATABASE') == '1', 'isolated disposable database only')
class CareerDatabaseTests(unittest.TestCase):
    def test_migration_reference_counts_and_generic_requirements(self):
        from app.career import career_requirements, list_careers
        from app.store import transaction
        with transaction() as db:
            self.assertEqual(len(list_careers(db)), 6)
            data = career_requirements(db, 'CR04')
        self.assertEqual(data['career']['title'], 'Data Analyst')
        self.assertEqual(len(data['skills']), 6)
        self.assertTrue(any(skill['courses'] for skill in data['skills']))

    def test_demo_seed_dry_run_insert_and_idempotency_roll_back(self):
        from uuid import uuid4
        from app.seed_httt_career_demo import seed_on_connection
        from app.store import engine, one, run

        email = f"career-seed-{uuid4().hex[:8]}@test.invalid"
        connection = engine().connect()
        transaction = connection.begin()
        try:
            curriculum = one(connection, "SELECT id FROM app.curricula WHERE code='HTTT-UTT' AND version='2024'")
            self.assertIsNotNone(curriculum)
            user = one(connection, """INSERT INTO app.users(email,password_hash,role)
                VALUES(:email,'test-only','student') RETURNING id""", email=email)
            run(connection, """INSERT INTO app.students(
                user_id,student_code,full_name,curriculum_id,cohort,domain_id,data_origin)
                VALUES(:user,:code,'Career Seed Fixture',:curriculum,'HTTT-TEST','demo_academic','synthetic')""",
                user=user['id'], code=f"CAREER-{uuid4().hex[:8]}", curriculum=curriculum['id'])

            preview = seed_on_connection(connection, email, dry_run=True)
            self.assertEqual(preview['would_insert_at_most'], 17)
            self.assertEqual(preview['existing_rows'], 0)
            first = seed_on_connection(connection, email, dry_run=False)
            self.assertEqual(first['inserted_rows'], 17)
            second = seed_on_connection(connection, email, dry_run=False)
            self.assertEqual(second['inserted_rows'], 0)
            self.assertEqual(second['skipped_existing_rows'], 17)
        finally:
            transaction.rollback()
            connection.close()


if __name__ == '__main__':
    unittest.main()
