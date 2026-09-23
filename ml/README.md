# ML/RAG trên Google Colab

Đọc [COLAB_RUNBOOK.md](COLAB_RUNBOOK.md) trước. Đã có 7 notebook sạch trong `notebooks/`,
code thí nghiệm trong `scripts/`, corpus DEMO và question drafts trong `rag/`.
**Chưa chạy các notebook trên Colab hoặc train OULAD thật.**

Lộ trình: 00 môi trường → 01 audit → người dùng duyệt → 02 features/split → 03 Dummy/LR/RF
→ 04 candidate/explanation → 05 RAG evaluation → 06 frozen final test/export.
Notebook05 retrieval smoke có thể chạy độc lập với OULAD; benchmark cần human-reviewed gold.

OULAD public_dataset tách hồ sơ DEMO/NTTU. Shared package `sic-advisor-core==0.3.0`, contract1.0.0.
Không dùng DB credentials/`.env` runtime. Không upload secrets, dữ liệu sinh viên thật hay model không rõ nguồn.

Đầu ra model gồm pipeline, manifest, schema, metrics, environment lock, model card,
split manifest, smoke IO và explanation config. Backend cần verify trust/environment/parity và activate riêng.
RAG bàn giao chunks/config để re-index Chroma; không chuyển live persistent store giữa Colab và backend.

`GenerationUnavailable` là điểm mở rộng provider; chưa có LLM API thực thi. Key + model/base URL và adapter test
cần được cấu hình sau khi chọn provider. Không bịa answer hoặc metric để báo tính năng sẵn sàng.
