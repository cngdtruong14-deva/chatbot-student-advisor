# API

FastAPI cung cấp OpenAPI tại `/docs` khi chạy local. Các nhóm chức năng chính gồm:

- `/api/v1/auth`: đăng nhập, refresh và logout.
- `/api/v1/students`: hồ sơ và tóm tắt học vụ của người dùng được phép.
- `/api/v1/academic`: GPA, mục tiêu điểm và mô phỏng.
- `/api/v1/chat`: phiên chat và message idempotency.
- `/api/v1/knowledge`: tìm kiếm evidence theo quyền và corpus scope.
- `/health/ready`: readiness check.

Contract chi tiết được sinh từ source hiện tại; client phải xử lý lỗi xác thực, phân quyền, thiếu hồ sơ và thiếu evidence.
