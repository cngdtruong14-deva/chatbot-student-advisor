# Audit HTTT Career–Skill Mapping 1.0.0

Version: `HTTT-CAREER-SKILLS-1.0.0`
Status: `owner_approved_demo`
Source mapping: `backend/app/resources/career/course_skills_HTTT.csv`
Canonical LF SHA-256: `8B01A3FB7921AEE10EBB983C338656C845254F2969B9E21ECCF089E124D3BB3C`

## Kết quả

- 72 học phần trong catalog `HTTT-UTT/2024`.
- 47 học phần có 91 ánh xạ tới đủ 27 kỹ năng.
- 25 học phần không ánh xạ theo quyết định của owner.
- Không có cặp `(course_code, skill_id)` trùng.
- `course_skills.weight` là mức đóng góp độc lập, không phải tỷ lệ buộc tổng mỗi môn bằng 1.

## Loại khỏi tín hiệu nghề nghiệp trực tiếp

Nhóm nền tảng chung, lý luận, thể chất và quốc phòng:

`DC1LL06`, `DC1LL07`, `DC1LL08`, `DC1LL03`, `DC1LL09`, `DC1LL05`,
`DC1CB11`, `DC1CB41`, `DC1TT21`, `DC1TT22`, `DC1TD21`, `DC1TD31`,
`DC1TD32`, `DC1TD33`, `DC1QP05`, `DC1QP06`, `DC1QP07`, `DC1QP08`.

Reason code: `non_career_foundation`.

## Ngoài phạm vi sáu nghề demo đã chọn

`DC2TT11`, `DC3TT34`, `DC2TH33`, `DC2HT41`, `DC2TH34`, `DC3HT44`, `DC3HT45`.

Reason code: `outside_selected_career_scope`.

Việc không ánh xạ không có nghĩa các môn này không có giá trị. Chúng chỉ không được dùng làm bằng chứng cho sáu hướng nghề nghiệp trong phiên bản demo này.

## Giới hạn

- Trọng số nghề nghiệp là bản demo được owner duyệt, chưa phải chuẩn năng lực chính thức của UTT.
- Match score là mức phủ kỹ năng có bằng chứng từ môn đã đạt, không phải xác suất được tuyển dụng.
- Phiên bản 1.0.0 chưa có `required_level` đã được nguồn tuyển dụng xác minh. Do đó phép tính dùng binary evidence coverage.
- Chỉ lần học mới nhất đã đạt được dùng làm bằng chứng.
