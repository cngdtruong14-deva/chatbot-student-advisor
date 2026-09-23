# Career Skill Gap — HTTT demo

Phiên bản dữ liệu: `HTTT-CAREER-SKILLS-1.0.0`.

## Phạm vi

- 27 kỹ năng, 6 định hướng nghề nghiệp, 8 chứng chỉ tham khảo.
- 91 ánh xạ kỹ năng trên 47 học phần HTTT.
- 25 học phần được loại có chủ ý và lưu reason code.
- Match score là mức phủ trọng số của kỹ năng có bằng chứng, không phải xác suất tuyển dụng.

## Nạp điểm demo có kiểm soát

Lệnh mặc định chỉ dry-run:

```powershell
docker compose exec api python -m app.seed_httt_career_demo
```

Chỉ sau khi kiểm tra dry-run và xác nhận tài khoản `student@demo.local`
đã gắn curriculum `HTTT-UTT`:

```powershell
docker compose exec api python -m app.seed_httt_career_demo --confirm SEED_HTTT_CAREER_DEMO
```

Script không ghi đè kết quả đã có. Dòng trùng bị bỏ qua và `academic_revision`
chỉ tăng khi có enrollment mới được thêm.

## Câu hỏi demo

- `Data Analyst cần kỹ năng gì?`
- `Tôi còn thiếu gì để làm Data Analyst?`
- `Tôi phù hợp nghề nào trong ngành HTTT?`
- `Business Analyst cần những môn nào?`

Chat không nhận `student_id` từ nội dung. Hồ sơ sinh viên luôn được giải quyết
từ tài khoản đang đăng nhập.
