# Cấu trúc repository

| Đường dẫn | Nội dung |
|---|---|
| `backend/` | FastAPI, migration Alembic, nghiệp vụ và kiểm thử backend |
| `frontend/` | React/TypeScript, Vite, Nginx và kiểm thử giao diện |
| `contracts/` | JSON Schema và hợp đồng artifact dùng chung |
| `packages/advisor_core/` | Logic dùng chung cho backend và pipeline ML |
| `ml/` | Notebook, cấu hình, pipeline đánh giá/huấn luyện và corpus demo công khai |
| `ops/` | Khởi tạo local, test cô lập, backup/restore và cấu hình production |
| `.github/workflows/` | CI và release security gate |
| `artifacts/` | Chỉ chứa placeholder; artifact runtime không được commit |
| `docs/` | Tài liệu vận hành và kỹ thuật công khai |

Database, tài liệu người dùng, vectorstore, secret và model binary phải được cấp ở runtime.

