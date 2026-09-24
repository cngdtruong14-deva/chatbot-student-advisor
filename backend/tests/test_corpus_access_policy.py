import unittest
from uuid import uuid4

from app.api import APIError, allow_corpus


class CorpusAccessPolicyTests(unittest.TestCase):
    def actor(self, role):
        return {"id": uuid4(), "role": role}

    def test_authenticated_student_can_open_published_utt_corpus(self):
        self.assertIsNone(allow_corpus(self.actor("student"), "utt_corpus"))

    def test_utt_test_is_admin_only(self):
        for role in ("student", "advisor"):
            with self.subTest(role=role), self.assertRaises(APIError) as raised:
                allow_corpus(self.actor(role), "utt_test")
            self.assertEqual((raised.exception.code, raised.exception.status), ("FORBIDDEN", 403))
        self.assertIsNone(allow_corpus(self.actor("admin"), "utt_test"))

    def test_non_student_cannot_open_published_utt_corpus(self):
        with self.assertRaises(APIError) as raised:
            allow_corpus(self.actor("advisor"), "utt_corpus")
        self.assertEqual((raised.exception.code, raised.exception.status), ("FORBIDDEN", 403))


if __name__ == "__main__":
    unittest.main()
