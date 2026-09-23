# Chính sách học vụ Academic Demo v2

Tài liệu mô phỏng cho sản phẩm Capstone. Phiên bản ACADEMIC-DEMO-2.0.0. Không phải quy chế chính thức của UTT. Nguồn: quyết định của chủ dự án và advisor_core.academic_policy_v2.

## Học lại và thi lại

Khi có kết quả đã xác định của lần học hoặc thi lại mới nhất, điểm mới thay điểm cũ của cùng học phần, kể cả điểm mới thấp hơn. Không đồng thời tính cả hai lần vào GPA. GPA được tính lại bằng dịch vụ học vụ của hệ thống.

## Vắng thi và cấm thi

Trạng thái absent_or_barred thể hiện vắng thi hoặc cấm thi, chưa hoàn thành học phần. Điểm hiệu lực tạm thời là 0; học phần có tính GPA vẫn đưa số tín chỉ vào mẫu số GPA. Khi có kết quả lần mới, quy tắc thay thế bằng lần mới nhất được áp dụng. Không suy ra ngày công bố kết quả khi timestamp bị thiếu.

## Học phần không tính GPA

PE101, PE201, PE301 và GEN402 không tính vào GPA cả thang 4 và thang 10. Các học phần này vẫn phải đạt; nếu không đạt cần học lại đến khi đạt. Điểm đạt là từ 4 trên thang 10. Tín chỉ đạt và tín chỉ dùng tính GPA là hai đại lượng khác nhau.

## GPA thang 4 và thang 10

Hệ thống tính riêng GPA thang 4 và thang 10 theo số tín chỉ của các học phần tính GPA, sau khi chọn lần học mới nhất. Không chuyển GPA tổng thang 4 sang thang 10 bằng phép nhân. Điểm từng học phần được quy đổi theo bảng của chính sách demo; kết quả GPA phải lấy từ dịch vụ tính toán, không để mô hình ngôn ngữ tự tính.

## Mục tiêu GPA và tình huống giả định

Chức năng mục tiêu GPA hiện dự phóng trên thang 4 với các tín chỉ mới có tính GPA. Thử thay điểm từng môn có thể tính lại cả hai thang khi có điểm môn thang 10 cụ thể. Tình huống giả định không sửa bảng điểm gốc.

## Dự đoán nguy cơ học tập

Artifact Academic Demo v2 dự đoán nguy cơ không hoàn thành học phần với đặc trưng ngày 28 mô phỏng. Đây không phải dự đoán điểm số thang 4 hoặc thang 10. Kết quả thuộc research case tổng hợp, chưa dùng trực tiếp cho hồ sơ sinh viên thực tế. Các tín hiệu mô phỏng và lịch sử chưa kiểm chứng thời gian không phải bằng chứng hành vi LMS thật.
