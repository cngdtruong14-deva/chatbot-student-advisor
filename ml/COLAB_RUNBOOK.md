# Google Colab Runbook — Academic Demo v2

## Mục đích và phạm vi

Đây là runbook chính để train/test/export một artifact nghiên cứu cho **Academic Demo v2**.
Dataset là dữ liệu **mô phỏng (synthetic/demo)**; không được mô tả là dữ liệu sinh viên thật, không được dùng để dự đoán trực tiếp hồ sơ sinh viên thật và không phải mô hình dự đoán điểm số thang 10/4.

- Target: `non_completion_at_end`.
- Cutoff: ngày 28.
- Domain: `academic_demo_v2`.
- Data origin: `synthetic`.
- Primary selection metric: Average Precision trên dev.
- Candidate models: DummyClassifier, LogisticRegression, RandomForest.
- Backend không phụ thuộc vào Colab và notebook **không tự kích hoạt** model trong backend.

Luồng này dùng notebook [09_academic_demo_v2_train_and_export.ipynb](notebooks/09_academic_demo_v2_train_and_export.ipynb). OULAD và RAG là các nhánh nghiên cứu độc lập, được giữ ở cuối tài liệu; không trộn dataset hoặc artifact giữa các domain.

## Đầu vào đã chốt

| Thành phần | Giá trị cần dùng |
|---|---|
| Source archive | ZIP nguồn sạch tạo từ đúng commit Git đã duyệt |
| Source archive SHA-256 | `EB451A262D02E949B4849458917CCF708A11A3561AEE836495FA780B159354A0` |
| Source commit trong manifest | `a64c0f573b4c57824b942ffe2510428437555045` |
| Dataset release | ZIP chứa release `academic_demo_v2_audit_20260909_r2` |
| Dataset bắt buộc | `normalized_enrollments.jsonl` và `output_manifest.json` |
| Runtime | Google Colab Python **3.13** mới (CPU đủ cho baseline) |
| Notebook | `09_academic_demo_v2_train_and_export.ipynb` |

ZIP dataset có thể chứa thư mục release ở lớp gốc hoặc bên trong một thư mục cha. Notebook tự tìm chính xác **một** `normalized_enrollments.jsonl` và **một** `output_manifest.json`, rồi đối chiếu hash trước khi làm tiếp.

Không upload `.env`, khóa API, thông tin đăng nhập, hay dữ liệu sinh viên thật lên Colab.

## Trạng thái Phase 00

**Phase 00 — hoàn tất khi output có các dấu hiệu sau:**

- `Clean source verified: a64c0f...`
- Python `3.13.x`.
- Không báo lỗi `SOURCE_MANIFEST.json`, source hash hoặc dependency.
- `Schema syntax PASS`.
- Có thư mục làm việc `/content/academic-demo-v2-work`.

`Schema syntax PASS` chỉ xác nhận JSON schema đọc được. Nó **không** có nghĩa model đã train, artifact đã hợp lệ, hoặc backend đã được kích hoạt.

Nếu đang dùng runtime cũ, dừng và tạo runtime Colab mới. Không giải nén source ZIP lần hai trong cùng runtime: notebook chủ động chặn `/content/student-advisor` đã tồn tại để tránh lẫn source.

## Quy trình còn lại sau Phase 00

### Phase 01 — upload và xác minh release data

1. Chạy ô upload dataset release.
2. Chọn **một** ZIP của `academic_demo_v2_audit_20260909_r2`.
3. Chỉ tiếp tục khi output có `Synthetic release verified:` cùng tên file, SHA-256 và kích thước.

Lỗi `Normalized release hash mismatch` nghĩa là file `normalized_enrollments.jsonl` không còn khớp `output_manifest.json`. Không sửa/bỏ qua hash; hãy tạo lại ZIP từ cùng một release nguyên vẹn.

### Phase 02 — preflight audit và duyệt dữ liệu

1. Chạy ô tạo `RUN_ID` và preflight.
2. Mở hai file Colab in ra:
   - `.../preflight/<RUN_ID>/processed/audit.json`
   - `.../preflight/<RUN_ID>/approval.template.json`
3. Kiểm tra tối thiểu:
   - domain là `academic_demo_v2`;
   - `data_origin` là `synthetic`;
   - target là `non_completion_at_end`;
   - cutoff là 28;
   - số dòng/split và audit không có lỗi bất thường.

Preflight chưa train model và chưa đọc test metrics.

### Phase 03 — train, chọn model và final test một lần

Trong ô **Owner gate**, chỉ sau khi đã review Phase 02, đổi đúng hai dòng:

```python
OWNER_APPROVES_DATASET = True
OWNER_APPROVES_FINAL_TEST = True
```

Giữ `OWNER` là định danh người duyệt. Không tự sửa `RUN_ID`, `MODEL_VERSION` hoặc `BUNDLE_DIRECTORY` nếu không có protocol mới. Chạy ô này **một lần** trong runtime/run hiện tại.

Lệnh governed runner sẽ:

1. Tạo event features và split group-disjoint theo sinh viên.
2. Chọn Dummy/LR/RF bằng dev Average Precision.
3. Đóng băng selection và threshold từ dev.
4. Chạy final test một lần, ghi `FINAL_TEST_STARTED.json`.
5. Xuất audit, approvals, manifests, metrics, report tables và bundle.

Không xóa marker final, không dùng test để điều chỉnh model/threshold, và không chạy lại cùng `RUN_ROOT`. Nếu một run thất bại, giữ nguyên output/lỗi, tạo runtime mới và ghi rõ lý do/protocol của run tiếp theo.

### Phase 04 — review kết quả

Chạy ô review chỉ sau khi Phase 03 hoàn tất. Kiểm tra:

- `run_report.json` và tên model được chọn;
- `run/final_metrics.json`;
- `report_tables/model_comparison_dev.csv`;
- `report_tables/final_metrics.csv`;
- `report_tables/calibration.csv`;
- `report_tables/split_summary.csv`;
- `report_tables/feature_dictionary.csv`;
- `bundle/manifest.json`, `bundle/model_card.md`, smoke inputs/expected và requirements lock.

Kết quả phải được báo cáo đúng là model risk mô phỏng day-28. Không diễn giải Average Precision/ROC-AUC thành "dự đoán chính xác điểm số".

### Phase 05 — export handoff

Chỉ sau Phase 04, đổi:

```python
EXPORT_HANDOFF = True
```

Notebook tạo và tải về `<RUN_ID>-handoff.zip`. Lưu ZIP này ngoài `/content` vì runtime Colab là ephemeral. Handoff cần giữ nguyên các thư mục audit, processed, run, report_tables, bundle và receipt để kiểm tra cục bộ.

## Sau khi tải handoff về máy

1. Không ghi đè artifact/receipt đang active trong backend.
2. Gửi hoặc đặt ZIP handoff tại vị trí được kiểm soát để kiểm tra hash, manifest, safe paths, environment compatibility và smoke parity.
3. Chỉ kích hoạt artifact sau khi backend kiểm tra bundle thành công và owner duyệt receipt riêng.
4. Nếu artifact mới không vượt Dummy trên dev, giữ kết quả trung thực và không activate như model dự đoán.

Artifact hiện hành và artifact Colab mới là hai version độc lập. Kết quả Colab tạo một candidate mới, không thay lịch sử prediction/explanation cũ.

## Troubleshooting ngắn

| Lỗi | Cách xử lý an toàn |
|---|---|
| `/content/student-advisor already exists` | Tạo runtime mới, chạy lại từ Phase 00; không giải nén chồng source. |
| Python không phải 3.13 | Tạo runtime Colab Python 3.13 mới. |
| `Upload exactly one ... archive` | Chỉ upload đúng một ZIP ở ô hiện tại. |
| `Normalized release hash mismatch` | Dùng lại ZIP release nguyên vẹn, không sửa manifest/hash. |
| `FINAL_TEST_STARTED.json` đã có | Không xóa marker; tạo run/runtime mới và ghi protocol mới. |
| Mất runtime trước export | Run trong `/content` mất. Phải bắt đầu lại; dùng Drive chỉ khi tự bật và vẫn giữ nguyên các gate. |

## Nhánh OULAD và RAG — giữ riêng

- OULAD là public research dataset (`data_origin=public_dataset`), không được suy luận lên Academic Demo v2 hay hồ sơ sinh viên.
- RAG dùng corpus được duyệt, có source/version/scope và citation; không suy ra quy chế từ tài liệu thiếu evidence.
- Benchmark RAG/final marker, OULAD approval và artifact của các nhánh đó không dùng thay cho approval/final marker Academic Demo v2.

Các notebook legacy `00`–`08` vẫn có thể được dùng cho mục đích nghiên cứu tương ứng, nhưng không phải quy trình để tạo artifact Academic Demo v2 mới.
