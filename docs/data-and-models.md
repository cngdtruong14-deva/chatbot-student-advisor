# Dữ liệu và model

Dữ liệu demo trong ứng dụng được đánh dấu synthetic và không đại diện cho sinh viên thật. Dữ liệu thật không được xuất.

`backend/app/seed_httt_curriculum.py` chứa catalog HTTT có nguồn ghi là một DOCX do owner cung cấp. Quyền phân phối công khai của nội dung này chưa được xác nhận; owner phải duyệt riêng trước khi public.

Model và corpus được cung cấp bên ngoài repository phải có nguồn gốc, checksum, schema, version, giới hạn sử dụng và quyền phân phối. Không bật provider LLM bằng credential trong source.
