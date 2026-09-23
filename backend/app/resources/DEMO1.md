# DEMO-1 — Chính sách mô phỏng, không phải quy chế chính thức của trường

## DP01–DP02: Chương trình
DEMO-CS phiên bản 1, cohort DEMO-2026, ngành CNTT mô phỏng. Chương trình có 126 tín chỉ, gồm 42 học phần bắt buộc, mỗi học phần 3 tín chỉ, 7 học kỳ đề xuất. Mọi dữ liệu mang nhãn synthetic và domain demo_academic.

## DP03–DP05: Thang điểm
Điểm thành phần và tổng kết nằm trong khoảng 0 đến 10. Grade point bằng điểm tổng kết nhân 0,4. Đạt học phần khi điểm tổng kết từ 4,0 và đáp ứng minimum của từng thành phần. Điểm trượt vẫn quy đổi tuyến tính, không tự ép GPA về 0. Backend tính Decimal, API hiển thị 6 số thập phân, UI 2 số; kiểm tra khả thi trước khi làm tròn.

## DP06–DP08: GPA và học lại
GPA bằng tổng quality points chia tín chỉ tính GPA. Một học phần chỉ tính lần finalized có grade point cao nhất; bằng nhau lấy attempt_no cao hơn. Học lại không cộng đôi tín chỉ. Tín chỉ đạt được ghi nhận một lần nếu có ít nhất một lần học đạt; tín chỉ tính GPA và tín chỉ đạt khác nhau. Không có tín chỉ tính GPA thì GPA là null.

## DP09–DP10: Trạng thái đặc biệt
Pass/fail: P có tín chỉ đạt nhưng không tham gia GPA; F không có tín chỉ đạt hoặc GPA. Pending, incomplete, withdrawn không được tính như điểm finalized; không thay thế lần finalized trước. Exempt chỉ ghi nhận tín chỉ đạt khi có xác nhận công nhận tín chỉ rõ ràng, không tham gia GPA. Không đổi grading mode giữa các lần học cùng học phần.

## DP11–DP12: Điểm thành phần
Trọng số các thành phần phải dương và tổng chính xác bằng 1; mặc định là 0,1; 0,2; 0,3; 0,4. Điểm tối đa mỗi thành phần là 10. Chỉ tính điểm cần đạt khi đúng một thành phần chưa biết; nhiều thành phần chưa biết thì yêu cầu bổ sung. Điểm cần đạt phải xét minimum và giới hạn tối đa, không tự normalize trọng số.

## DP13–DP14: Mục tiêu và mô phỏng
GPA tương lai cần đạt chỉ áp dụng cho tín chỉ GPA mới, không dùng như cách thay điểm học lại. Yêu cầu trên 4 là bất khả thi; không còn tín chỉ thì trả trạng thái đã đạt/chưa đạt, không chia 0. Mô phỏng theo GPA học kỳ hoặc điểm học phần không thay đổi bảng điểm hay academic_revision. Tính toán phải gọi dịch vụ học vụ xác định, không nhờ LLM làm toán.

## DP15–DP16: Kế hoạch và tiến độ
Điều kiện tiên quyết dạng AND, môn tiên quyết phải đạt và grade point tối thiểu 1,6. Đồ thị không có chu trình; không tự suy diễn OR, đồng tiên quyết hoặc môn thay thế. Chỉ gợi ý offering đang mở, tối đa 18 tín chỉ mỗi kỳ. Chưa kiểm tra lịch học hoặc sĩ số. Tiến độ dựa vào tín chỉ bắt buộc đã đạt trên 126, không phải kết luận tốt nghiệp chính thức.

## DP17: Nhập dữ liệu
Import có policy/version và provenance, transaction all-or-nothing, dry-run không ghi học vụ. Import lại không tạo bản sao; thay đổi dữ liệu học vụ làm tăng academic_revision. Dữ liệu DEMO-1 không chứng minh quy chế hay hiệu quả dự đoán tại NTTU.
