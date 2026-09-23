# Chạy và kiểm thử ứng dụng local

## Chạy ở repository

```powershell
.\ops\Start-Local.ps1
.\ops\Test-Foundation.ps1
docker compose exec api python -m app.seed --demo
```

Mở http://localhost:3000; dùng `student@demo.local` với mật khẩu vừa nhập trong terminal.
Không có mật khẩu mặc định được commit. Seed có tính idempotent và không reset mật khẩu đã tồn tại.
Nếu cần đổi password, phải dùng thao tác quản trị có chủ đích, không chạy seed để giả định đã đổi.

Backend đọc `JWT_SECRET` riêng từ `.env`; Initialize-Application chỉ thêm khi thiếu, không đổi DB credentials.
Không gửi `.env`, output compose config hay password vào chat. API/web chỉ bind localhost.
Không có provider key vẫn tính GPA, required GPA, target score, what-if và recommendation được.

## Frontend developer

```powershell
cd frontend
npm ci
npm run build
```

Build trong Docker là đường chạy đã kiểm chứng. `npm run dev` có proxy `/api` và `/health`
tới localhost:8000; giữ Host để auth kiểm tra cùng origin. Dev proxy chưa nằm trong browser E2E lần này.

## CSV hiện được hỗ trợ

Admin UI trên Tổng quan: chọn CSV, dry-run trước rồi mới bật nút ghi.
Transport: `POST /api/v1/admin/imports/academic?dry_run=true|false`, `Content-Type: text/csv`, Bearer Admin.
Giới hạn 512.000 bytes/1.000 rows, UTF-8. Chỉ enrollment của danh mục/sinh viên đã có.

```csv
student_code,course_code,semester_code,attempt_no,status,final_score,policy_version,data_origin
DEMO-001,DEMO-C26,DEMO-T5,1,graded,7.5,DEMO-1,synthetic
```

Sai một dòng → không ghi cả batch. Retry cùng actor/type/hash không ghi trùng.
Thay đổi thật tăng academic_revision một lần/student/transaction. Dry-run không ghi học vụ.
Không nhập finalized score cho enrollment đã có component grade bằng đường import này; cần importer component đúng policy.
Các CSV students/courses/curriculum/offerings/prerequisites/grade_components **chưa được hỗ trợ**.

## Kiểm thử an toàn

`Test-Foundation.ps1` chạy unit + least-privilege + readiness và xác nhận capabilities cần auth.
`tests.integration_application` có ghi fixture; **chỉ** chạy trên database test độc lập:

```powershell
docker compose exec -T -e ADVISOR_TEST_DATABASE=1 api python -m tests.integration_application
```

Không bật flag này trên DB sử dụng thật. Test thay password tài khoản demo trong DB test.
Trong lần này stack audit `sic-app-audit-0906`, ports13010/18010, volume riêng. Không xóa volume gốc hay audit.

Browser test `frontend/tests/e2e.cjs` hiện dành cho máy Windows này (Chrome + Playwright + audit directory đã kiểm tra),
không phải CI portable. Nó dùng password random qua stdin, kiểm tra login/GPA/calculator/chat/reload/mobile/logout,
không in password. Ảnh nằm ngoài repo trong workspace `output/app-build/evidence`.
