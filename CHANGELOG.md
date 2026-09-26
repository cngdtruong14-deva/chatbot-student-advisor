# Changelog

## 2026-09-26 — Tối ưu định tuyến và trình bày mô phỏng GPA

- Phân loại câu hỏi lập kế hoạch GPA theo điểm tín hiệu và cấu trúc câu, thay cho cơ chế từ khóa đầu tiên thắng.
- Phân biệt câu hỏi cần tìm GPA phải đạt với câu hỏi dự phóng; yêu cầu làm rõ khi hai ý định thực sự cân bằng.
- Card mô phỏng tách rõ GPA hiện tại, mức GPA giả định của tín chỉ mới và GPA dự kiến.
- Chỉ hiển thị GPA thang 10 hiện tại khi không thể suy ra giá trị dự kiến; giải thích rõ quy đổi theo bậc không tuyến tính.
- Bổ sung kiểm thử hồi quy cho câu đã gây lỗi và các cách diễn đạt đối kháng.

## 2026-09-26 — Sửa mô phỏng điểm tự khai

- Chatbot nhận đúng câu mô phỏng đầy đủ có dấu chấm cuối câu, ví dụ `mô phỏng tự khai CS1 lần 2 được 8.`.
- Phản hồi mô phỏng hiển thị rõ môn/lần học, điểm trước–sau và GPA trước–sau.
- Bổ sung kiểm thử hồi quy cho nhiều dấu câu, điểm thập phân và xác nhận không ghi thay đổi vào bảng điểm đã lưu.

## 2026-09-23 — Public release candidate

- Hoàn thiện backend, frontend, database migrations và Docker Compose.
- Bổ sung chatbot học vụ, RAG có dẫn nguồn và grounded generation tùy cấu hình.
- Bổ sung hồ sơ học tập, GPA, mô phỏng, nhập dữ liệu và quản lý tài liệu.
- Bổ sung catalog HTTT pilot và Career Skill Gap có giải thích.
- Chuẩn hóa nhận diện sản phẩm dùng chung; UTT là phạm vi pilot, không phải chủ sở hữu sản phẩm.
- Không đóng gói secret, database, tài liệu UTT runtime, vectorstore hoặc model binary.
