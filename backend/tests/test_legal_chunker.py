"""Unit tests for hierarchical legal and regulatory chunker."""
import unittest
from advisor_core.legal_chunker import chunk_hierarchical_legal


class LegalChunkerTests(unittest.TestCase):
    def test_preserves_article_and_clauses_with_page_markers(self):
        text = """## Trang 1

QUY CHẾ ĐÀO TẠO ĐẠI HỌC

Chương I: NHỮNG QUY ĐỊNH CHUNG

Điều 1. Phạm vi điều chỉnh
1. Quy chế này quy định về tổ chức và quản lý đào tạo trình độ đại học theo hệ thống tín chỉ.
2. Quy chế này áp dụng cho toàn thể sinh viên và giảng viên Nhà trường.

## Trang 2

Điều 2. Thời gian đào tạo
1. Thời gian kế hoạch chuẩn toàn khóa là 4 năm đối với hệ đại học chính quy.
* Lưu ý: Thời gian tối đa để sinh viên hoàn thành chương trình không được vượt quá 8 năm (gấp 2 lần kế hoạch chuẩn).
2. Sinh viên học vượt có thể rút ngắn thời gian đào tạo tối đa 1 năm.
"""
        chunks = chunk_hierarchical_legal(
            text,
            document_id="doc-test-1",
            version_id="ver-1",
            scope="utt_corpus",
            source="test_policy.pdf",
            valid_from="2026-09-19",
        )
        self.assertGreater(len(chunks), 0)

        # Verify page numbers
        p1_chunks = [c for c in chunks if c["page_number"] == 1]
        p2_chunks = [c for c in chunks if c["page_number"] == 2]
        self.assertTrue(len(p1_chunks) > 0)
        self.assertTrue(len(p2_chunks) > 0)

        # Verify conditions/exceptions preservation: "* Lưu ý:" must be in the same chunk as Điều 2 Khoản 1
        note_chunk = next(c for c in chunks if "Lưu ý:" in c["text"])
        self.assertIn("thời gian tối đa", note_chunk["text"].lower())
        self.assertIn("kế hoạch chuẩn", note_chunk["text"].lower())
        self.assertEqual(note_chunk["page_number"], 2)
        self.assertIn("Điều 2", note_chunk["locator_label"])

    def test_unpaged_forms_do_not_fabricate_page_numbers(self):
        form_text = """ĐƠN XIN HỌC LẠI

Kính gửi: Ban Giám hiệu, Phòng Đào tạo
Tôi tên là: Nguyễn Văn A
Mã sinh viên: SV0001 Lớp: CNTT1
Nay tôi làm đơn này kính xin được đăng ký học lại học phần:
Toán cao cấp 1 (Mã HP: MAT101)
Học phí sẽ được đóng đầy đủ theo quy định.
Kính mong Nhà trường xem xét giải quyết.
"""
        chunks = chunk_hierarchical_legal(
            form_text,
            document_id="doc-form-1",
            version_id="ver-1",
            scope="utt_corpus",
            source="ĐƠN XIN HỌC LẠI.docx",
            valid_from="2026-09-19",
        )
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        # Crucial requirement: DO NOT FABRICATE PAGE NUMBERS
        self.assertIsNone(chunk["page_number"])
        self.assertEqual(chunk["locator_type"], "form")
        self.assertIn("Biểu mẫu", chunk["locator_label"])
        self.assertNotIn("Trang 1", chunk["locator_label"])

    def test_table_preservation_and_provenance(self):
        table_text = """## Trang 5

Điều 9. Quy đổi thang điểm
Bảng quy đổi thang điểm 10 sang điểm chữ:
| Thang điểm 10 | Điểm chữ | Thang điểm 4 |
| 8.5 - 10.0 | A | 4.0 |
| 8.0 - 8.4 | B+ | 3.5 |
| 7.0 - 7.9 | B | 3.0 |
| 6.0 - 6.9 | C+ | 2.5 |
| 5.5 - 5.9 | C | 2.0 |
| 5.0 - 5.4 | D+ | 1.5 |
| 4.0 - 4.9 | D | 1.0 |
| < 4.0 | F | 0.0 |
* Lưu ý: Điểm F là điểm không đạt, sinh viên phải đăng ký học lại.
"""
        chunks = chunk_hierarchical_legal(
            table_text,
            document_id="doc-table-1",
            version_id="ver-1",
            scope="utt_corpus",
            source="quy_che.pdf",
            valid_from="2026-09-19",
        )
        table_chunk = next(c for c in chunks if "| Thang điểm 10 |" in c["text"])
        self.assertIn("Điểm F là điểm không đạt", table_chunk["text"])
        self.assertEqual(table_chunk["page_number"], 5)
        self.assertGreater(table_chunk["char_end"], table_chunk["char_start"])
        self.assertEqual(table_chunk["chunker_version"], "utt_legal_v1")


if __name__ == "__main__":
    unittest.main()
