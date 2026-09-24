# Chatbot Student Advisor

Nền tảng cố vấn học tập có thể cấu hình cho nhiều cơ sở đào tạo: quản lý hồ sơ
học tập, tính và mô phỏng GPA, tra cứu tài liệu có dẫn nguồn, cảnh báo rủi ro
học tập và tham khảo định hướng nghề nghiệp.

Phiên bản hiện tại đang **pilot với sinh viên UTT** và dùng catalog Hệ thống
thông tin cùng tài liệu UTT để kiểm chứng. Đây không phải cổng thông tin chính
thức của UTT; dữ liệu học vụ/ML đi kèm repository là dữ liệu mô phỏng.

## Chức năng

- Đăng ký, đăng nhập và phân quyền sinh viên, cố vấn, quản trị viên.
- Hồ sơ học tập; GPA thang 4/thang 10; lịch sử học kỳ và tiến độ tín chỉ.
- Tính GPA mục tiêu, điểm cần đạt và mô phỏng what-if không sửa bảng điểm.
- Chatbot gọi công cụ học vụ xác định, giữ ngữ cảnh ngắn hạn và tìm tài liệu RAG.
- Nạp, trích xuất, duyệt và phát hành PDF, DOCX, ảnh scan hoặc văn bản.
- Trả lời grounded bằng Gemini khi được bật; luôn giữ citation và fail-closed.
- Artifact ML dự báo nguy cơ không hoàn thành theo cutoff ngày 28.
- Career Skill Gap HTTT: 27 kỹ năng, 6 hướng nghề nghiệp, 91 ánh xạ
  học phần–kỹ năng và gợi ý phần còn thiếu.

## Kiến trúc

| Tầng | Công nghệ |
|---|---|
| Web | React 19, TypeScript, Vite, Nginx |
| API | FastAPI, SQLAlchemy, Alembic |
| Database | PostgreSQL 17 |
| RAG | keyword/dense retrieval, Chroma, Gemini grounded generation |
| ML | pandas, scikit-learn, joblib; notebook Colab có governance |
| Đóng gói | Docker Compose; Bicep mẫu cho Azure Container Apps |

Luồng chatbot tách phép tính học vụ khỏi LLM. GPA, kế hoạch tín chỉ và Career
Skill Gap được tính bằng code/dữ liệu có cấu trúc; LLM chỉ diễn giải bằng chứng
được phép, không tự tạo điểm hay quy định.

## Cài đặt nhanh bằng Docker

### 1. Yêu cầu

- Git.
- Docker Desktop chạy Linux containers, Docker Compose v2.
- Windows PowerShell 5.1 hoặc PowerShell 7.
- Khuyến nghị tối thiểu 8 GB RAM và 10 GB ổ trống.

### 2. Tải source và khởi động

```powershell
git clone https://github.com/cngdtruong14-deva/chatbot-student-advisor.git
cd chatbot-student-advisor
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\Start-Local.ps1
```

`Start-Local.ps1` tạo `.env` với mật khẩu database ngẫu nhiên, thêm JWT secret,
build image, chạy migration rồi chờ DB/API/web healthy. Script giữ nguyên `.env`
đã tồn tại và không in secret.

Các địa chỉ mặc định:

- Web: <http://localhost:3000>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>
- Readiness: <http://localhost:8000/health/ready>

Kiểm tra trạng thái và dừng stack:

```powershell
docker compose ps -a
docker compose logs --tail 100 api
docker compose down
```

Không dùng `docker compose down --volumes` nếu cần giữ database local.

## Tài khoản demo và mật khẩu

Repository **không chứa mật khẩu mặc định**. Sau khi stack đã chạy, tạo dữ
liệu demo và nhập một mật khẩu riêng (12–256 ký tự) tại prompt ẩn:

```powershell
docker compose exec -it api python -m app.seed --demo
```

Các tài khoản được tạo:

| Email | Vai trò |
|---|---|
| `student@demo.local` | Sinh viên demo chính |
| `student2@demo.local` | Sinh viên demo thứ hai |
| `advisor@demo.local` | Cố vấn |
| `admin@demo.local` | Quản trị viên |

Mật khẩu bạn nhập áp dụng cho tài khoản mới. Seed là idempotent và không đổi
mật khẩu của tài khoản đã có. Nếu quên, đặt lại có chủ đích:

```powershell
# Prompt ẩn; không truyền mật khẩu trên command line.
.\ops\Set-UserPassword.ps1 -Email admin@demo.local
.\ops\Set-UserPassword.ps1 -Email student@demo.local
# Hoặc đổi cả bốn tài khoản demo:
.\ops\Set-UserPassword.ps1 -AllDemo
```

Production không có tài khoản/mật khẩu dùng chung được commit. Chủ hệ thống
phải đặt mật khẩu riêng hoặc tạo tài khoản mới và lưu trong password manager.

## Dữ liệu HTTT và Career Skill Gap

Migration `0015_htt_catalog` nạp catalog pilot `HTTT-UTT/2024`: 72 học phần,
thuộc ngành Hệ thống thông tin, khoa Công nghệ thông tin. Migration
`0016_career_skills` nạp mapping demo đã duyệt: 27 kỹ năng, 6 nghề, 8 chứng chỉ,
91 ánh xạ và 25 học phần loại có lý do. Migration không tạo điểm sinh viên.

Điểm minh họa nghề nghiệp là opt-in và chỉ chạy sau khi một profile đã được gắn
curriculum `HTTT-UTT`:

```powershell
docker compose exec api python -m app.seed_httt_career_demo
docker compose exec api python -m app.seed_httt_career_demo --confirm SEED_HTTT_CAREER_DEMO
```

Xem [runbook Career Skill Gap](docs/runbooks/CAREER_SKILL_GAP.md). Match score là
mức phủ kỹ năng trong mapping demo, không phải xác suất được tuyển dụng.

## Dataset Academic Demo v2

Hai ZIP synthetic có thể tải trực tiếp trong thư mục [`datasets`](datasets/):

| File | Nội dung | SHA-256 |
|---|---|---|
| `academic-demo-v2-raw-v1.zip` | 1.000 sinh viên mô phỏng, catalog, offering, enrollment và component score; không chứa bảng tài khoản | `41262948214ABEE4268DCEF3EF8188A7E5C3CA365C893FD7CCF6CB57A6319DA3` |
| `academic-demo-v2-normalized-r2.zip` | Audit, policy, manifests, GPA reconciliation và `normalized_enrollments.jsonl` dùng cho Notebook 09 | `A3B4BEA3BF442D620124551399252B45007BF0DFB11D61FA3F02A6F4E90495C9` |

Đây là dữ liệu tự sinh phục vụ demo/capstone, không phải hồ sơ sinh viên thật.
Xem [datasets/README.md](datasets/README.md) để biết schema và cách kiểm tra hash.

## Huấn luyện và đánh giá ML

Quy trình chính là
[`09_academic_demo_v2_train_and_export.ipynb`](ml/notebooks/09_academic_demo_v2_train_and_export.ipynb).
Notebook dùng ZIP normalized ở trên, target `non_completion_at_end`, cutoff ngày
28, split theo sinh viên và chọn giữa Dummy, Logistic Regression và Random
Forest bằng Average Precision trên dev.

Quy trình Colab tóm tắt:

1. Tạo source ZIP sạch từ đúng Git commit và upload vào runtime Python 3.13.
2. Upload `datasets/academic-demo-v2-normalized-r2.zip`.
3. Review `audit.json` và `approval.template.json` trước khi duyệt.
4. Train/chọn model bằng dev; final test chỉ chạy một lần trên run mới.
5. Review metrics, calibration, feature dictionary và model card.
6. Export handoff ZIP; backend không tự kích hoạt candidate vừa train.

Notebook
[`10_academic_demo_v2_model_evaluation.ipynb`](ml/notebooks/10_academic_demo_v2_model_evaluation.ipynb)
phục vụ phân tích hậu kiểm. Chi tiết đầy đủ ở
[`ml/COLAB_RUNBOOK.md`](ml/COLAB_RUNBOOK.md). Không diễn giải model này thành
dự đoán điểm số thang 10/4 hoặc áp dụng lên sinh viên thật chưa thẩm định.

## RAG và Gemini

Repository có corpus mẫu công khai
[`ml/rag/corpus/DEMO1.md`](ml/rag/corpus/DEMO1.md). PDF/DOCX UTT, database đang
chạy, vectorstore và model binary là dữ liệu runtime nên không đưa vào Git.

### Nạp tài liệu

1. Đăng nhập bằng tài khoản admin.
2. Đăng ký/upload tài liệu trong màn hình quản trị.
3. Chạy ingestion và activation theo UUID được trả về:

```powershell
docker compose exec api python -m app.knowledge ingest --version-id <UUID>
docker compose exec api python -m app.knowledge activate --version-id <UUID>
```

Tài liệu pending không được truy xuất; chỉ version `active` có chunks đã kiểm
tra mới đi vào corpus. Xem
[`docs/implementation/DOCUMENTS_AND_RAG_RUNBOOK.md`](docs/implementation/DOCUMENTS_AND_RAG_RUNBOOK.md).

### Chế độ retrieval

- `RAG_METHOD=keyword`: không cần tải embedding model, phù hợp chạy thử.
- `RAG_METHOD=dense`: cần cài `ml/requirements-rag.txt`, tải/pin đúng embedding
  revision và tạo Chroma index; vectorstore không commit vào Git.
- Notebook [`05_rag_evaluation.ipynb`](ml/notebooks/05_rag_evaluation.ipynb)
  dùng để đánh giá retrieval riêng, không dùng test set để tuning.

### Bật grounded generation

Mặc định `RAG_LLM_ENABLED=0`; retrieval/citation vẫn hoạt động. Có hai cách cấu
hình server-side trong `.env` hoặc secret store:

```dotenv
# Cách A: API gọi Gemini trực tiếp
RAG_LLM_ENABLED=1
RAG_LLM_PROVIDER=gemini
RAG_LLM_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=...

# Cách B: API gọi gateway ký HMAC; API không giữ Gemini key
RAG_LLM_GATEWAY_URL=https://your-gateway.example/api/v1
RAG_LLM_GATEWAY_SECRET=...
```

Không dùng cả hai secret phía client. Gateway mẫu nằm trong
[`gateway_function`](gateway_function/) và Bicep trong [`infra`](infra/). Chỉ
bật generation khi approval/receipt đang active khớp runtime. GPA, transcript,
JWT, cookie và dữ liệu cá nhân không được gửi tới Gemini.

## Phát triển và kiểm thử

Frontend:

```powershell
cd frontend
npm ci
npm run test:cards
npm run test:contracts
npm run build
```

Toàn hệ thống:

```powershell
docker compose build api web
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\Test-Foundation.ps1
```

Integration test có ghi fixture chỉ được chạy trên database test cô lập với
`ADVISOR_TEST_DATABASE=1`; không bật cờ này trên database dùng thật.

## Triển khai production

- Dùng image digest bất biến, secret manager, HTTPS, backup và restore rehearsal.
- Không commit `.env`, API key, database dump, tài liệu riêng, artifact/model
  binary hoặc vectorstore.
- Chạy migration trước khi chuyển traffic; giữ revision cũ để rollback.
- Thay hostname/origin trong `.env.production.example` và giữ API sau reverse
  proxy cùng origin với web.
- Workflow `.github/workflows/release-gate.yml` thực hiện secret scan,
  dependency audit và release verification.

Runbook: [Stage 9 Production Security](docs/implementation/STAGE9_PRODUCTION_SECURITY_RUNBOOK.md).

## Tài liệu dự án

- [Mục lục tài liệu](docs/README.md)
- [Cấu trúc repository](docs/PROJECT_STRUCTURE.md)
- [Báo cáo ML/RAG/Capstone](docs/reports/README.md)
- [Dữ liệu và model](docs/data-and-models.md)

## Phạm vi và giấy phép

- Catalog/mapping HTTT được công khai để minh họa pilot; không tuyên bố là quy
  chế chính thức hiện hành của UTT.
- `DEMO1.md`, sample CSV và hai dataset ZIP là dữ liệu demo/synthetic.
- Tài liệu UTT upload ở runtime phải tuân thủ quyền sử dụng của chủ hệ thống.

Copyright © 2026. All rights reserved. Repository này không cấp giấy phép mã
nguồn mở; không được sao chép, phân phối hoặc khai thác ngoài phạm vi được chủ
sở hữu cho phép.
