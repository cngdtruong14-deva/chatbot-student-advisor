"""Bounded live-provider smoke for the governed false-abstention regression."""
from __future__ import annotations

import json
import time

from app.llm_runtime import OpenAICompatibleProvider


def main() -> int:
    question = "Sinh viên ngành Công nghệ thông tin có được miễn chuẩn đầu ra tin học không?"
    matches = [
        {"chunk": {
            "chunk_id": "smoke-required-standard",
            "title": "Chuẩn đầu ra Tin học",
            "section": "Điều 1",
            "text": (
                "Chuẩn đầu ra trình độ công nghệ thông tin là điều kiện bắt buộc "
                "mà người học cần đạt trước khi tốt nghiệp và áp dụng chung cho các "
                "chương trình đào tạo đại học."
            ),
        }},
        {"chunk": {
            "chunk_id": "smoke-recognition-conditions",
            "title": "Chuẩn đầu ra Tin học",
            "section": "Điều 4",
            "text": (
                "Người học có chứng chỉ MOS hoặc IC3, hoặc thuộc trường hợp được "
                "liệt kê, được làm thủ tục xét miễn thi công nhận chuẩn đầu ra CNTT."
            ),
        }},
    ]
    started = time.monotonic()
    result = OpenAICompatibleProvider().generate(question, matches)
    ids = {
        citation_id
        for claim in result.get("claims", [])
        for citation_id in claim.get("citation_ids", [])
    }
    passed = result.get("status") == "completed" and bool(ids) and ids <= {
        "smoke-required-standard", "smoke-recognition-conditions",
    }
    print(json.dumps({
        "case": "utt_it_output_standard_exemption",
        "status": result.get("status"),
        "failure_reason": result.get("failure_reason"),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "claim_count": len(result.get("claims", [])),
        "citation_count": len(ids),
        "passed": passed,
    }))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
