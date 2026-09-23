"""Fast checks for the public CSV importer contract; DB behaviors use integration tests."""
import unittest

from app.imports import SUPPORTED_IMPORTS, TEMPLATES


class ImportContractsTests(unittest.TestCase):
    def test_every_supported_import_has_a_downloadable_template(self):
        self.assertEqual(SUPPORTED_IMPORTS, set(TEMPLATES))
        for import_type, template in TEMPLATES.items():
            with self.subTest(import_type=import_type):
                header, example = template.splitlines()
                self.assertTrue(header and example)
                self.assertEqual(len(header.split(",")), len(example.split(",")))

    def test_student_template_requires_existing_account_link(self):
        self.assertIn("account_email", TEMPLATES["students"].splitlines()[0].split(","))
        self.assertNotIn("password", TEMPLATES["students"].lower())

    def test_score_import_is_separate_from_component_definitions(self):
        self.assertIn("grade_components", SUPPORTED_IMPORTS)
        self.assertIn("grade_component_scores", SUPPORTED_IMPORTS)


if __name__ == "__main__":
    unittest.main()
