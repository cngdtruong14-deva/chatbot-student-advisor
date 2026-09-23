"""Small developer smoke benchmark, not a held-out RAG quality certification."""
import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from advisor_core.rag import lexical_search
from app.knowledge import accessible_chunks
from app.dense_runtime import search as dense_search

CASES=[
 ('demo_academic','Học lại lấy điểm mới hay điểm cao nhất?','điểm mới thay điểm cũ'),
 ('demo_academic','Vắng thi hoặc cấm thi tính GPA như thế nào?','Điểm hiệu lực tạm thời là 0'),
 ('demo_academic','Những môn nào không tính GPA?','PE101, PE201, PE301 và GEN402'),
 ('demo_academic','Có đổi GPA tổng thang 4 sang thang 10 bằng phép nhân không?','Không chuyển GPA tổng'),
 ('demo_academic','Mô hình có dự đoán điểm thang 10 của sinh viên thực tế không?','không phải dự đoán điểm số'),
 ('utt_test','Ngành Công nghệ thông tin cần bao nhiêu tín chỉ?','165 tín chỉ'),
 ('utt_test','Quy chế đào tạo áp dụng từ khóa tuyển sinh nào?','khóa 75'),
 ('utt_test','Chương trình thứ hai được đăng ký sớm nhất khi nào?','năm thứ hai'),
 ('utt_test','Học phần tiên quyết là gì?','học phần A'),
]

def evaluate(output):
    results=[]
    for scope in ('demo_academic','utt_test'):
        chunks=accessible_chunks(corpus_scope=scope)
        for _,query,gold in (c for c in CASES if c[0]==scope):
            gold_ids={c['chunk_id'] for c in chunks if gold.casefold() in c['text'].casefold()}
            for method in ('keyword','dense'):
                found=lexical_search(chunks,query,scope,date.today().isoformat(),5) if method=='keyword' else dense_search(chunks,query,5)
                ranks=[i+1 for i,r in enumerate(found) if r['chunk']['chunk_id'] in gold_ids]
                results.append({'scope':scope,'query':query,'method':method,'gold_available':bool(gold_ids),
                    'hit_at_5':bool(ranks) if gold_ids else None,'reciprocal_rank':1/min(ranks) if ranks else 0,
                    'top_titles':[r['chunk'].get('title') for r in found],
                    'citation_ids':[r['chunk']['chunk_id'] for r in found]})
    report={'protocol':'developer_smoke_v1_not_heldout','generation_evaluated':False,'results':results,'summary':{}}
    for scope in ('demo_academic','utt_test'):
        for method in ('keyword','dense'):
            rows=[r for r in results if r['scope']==scope and r['method']==method and r['gold_available']]
            report['summary'][scope+'/'+method]={'n':len(rows),'hit_at_5':sum(r['hit_at_5'] for r in rows)/len(rows) if rows else None,
                'mrr_at_5':sum(r['reciprocal_rank'] for r in rows)/len(rows) if rows else None}
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');evaluate(p.parse_args().output)
