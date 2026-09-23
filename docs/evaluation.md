# Đánh giá bản source public

Các kết quả dưới đây được chạy trực tiếp trên bản export sạch ngày 22/09/2026,
không kế thừa trạng thái PASS của repository phát triển.

## Kết quả đã xác minh

- Python AST: 148 file, 0 lỗi cú pháp.
- Notebook: 10 file JSON hợp lệ, 0 output, 0 execution count.
- Markdown: 0 liên kết tương đối bị thiếu.
- OpenAPI/frontend contract: 45 operation tồn tại trong snapshot đã review.
- Docker build: API PASS; frontend type-check, Vite build và 24 assertion UI PASS.
- Integration trên PostgreSQL disposable: 31/31 PASS, chỉ dùng dữ liệu synthetic.
- Backend: 206 test, 204 PASS, 2 capability skip.
- Browser E2E: PASS ở viewport 360/768/1280, gồm phân quyền, luồng học vụ,
  citation, chat history/evidence sidebar và recovery flow.
- ML/Colab source: 10/10 test PASS; ML isolation/schema checks PASS.
- Cleanup: container, volume và network của project kiểm thử đã được gỡ; stack
  local đang chạy không bị tác động.

Hai skip backend phải được giữ nguyên khi trình bày kết quả:

1. Không có approved model artifact trong image test, nên chưa xác minh real-model parity.
2. Fixture cô lập không có môn học lại, nên ca parity lịch sử học lại không chạy;
   logic tương ứng vẫn có unit test trực tiếp.

## Chưa được chứng minh

- Chưa chạy secret scan toàn lịch sử vì bản export chưa khởi tạo Git repository.
- Chưa chạy Release Security Gate trên GitHub của repository public.
- Chưa kiểm chứng model/corpus production, Gemini thật, TLS, firewall, backup/restore,
  retention hoặc giám sát trên staging.
- Không dùng benchmark cũ để tuyên bố production readiness. Metric phải đi kèm
  split, model provenance, corpus version và điều kiện chạy.

Kết quả này chứng minh bản source có thể build và vượt qua suite cô lập được nêu
trên; không thay thế go-live checklist của môi trường production.
