## Kết quả và phạm vi

- Việc hoàn thành / endpoint hoặc artifact bị ảnh hưởng:
- Nhánh công việc: hạ tầng / Claude-app / Colab-ML:
- Những gì CHƯA triển khai:

## Kiểm tra trước khi merge

- [ ] Có kết quả test thực, không dùng dữ liệu giả làm kết quả đánh giá.
- [ ] Không có .env, API key, dữ liệu sinh viên hoặc model binary trong Git.
- [ ] Thay đổi contract/shared package/migration đã được người tích hợp duyệt.
- [ ] Nếu có model: manifest, feature schema, metrics, split IDs, model card và smoke test đầy đủ.
- [ ] Ghi rõ cách rollback; không xóa volume hoặc dữ liệu để sửa lỗi.
