import unittest

from app.seed_httt_curriculum import (
    CURRICULUM_CREDITS,
    ELECTIVE_CODES,
    HTTT_COURSES,
    NON_GPA_CODES,
    PREREQUISITES,
    SOURCE_SHA256,
)


class HTTTCatalogTests(unittest.TestCase):
    def test_owner_source_catalog_shape(self):
        codes = [row[0] for row in HTTT_COURSES]
        self.assertEqual(len(codes), 72)
        self.assertEqual(len(set(codes)), 72)
        self.assertEqual(len(ELECTIVE_CODES), 19)
        self.assertEqual(len(NON_GPA_CODES), 8)
        self.assertEqual(sum(code not in ELECTIVE_CODES for code in codes), 53)
        self.assertEqual(sum(row[2] for row in HTTT_COURSES), 199)
        self.assertEqual(CURRICULUM_CREDITS, 157)
        self.assertEqual(SOURCE_SHA256, "974855dbef253e24fe82c85a01866f0665e1b95a5768bd2651203b3515e4151c")

    def test_prerequisites_reference_only_catalog_courses(self):
        codes = {row[0] for row in HTTT_COURSES}
        self.assertEqual(len(PREREQUISITES), 45)
        self.assertEqual(len(set(PREREQUISITES)), 45)
        for course, prerequisite in PREREQUISITES:
            self.assertIn(course, codes)
            self.assertIn(prerequisite, codes)
            self.assertNotEqual(course, prerequisite)

    def test_catalog_does_not_replace_demo_course_namespace(self):
        self.assertFalse(any(row[0].startswith("DEMO-") for row in HTTT_COURSES))


if __name__ == "__main__":
    unittest.main()
