"""Offline, immutable Phase B review packets. Never writes to the application DB."""
import argparse
import hashlib
import html
import json
import unicodedata
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def metrics(reference, hypothesis):
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        raise ValueError("NONEMPTY_GOLD_REQUIRED")
    return {"cer": distance(ref, hyp) / len(ref),
            "wer": distance(ref.split(), hyp.split()) / len(ref.split())}


def build(repo, out):
    from pdf2image import convert_from_path
    repo, out = Path(repo).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError("IMMUTABLE_OUTPUT_EXISTS")
    sources_path = repo / "artifacts/phase_b/source_manifest.jsonl"
    pages_path = repo / "artifacts/phase_b/page_manifest.jsonl"
    sources = {s["source_id"]: s for s in read_rows(sources_path)}
    pages = read_rows(pages_path)
    for source in sources.values():
        raw = (repo / source["internal_path"]).resolve()
        if not raw.is_relative_to(repo) or sha(raw) != source["raw_sha256"]:
            raise ValueError("RAW_SOURCE_HASH_OR_PATH_MISMATCH")
    for page in pages:
        if hashlib.sha256(page["raw_text"].encode()).hexdigest() != page["text_sha256"]:
            raise ValueError("PAGE_TEXT_HASH_MISMATCH")
    # First packet: ten different scanned sources, policy-oriented ordering.
    priorities = ("đào tạo", "học vụ", "thi kết thúc", "đánh giá", "học bổng", "quy chế", "quy định")
    def rank(p):
        title = p["document_title"].lower()
        return (next((i for i, word in enumerate(priorities) if word in title), len(priorities)),
                p["source_id"], p["page_index"])
    selected, seen = [], set()
    for page in sorted(pages, key=rank):
        if page["extraction_method"] != "ocr_tesseract_vie_eng" or page["source_id"] in seen:
            continue
        selected.append(page)
        seen.add(page["source_id"])
        if len(selected) == 10:
            break
    out.mkdir(parents=True)
    records, cards = [], []
    for n, page in enumerate(selected, 1):
        source = sources[page["source_id"]]
        raw = repo / source["internal_path"]
        images = convert_from_path(str(raw), dpi=130, first_page=page["page_index"],
                                   last_page=page["page_index"], timeout=60)
        images[0].save(out / f"page-{n:02d}.png")
        record = {"id": f"B01-{n:02d}", "source_id": page["source_id"],
                  "raw_sha256": source["raw_sha256"], "page_index": page["page_index"],
                  "text_sha256": page["text_sha256"], "ocr_text": page["raw_text"],
                  "decision": "pending", "critical_verified": False, "gold_text": "", "notes": ""}
        records.append(record)
        cards.append(f'<section data-i="{n-1}"><h2>{record["id"]} — {html.escape(page["document_title"])}, trang {page["page_index"]}</h2>'
                     f'<div class="grid"><a href="page-{n:02d}.png" target="_blank"><img src="page-{n:02d}.png"></a>'
                     f'<div><h3>OCR đầy đủ — chưa được duyệt</h3><pre>{html.escape(page["raw_text"])}</pre></div></div>'
                     '<p>Đối chiếu toàn trang, đặc biệt số quyết định, ngày, điểm và ngoại lệ. Bấm ảnh để phóng lớn.</p>'
                     '<select class="decision"><option value="pending">Chưa duyệt</option><option value="accepted">Khớp toàn trang</option>'
                     '<option value="corrected">Đã sửa bản đối chiếu</option><option value="unreadable">Không đọc rõ</option></select>'
                     '<label><input class="critical" type="checkbox"> Đã kiểm tra tất cả số liệu/điều kiện trọng yếu trên trang</label>'
                     '<p>Bản chép chuẩn: nếu chọn “Đã sửa”, nhập toàn văn đúng của trang, không chỉ ghi riêng chỗ sai.</p>'
                     '<textarea class="gold" rows="10" placeholder="Bản chép chuẩn đầy đủ khi cần sửa"></textarea>'
                     '<textarea class="notes" rows="2" placeholder="Ghi chú, vị trí chưa đọc rõ"></textarea></section>')
    packet = {"packet_version": 2, "source_manifest_sha256": sha(sources_path),
              "page_manifest_sha256": sha(pages_path), "reviewer": "", "records": records}
    (out / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.dumps(packet, ensure_ascii=False).replace("<", "\\u003c")
    script = r'''const packet=PACKET;
const fields=()=>Array.from(document.querySelectorAll('section'));
function collect(){packet.reviewer=document.querySelector('#reviewer').value.trim();packet.reviewed_at=new Date().toISOString();fields().forEach((s,i)=>{const r=packet.records[i];r.decision=s.querySelector('.decision').value;r.critical_verified=s.querySelector('.critical').checked;r.gold_text=s.querySelector('.gold').value;r.notes=s.querySelector('.notes').value;});return packet;}
document.querySelector('#export').onclick=()=>{const p=collect();if(!p.reviewer){alert('Hãy điền tên người duyệt');return;}for(const r of p.records){if(r.decision==='accepted'&&!r.critical_verified){alert(r.id+': cần xác nhận nội dung trọng yếu');return;}if(r.decision==='corrected'&&(!r.gold_text.trim()||!r.critical_verified)){alert(r.id+': cần toàn văn chuẩn và xác nhận nội dung trọng yếu');return;}}const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));a.href=url;a.download='phase-b-review-batch-01.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
document.querySelector('#restore').onchange=async e=>{try{const p=JSON.parse(await e.target.files[0].text());if(p.page_manifest_sha256!==packet.page_manifest_sha256||p.records.length!==packet.records.length||p.records.some((r,i)=>r.id!==packet.records[i].id||r.text_sha256!==packet.records[i].text_sha256))throw Error('File không thuộc nhóm này');document.querySelector('#reviewer').value=p.reviewer||'';fields().forEach((s,i)=>{const r=p.records[i];s.querySelector('.decision').value=r.decision;s.querySelector('.critical').checked=r.critical_verified===true;s.querySelector('.gold').value=r.gold_text||'';s.querySelector('.notes').value=r.notes||'';});}catch(err){alert(err.message);}};
'''.replace("PACKET", data)
    (out / "index.html").write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Phase B — duyệt nhóm 01</title>'
        '<style>body{font:16px system-ui;margin:24px;background:#f3f6fa;color:#17243b}section{background:white;padding:20px;margin:24px 0;border-radius:10px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}img{width:100%}pre{white-space:pre-wrap;line-height:1.6}textarea{display:block;width:98%;margin:12px 0}select,input,button{padding:8px}label{margin:12px}header{position:sticky;top:0;background:#e9eff9;padding:16px}h2{font-size:20px}</style>'
        '<header><h1>Phase B — nhóm duyệt 01 (10 trang)</h1><p>Chưa có trang nào được duyệt tự động. Không thay đổi corpus live. Xuất file để lưu tiến độ trước khi đóng trang.</p>'
        '<input id="reviewer" placeholder="Tên người duyệt"><button id="export">Tải kết quả duyệt JSON</button> Nạp lại bản đã lưu: <input type="file" id="restore" accept=".json"></header>'
        + ''.join(cards) + '<script>' + script + '</script></html>', encoding="utf-8")
    print(json.dumps({"packet": str(out / "index.html"), "pages": len(records), "status": "AWAITING_HUMAN_REVIEW"}))


def evaluate(packet_path, response_path):
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    response = json.loads(Path(response_path).read_text(encoding="utf-8"))
    if not response.get("reviewer", "").strip() or not response.get("reviewed_at"):
        raise ValueError("REVIEWER_AND_TIMESTAMP_REQUIRED")
    for field in ("packet_version", "source_manifest_sha256", "page_manifest_sha256"):
        if packet[field] != response.get(field):
            raise ValueError("STALE_PACKET")
    if len(packet["records"]) != len(response["records"]):
        raise ValueError("RECORD_COUNT_MISMATCH")
    results = []
    for original, reviewed in zip(packet["records"], response["records"]):
        for key in ("id", "source_id", "page_index", "raw_sha256", "text_sha256", "ocr_text"):
            if reviewed.get(key) != original[key]:
                raise ValueError("SOURCE_BINDING_MISMATCH")
        decision = reviewed.get("decision")
        if decision not in ("pending", "unreadable", "accepted", "corrected"):
            raise ValueError("INVALID_DECISION")
        item = {"id": original["id"], "decision": decision, "metrics": None}
        if decision in ("accepted", "corrected"):
            if reviewed.get("critical_verified") is not True:
                raise ValueError("CRITICAL_REVIEW_REQUIRED")
            gold = original["ocr_text"] if decision == "accepted" else reviewed.get("gold_text", "")
            item["metrics"] = metrics(gold, original["ocr_text"])
            item["original_ocr_meets_cer"] = item["metrics"]["cer"] <= .02
        results.append(item)
    return {"status": "BATCH_ONLY_NOT_PHASE_ACCEPTANCE", "normalization": "Unicode NFC; collapse whitespace; preserve case/punctuation", "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("evaluate")
    p.add_argument("--packet", required=True)
    p.add_argument("--response", required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.repo, args.out)
    else:
        print(json.dumps(evaluate(args.packet, args.response), ensure_ascii=False, indent=2))
