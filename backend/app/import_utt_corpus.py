"""Receive owner-authorized Drive readable text into the isolated test corpus.

Dates below are test-index availability, not certified institutional validity.
Incomplete/image-only extractions remain in the receipt inventory, not active.
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import date
from app.knowledge import DocumentInput, register_document, ingest, activate
from app.store import transaction, one

def import_corpus(path, output, dry_run=False):
    payload=json.loads(Path(path).read_text(encoding='utf-8'))
    assert payload['scope']=='utt_test'
    with transaction() as db:
        owner=one(db,"SELECT id FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
    if not owner: raise ValueError('ADMIN_REQUIRED')
    results=[]
    for source in payload['documents']:
        try:
            text=source['content'].replace('\x00','').strip()
            if len(text)<100: raise ValueError('EXTRACTION_INSUFFICIENT')
            digest=hashlib.sha256(text.encode()).hexdigest()
            header=f"# {source['title']}\n\nNguồn UTT do chủ dự án cung cấp để thử nghiệm. Văn bản trích xuất tự động, chưa xác nhận đầy đủ, hiệu lực hoặc phạm vi áp dụng. Không thay chính sách GPA demo. Ngày 2026-09-17 là ngày khả dụng của kho thử nghiệm.\n\n"
            body=DocumentInput(title=source['title'],source=source['source'],
                version='drive-text-20260917-'+digest[:12],content=header+text,
                corpus_scope='utt_test',valid_from=date(2026,9,17))
            result={'source_id':source['id'],'title':source['title'],'source_sha256':digest,'chars':len(text)}
            if dry_run: result['status']='validated'
            else:
                item=register_document(body,owner['id'])
                result.update(ingest(item['id']))
                result.update(activate(item['id']))
            results.append(result)
        except Exception as exc:
            results.append({'source_id':source['id'],'title':source['title'],'status':'failed','error_type':type(exc).__name__})
        print(json.dumps(results[-1],ensure_ascii=False,default=str),flush=True)
    receipt={'scope':'utt_test','extraction':payload['extraction'],'institutional_validity_verified':False,
             'dry_run':dry_run,'results':results,'inventory':payload['inventory']}
    Path(output).write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--dry-run',action='store_true');args=p.parse_args()
    import_corpus(args.input,args.output,args.dry_run)
