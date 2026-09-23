# Cố vấn học tập thông minh

Nền tảng hỗ trợ sinh viên theo dõi kết quả học tập, lập kế hoạch tích lũy tín
chỉ, mô phỏng GPA, tra cứu tài liệu có dẫn nguồn và tham khảo định hướng nghề
nghiệp. Sản phẩm được thiết kế để có thể cấu hình cho nhiều cơ sở đào tạo.

Phiên bản hiện tại đang **pilot với sinh viên UTT** và sử dụng kho tài liệu UTT
để kiểm chứng chức năng RAG. Đây không phải cổng thông tin chính thức của UTT.
Tên nguồn UTT vẫn được giữ trong từng tài liệu và trích dẫn để bảo đảm khả năng
đối chiếu.

## Chức năng chính

- Đăng ký, đăng nhập và phân quyền sinh viên, cố vấn, quản trị viên.
- Hồ sơ học tập, GPA thang 4/thang 10, lịch sử học kỳ và tiến độ tín chỉ.
- Tính GPA mục tiêu, điểm cần đạt và mô phỏng what-if không sửa bảng điểm.
- Chatbot điều phối các công cụ học vụ xác định và RAG có dẫn nguồn.
- Nạp, trích xuất, duyệt và phát hành tài liệu PDF, DOCX, ảnh scan hoặc văn bản.
- Dự đoán rủi ro học tập bằng artifact ML đã được phê duyệt.
- Career Skill Gap cho chương trình HTTT pilot: 27 kỹ năng, 6 hướng nghề nghiệp
  và 91 ánh xạ học phần–kỹ năng.

## Kiến trúc

- Frontend: React, TypeScript, Vite và Nginx.
- Backend: FastAPI, SQLAlchemy và Alembic.
- Dữ liệu: PostgreSQL.
- Tìm kiếm tài liệu: Chroma, keyword/dense retrieval và grounded generation tùy
  cấu hình.
- Đóng gói: Docker Compose.

## Chạy local

Yêu cầu Docker Desktop ở chế độ Linux containers và PowerShell.

```powershell
Copy-Item .env.example .env
# Điền các secret local trong .env; không commit file này.
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\Start-Local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\Test-Foundation.ps1
```

Mặc định:

- Web: `http://localhost:3000`
- API: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health/ready`

Tạo dữ liệu minh họa local theo hướng dẫn trong
[`docs/runbooks/CAREER_SKILL_GAP.md`](docs/runbooks/CAREER_SKILL_GAP.md) và các
runbook tương ứng. Script seed yêu cầu xác nhận rõ ràng và không được dùng trên
dữ liệu production.

## Cấu hình runtime

Các giá trị nhạy cảm như mật khẩu PostgreSQL, JWT secret và provider API key chỉ
được đặt trong `.env` hoặc secret store của môi trường triển khai. Tham khảo
`.env.production.example`; không đưa secret vào Git.

Tài liệu PDF/DOCX, database, vectorstore, model binary và dữ liệu người dùng là
dữ liệu runtime. Chúng không nằm trong source public và được quản trị viên nạp
lại thông qua quy trình vận hành của hệ thống.

## Kiểm thử

```powershell
docker compose build api web
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\Test-ApplicationIsolated.ps1 -ApiImage <api-image>
```

Bộ kiểm thử cô lập tạo database riêng, vô hiệu hóa provider LLM và không ghi
fixture vào database đang chạy.

## Tài liệu

- [Mục lục tài liệu](docs/README.md)
- [Kiến trúc thư mục](docs/PROJECT_STRUCTURE.md)
- [Báo cáo ML/RAG/Capstone](docs/reports/README.md)
- [Runbook triển khai production](docs/implementation/STAGE9_PRODUCTION_SECURITY_RUNBOOK.md)

## Trạng thái dữ liệu pilot

- Dữ liệu học vụ và ML demo là synthetic, không phải hồ sơ sinh viên UTT thật.
- Kho RAG hiện tại sử dụng tài liệu UTT do chủ dự án cung cấp và phê duyệt cho
  pilot; câu trả lời luôn cần giữ citation và phạm vi hiệu lực.
- Điểm Career Skill Gap phản ánh mức phủ kỹ năng trong bộ mapping demo, không
  phải xác suất được tuyển dụng.

## Giấy phép

Copyright © 2026. All rights reserved. Repository này không cấp giấy phép mã
nguồn mở; không được sao chép, phân phối hoặc khai thác ngoài phạm vi được chủ
sở hữu cho phép.
