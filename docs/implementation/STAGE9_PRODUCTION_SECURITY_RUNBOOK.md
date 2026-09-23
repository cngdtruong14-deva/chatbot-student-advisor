# Chặng 9 — CI, bảo mật và vận hành production pilot

## Phạm vi

Chặng này cung cấp cấu hình và automation để owner kiểm thử. Nó không mua VPS,
không đổi DNS, không cấp TLS thật và không triển khai public. Dữ liệu synthetic
vẫn giữ đúng nhãn; tài liệu UTT và RAG dùng release/approval hiện hành.

## 1. Release gate

Workflow `.github/workflows/release-gate.yml` chạy trên PR vào `main` hoặc bằng
`workflow_dispatch`: secret scan, dependency audit, syntax, contract drift,
Docker build, disposable integration/browser E2E, model/corpus/security tests và
release receipt. Gate chỉ có giá trị cho đúng commit SHA trong artifact workflow.

Không bỏ qua lỗi Critical/High. Dependency finding chỉ được miễn bằng quyết định
owner có mã CVE, phạm vi ảnh hưởng, biện pháp giảm thiểu và hạn hết hiệu lực.

## 2. Chuẩn bị host

1. Linux host chỉ mở SSH quản trị, TCP 80 và 443.
2. Tạo user vận hành không phải root và thư mục `/srv/student-advisor`.
3. Copy `.env.production.example` ra một file root-owned ngoài repository, chmod
   `600`, điền image digest và secret production mới. Không dùng lại secret local.
4. Kiểm tra `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` đúng domain HTTPS duy nhất.
5. Copy `ops/Caddyfile.example`, đổi domain và để Caddy host kết thúc TLS.
6. `web` chỉ bind `127.0.0.1:8080`; API, PostgreSQL và Chroma không public port.
   Chọn một `EDGE_SUBNET` không xung đột với host; API chỉ tin đúng địa chỉ
   `WEB_PROXY_IP` khi xử lý forwarded headers, không dùng wildcard proxy trust.

## 3. Trình tự triển khai

```sh
docker compose --env-file /secure/.env.production -f ops/production.compose.yaml config --quiet
docker compose --env-file /secure/.env.production -f ops/production.compose.yaml pull
docker compose --env-file /secure/.env.production -f ops/production.compose.yaml run --rm migrate
docker compose --env-file /secure/.env.production -f ops/production.compose.yaml up -d db api web
sh ops/production/healthcheck.sh /secure/.env.production
```

Ứng dụng production fail startup nếu JWT yếu, host/origin wildcard, origin không
phải HTTPS, test-database flag xuất hiện hoặc Gemini được bật thiếu key/provider.

## 4. Release manifest

Sau khi pull đúng image digest và đặt đủ artifact được duyệt:

```sh
python ops/build_release_manifest.py \
  --api-image registry/api@sha256:... \
  --web-image registry/web@sha256:... \
  --artifact artifacts/approved/final-002/manifest.json \
  --artifact artifacts/stage7/effectivity/release_receipt.current.json \
  --artifact artifacts/stage7/benchmark_v4/rag_runtime_approval_capstone_v4.signed.json \
  --output artifacts/release/release-manifest.json --require-clean
```

## 5. Backup, restore và retention

Trước migration, deploy hoặc purge:

```sh
sh ops/production/backup.sh /secure/.env.production /secure/backups release-YYYYMMDD-HHMM
```

Mã hóa và copy backup ra ngoài host. Restore phải diễn tập trên stack tách biệt;
không restore đè production để thử. Chỉ sau khi receipt restore PASS mới chạy:

```sh
sh ops/production/retention-purge.sh /secure/.env.production \
  /secure/backups/release-.../backup_manifest.json
# xem dry-run, sau đó chạy lại và thêm --confirm
```

Chat/RAG feedback hết hạn sau tối đa 30 ngày. Purge thật ghi một bản ghi tổng hợp
vào `app.audit_logs`; không gửi nội dung hội thoại sang Gemini hoặc hệ thống khác.

## 6. Monitoring tối thiểu

- Chạy `healthcheck.sh` mỗi phút từ host monitor.
- Cảnh báo khi API/web unhealthy, restart loop, disk >80%, backup/purge lỗi.
- Thu thập log JSON Docker/Caddy: 4xx/5xx, auth failures, Gemini timeout/429,
  ingest failure và request latency; không thu request body, token hay query text.
- Log rotation mặc định 10 MB × 5 file/container.

## 7. Owner gate trước public pilot

- GitHub Release Security Gate PASS đúng SHA.
- Không secret trong source, history, workflow artifact hoặc log.
- TLS hợp lệ; HTTP chuyển HTTPS; DB/Chroma không public.
- Backup + restore rehearsal PASS và đo RPO/RTO.
- Đăng nhập, refresh/logout, GPA/what-if, upload PDF/DOCX, RAG citation và
  account isolation PASS trên staging.
- Retention dry-run/purge trên fixture staging PASS.
- Release manifest khớp source, image, model, corpus và approvals.
- Owner ký release approval; nếu thiếu một mục thì chưa được gọi production.
