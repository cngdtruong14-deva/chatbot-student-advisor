# Dữ liệu và model

Dữ liệu học vụ/ML trong repository là synthetic và không đại diện cho sinh viên
thật. Hai ZIP công khai, checksum và giới hạn sử dụng được mô tả tại
[`datasets/README.md`](../datasets/README.md).

Catalog `HTTT-UTT/2024`, sample CSV, mapping Career Skill Gap và corpus
`ml/rag/corpus/DEMO1.md` được owner cho phép công khai để minh họa pilot. Chúng
không được mô tả là quy chế/chương trình chính thức hiện hành của UTT.

PDF/DOCX UTT, database, vectorstore, model binary và dữ liệu người dùng là dữ
liệu runtime, không nằm trong source public. Quản trị viên có thể nạp tài liệu
qua workflow của hệ thống mà không thiếu code.

Model/corpus đưa vào runtime phải có nguồn gốc, checksum, schema, version, giới
hạn sử dụng và approval. Không bật provider bằng credential trong source.
