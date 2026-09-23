# Tích hợp artifact ML

Backend và pipeline huấn luyện trao đổi qua artifact bất biến, manifest có
version và schema trong `contracts/`. Model không được đóng gói trong source
public; quản trị viên nhận bundle qua kênh vận hành rồi xác minh hash, nội dung,
smoke cases và domain trước khi kích hoạt.

## Nguyên tắc

- Không áp model nghiên cứu OULAD lên hồ sơ sinh viên thuộc domain khác.
- Academic Demo v2 dùng feature contract, receipt và model version riêng.
- Feature snapshot và prediction là bằng chứng bất biến; không sửa lịch sử khi
  đổi model.
- Bundle chưa qua inspection/smoke parity phải trả trạng thái model unavailable.
- Không deserialize model từ nguồn không tin cậy và không cài dependency từ
  artifact một cách tự động.

## Quy trình vận hành

1. Huấn luyện và đánh giá bằng notebook/pipeline tương ứng trong `ml/`.
2. Khóa dataset/split/config/source commit và xuất manifest cùng smoke cases.
3. Đưa bundle vào `artifacts/incoming` ngoài Git.
4. Xác minh safe path, hash, schema, phiên bản môi trường và smoke parity.
5. Chuyển bundle đã duyệt sang artifact mount chỉ đọc.
6. Kích hoạt đúng domain/target/schema/cutoff; giữ nguyên model version cũ để
   truy vết prediction lịch sử.
7. Backend chỉ phục vụ inference khi receipt và runtime compatibility hợp lệ.

## Ranh giới dữ liệu

Dữ liệu học vụ pilot trong repository là synthetic. Dữ liệu thật, model binary,
database và artifact huấn luyện không được commit. Frontend phải hiển thị model
version/domain và không trình bày attribution như quan hệ nhân quả.

