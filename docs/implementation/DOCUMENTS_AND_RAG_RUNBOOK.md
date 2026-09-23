# Nạp tài liệu và truy xuất trong chat

## Sử dụng tại localhost:3000

1. Đăng nhập bằng tài khoản Admin hiện có.
2. Mở **Quản lý tài liệu**. Chọn tài liệu mới hoặc thêm phiên bản cho tài liệu cũ.
3. Nhập tiêu đề, nguồn, phiên bản, ngày hiệu lực. Dán văn bản hoặc chọn TXT/MD UTF-8 (tối đa 400 KB), PDF/DOCX (tối đa 5 MB). PDF tối đa 200 trang; nội dung sau trích xuất tối đa 100.000 ký tự.
4. Với PDF/DOCX, API chỉ trích văn bản vào ô xem trước; không lưu file gốc. Kiểm tra kỹ vì PDF scan không có lớp chữ cần OCR và sẽ bị từ chối.
5. Chọn **Lưu bản nháp**. Nội dung được lưu trong PostgreSQL, trạng thái `pending`.
6. Mở **Hướng dẫn xử lý bản nháp** dưới tài liệu. Chạy hai lệnh được hiển thị trong PowerShell tại thư mục repository:

```powershell
docker compose exec api python -m app.knowledge ingest --version-id <UUID>
docker compose exec api python -m app.knowledge activate --version-id <UUID>
```

7. Chọn **Cập nhật trạng thái**: tài liệu cần ở trạng thái `active`. Sau đó mở **Trợ lý học tập**, hỏi về nội dung vừa nạp và mở tiêu đề trích dẫn để xem nguyên văn.

API nhận bản nháp; xử lý/chỉ mục và kích hoạt tuân theo API contract cùng schema hiện hành trong `contracts/`. Không có tác vụ nền chạy ngầm sau khi upload. CLI ingestion lỗi sẽ ghi `failed`; có thể chạy lại cùng ID. Một lần xử lý thành công không tạo thêm chunks khi chạy lại.

## Tài liệu và phạm vi

Kho hiện chỉ phục vụ `demo_academic`, `data_origin=synthetic`. Không dùng màn hình này để gắn nhãn quy chế chính thức của trường. Hai tài liệu mẫu đã nạp: DEMO-1 và DEMO — Hướng dẫn kho tài liệu.

PostgreSQL lưu nội dung, metadata, phiên bản và các đoạn văn. Chroma lưu embedding; E5 `intfloat/multilingual-e5-small` được pin revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, CPU. Database quyết định bản nào được phép truy xuất trước khi query vector.

Kho chỉ truy xuất bản active đúng ngày hiệu lực và loại tài liệu. Hai phiên bản cùng tài liệu không được chồng khoảng hiệu lực khi cùng active. Để ngừng công bố một bản:

```powershell
docker compose exec api python -m app.knowledge retire --version-id <UUID>
```

Lệnh này giữ nội dung lịch sử; không xóa tài liệu. Phiên bản mới có ID và chunks riêng. Nếu muốn giữ khả năng truy xuất lịch sử với `as_of`, khai báo các khoảng hiệu lực không chồng nhau ngay từ đầu.

## Khởi tạo ở máy mới

Build/migrate bằng `ops/Start-Local.ps1`, seed tài khoản theo RUN_APPLICATION.md. Cache embedding cần được tải một lần:

```powershell
docker compose exec -e HF_HUB_OFFLINE=0 -e RAG_ALLOW_DOWNLOAD=1 api python -m app.knowledge seed-demo
```

Sau đó retrieval chạy offline với cache trong `vectorstore/`; không cần phiên Colab hoặc LLM key. Model/index và dữ liệu local được Git ignore. Backup PostgreSQL và `vectorstore` trước khi chuyển máy; không xóa volume để khắc phục lỗi.

## Bật sinh câu trả lời bằng LLM (tùy chọn)

Adapter dùng endpoint tương thích `POST <base_url>/chat/completions`. Mặc định `RAG_LLM_ENABLED=0`; retrieval/citation vẫn hoạt động khi không có provider. Chỉ ghi cấu hình vào `.env` local, không gửi key qua chat và không commit `.env`:

```dotenv
RAG_LLM_ENABLED=1
RAG_LLM_BASE_URL=https://provider.example/v1
RAG_LLM_MODEL=approved-model-name
RAG_LLM_API_KEY=<provider-key-from-secret-store>
RAG_LLM_TIMEOUT_SECONDS=20
```

Khởi động lại API bằng `docker compose up -d --wait api web`, rồi kiểm tra `/api/v1/system/capabilities` sau khi đăng nhập. `llm=configured` chỉ xác nhận đủ cấu hình; cần một smoke test thật và benchmark riêng trước khi gọi provider/model là đã sẵn sàng cho Capstone.

LLM chỉ nhận câu hỏi và tối đa 14.000 ký tự từ các chunk đã qua bộ lọc scope/version. Prompt coi chỉ dẫn trong tài liệu là dữ liệu. Backend chỉ chấp nhận JSON có answer/claims, từ chối toàn bộ kết quả nếu một claim thiếu citation hoặc citation không thuộc các chunk đã retrieval, và dựng nội dung hiển thị lại từ chính các claim đã kiểm tra. Timeout, 401/403, 429, lỗi schema và lỗi provider đều quay về `insufficient_evidence`; GPA/what-if không phụ thuộc LLM. Không nhập dữ liệu sinh viên thật vào chat khi chưa duyệt quyền sử dụng dữ liệu của provider.

## ML nghiên cứu

Model `final-002` đã nhận, kiểm tra hash và kích hoạt sau parity với 20 smoke cases. 20 hồ sơ công khai từ smoke_inputs được gán cho Admin tại màn hình Kết nối nghiên cứu. Đây là inference smoke/demo, không phải lần đánh giá final-test mới.

API lưu prediction và giải thích linear contribution theo model/snapshot gốc; quyền xem lịch sử và giải thích theo owner/Admin. Giải thích là đóng góp vào log-odds, không chứng minh nhân quả.

## Giới hạn

- PDF và DOCX có lớp văn bản được hỗ trợ; OCR cho PDF scan và `.doc` cũ chưa hỗ trợ.
- Adapter LLM đã có và được test với provider mô phỏng; provider/key/model thật chưa được cấu hình hoặc đánh giá.
- Corpus mở rộng chưa có benchmark độc lập; không áp dụng số liệu Colab cũ cho corpus mới.
- Danh sách Admin hiển thị tối đa 200 phiên bản; luồng hiện dành cho corpus nhỏ Capstone, chưa phải ingestion quy mô lớn.
