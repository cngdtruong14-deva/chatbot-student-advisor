"""Idempotent owner-approved demo policy ingestion through the existing lifecycle."""
import json
from pathlib import Path
from datetime import date
from app.knowledge import DocumentInput, register_document, ingest, activate
from app.store import transaction, one, run

def main():
    with transaction() as db:
        owner=one(db,"SELECT id FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
    if not owner: raise ValueError('ADMIN_REQUIRED')
    body=DocumentInput(title='Academic Demo v2 — Chính sách mô phỏng',
        source='repo:backend/app/resources/ACADEMIC_DEMO_V2.md',version='ACADEMIC-DEMO-2.0.0-rag-r1',
        content=Path(__file__).with_name('resources').joinpath('ACADEMIC_DEMO_V2.md').read_text(encoding='utf-8'),
        valid_from=date(2026,9,17),corpus_scope='demo_academic')
    item=register_document(body,owner['id'])
    with transaction() as db:
        run(db,"UPDATE app.document_versions SET corpus_label='ACADEMIC-DEMO-2.0.0' WHERE id=:id AND scope_key='demo_academic'",id=item['id'])
    ingested=ingest(item['id'])
    print(json.dumps({'ingest':ingested,'activation':activate(item['id'])},default=str))

if __name__=='__main__': main()
