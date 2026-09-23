"""Extracts DB and Chroma counts for consistent snapshot verification."""
import json
import chromadb
from app.store import transaction, rows

with transaction() as db:
    running = rows(db, "SELECT count(id) as cnt FROM app.document_versions WHERE status='running'")[0]['cnt']
    db_total = rows(db, "SELECT count(id) as cnt FROM app.chunks")[0]['cnt']
    db_utt_active = rows(
        db,
        "SELECT count(c.id) as cnt FROM app.chunks c JOIN app.document_versions v ON v.id=c.version_id WHERE v.status='active' AND v.scope_key='utt_corpus'"
    )[0]['cnt']

client = chromadb.PersistentClient('/vectorstore/chroma')
try:
    coll = client.get_collection('release-utt-corpus-2026-v1-staging')
    chroma_count = coll.count()
except Exception:
    chroma_count = -1

print(json.dumps({
    'running_ingests': running,
    'db_total_chunks': db_total,
    'db_utt_active': db_utt_active,
    'chroma_vector_count': chroma_count
}))
