# Triển khai

Bản xuất này chưa phải gói triển khai production. Không có image release, model binary, corpus persistent, registry digest hoặc website public đi kèm.

Trước khi triển khai cần owner duyệt: môi trường và network, secrets manager, image provenance, database backup/restore, model/corpus provenance, quyền dữ liệu, logging/retention, health checks, rollback và CI trên chính bản xuất.

Các script backup/restore nội bộ không được đưa vào bản public và không được xem là quy trình production đã được chứng nhận.
