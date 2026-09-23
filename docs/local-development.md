# Phát triển local

Yêu cầu Docker Desktop, PowerShell và Node.js/npm.

1. Sao chép `.env.example` thành `.env` và thay placeholder bằng secret local.
2. Chạy `ops/Initialize-Local.ps1`.
3. Chạy `ops/Start-Local.ps1`.
4. Kiểm tra web tại `http://localhost:3000`, API docs tại `http://localhost:8000/docs`.
5. Chạy `ops/Test-Foundation.ps1` trên stack local phù hợp.

Không dùng dữ liệu thật, volume live hoặc secret production khi phát triển. Test ghi database phải dùng stack disposable và được kiểm tra biến môi trường an toàn trước khi chạy.
