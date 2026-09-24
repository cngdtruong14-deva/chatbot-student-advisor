# Academic Demo v2 datasets

Các gói trong thư mục này là dữ liệu **synthetic/demo**, không phải dữ liệu sinh
viên UTT thật và không chứa thông tin đăng nhập production.

## Gói dữ liệu

### `academic-demo-v2-raw-v1.zip`

Gồm 12 file nguồn: cohorts, students, courses, curricula,
curriculum_courses, semesters, offerings, prerequisites, enrollments,
grade_components, grade_component_scores và `dataset_validation.json`.

- Quy mô: 1.000 sinh viên, 50 học phần, 292 lớp học phần, 24.370 lượt học và
  80.236 điểm thành phần.
- `users.csv` được loại có chủ ý: huấn luyện không cần bảng tài khoản.
- SHA-256: `41262948214ABEE4268DCEF3EF8188A7E5C3CA365C893FD7CCF6CB57A6319DA3`.

Sau khi giải nén, có thể chạy audit/chuẩn hóa vào một thư mục output mới:

```powershell
python -m ml.scripts.audit_academic_demo .\academic-demo-v2-raw-v1
python -m ml.scripts.prepare_academic_v2 .\academic-demo-v2-raw-v1 .\academic-demo-v2-normalized-new
```

### `academic-demo-v2-normalized-r2.zip`

Gồm `source_manifest.json`, `policy.json`, `audit.json`,
`normalized_enrollments.jsonl`, `gpa_reconciliation.jsonl` và
`output_manifest.json`. Đây là input đã chuẩn hóa cho Notebook 09.

- SHA-256: `A3B4BEA3BF442D620124551399252B45007BF0DFB11D61FA3F02A6F4E90495C9`.
- Notebook đối chiếu từng file với `output_manifest.json`; không bỏ qua lỗi hash.

Kiểm tra ZIP trên PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 .\datasets\academic-demo-v2-raw-v1.zip
Get-FileHash -Algorithm SHA256 .\datasets\academic-demo-v2-normalized-r2.zip
```

## Giới hạn

- Nhãn ML là nguy cơ `non_completion_at_end`, không phải dự đoán điểm số.
- Mốc day-28 là protocol demo; dữ liệu synthetic không chứng minh hiệu quả trên
  sinh viên thật.
- 145 lượt thiếu điểm được biểu diễn theo policy demo là vắng/cấm thi tạm thời;
  không có timestamp đủ tin cậy để suy diễn lịch sử thật.
- PE/QPAN không tính GPA theo policy demo; học lại lấy lần giải quyết mới nhất.
- Không dùng các file này để đưa ra quyết định học vụ thực tế.
