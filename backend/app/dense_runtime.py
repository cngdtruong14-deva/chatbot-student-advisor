"""Chroma/E5 local index; creation only from the ingestion CLI."""
import hashlib
import json
import os
import threading
from functools import lru_cache
from pathlib import Path

CONFIG={'embedding_model':'intfloat/multilingual-e5-small',
        'embedding_revision':'614241f622f53c4eeff9890bdc4f31cfecc418b3'}
ROOT=Path(os.environ.get('RAG_DIRECTORY','/vectorstore'))
LOCK=threading.Lock()

@lru_cache(maxsize=1)
def embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(CONFIG['embedding_model'],revision=CONFIG['embedding_revision'],
       trust_remote_code=False,local_files_only=os.environ.get('RAG_ALLOW_DOWNLOAD')!='1',device='cpu')

@lru_cache(maxsize=1)
def client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(ROOT/'chroma'),settings=Settings(anonymized_telemetry=False))

def name(version_id):
    return 'doc-'+hashlib.sha256((str(version_id)+json.dumps(CONFIG,sort_keys=True)).encode()).hexdigest()[:40]

def index(version_id,chunks):
    collection=client().get_or_create_collection(name(version_id),embedding_function=None,metadata={'hnsw:space':'cosine'})
    with LOCK:
        vectors=embedder().encode(['passage: '+c['text'] for c in chunks],normalize_embeddings=True).tolist()
    collection.upsert(ids=[c['chunk_id'] for c in chunks],embeddings=vectors)
    if collection.count()!=len(chunks): raise ValueError('INDEX_INCOMPLETE')

def search(chunks, query, k=5):
    if not chunks:
        return []
    with LOCK:
        vector = embedder().encode(['query: ' + query], normalize_embeddings=True).tolist()
    results = []
    c_client = client()

    release_chunks = {}
    legacy_chunks = []
    for c in chunks:
        ver = c.get('version')
        if ver and (ver.startswith('UTT-CORPUS-') or ver.startswith('RELEASE-')):
            release_chunks.setdefault(ver, {})[c['chunk_id']] = c
        else:
            legacy_chunks.append(c)

    for rel_id, allowed in release_chunks.items():
        candidates = [
            f"release-{rel_id.lower().replace('_', '-').replace('.', '-')}-staging",
            f"release-{rel_id.lower().replace('_', '-').replace('.', '-')}",
            rel_id,
        ]
        col = None
        for cand in candidates:
            try:
                col = c_client.get_collection(cand, embedding_function=None)
                break
            except Exception:
                continue
        if col:
            answer = col.query(
                query_embeddings=vector,
                ids=list(allowed),
                n_results=min(k, len(allowed)),
                include=['distances'],
            )
            if answer and answer.get('ids') and answer['ids'][0]:
                results.extend(
                    {'chunk': allowed[cid], 'score': 1 - float(dist)}
                    for cid, dist in zip(answer['ids'][0], answer['distances'][0])
                    if cid in allowed
                )
        else:
            raise RuntimeError('ACTIVE_RELEASE_INDEX_UNAVAILABLE')

    if legacy_chunks:
        by_version = {}
        for c in legacy_chunks:
            by_version.setdefault(c['version_id'], {})[c['chunk_id']] = c
        for version, allowed in by_version.items():
            try:
                collection = c_client.get_collection(name(version), embedding_function=None)
            except Exception:
                continue
            answer = collection.query(
                query_embeddings=vector,
                ids=list(allowed),
                n_results=min(k, len(allowed)),
                include=['distances'],
            )
            if answer and answer.get('ids') and answer['ids'][0]:
                results.extend(
                    {'chunk': allowed[cid], 'score': 1 - float(dist)}
                    for cid, dist in zip(answer['ids'][0], answer['distances'][0])
                    if cid in allowed
                )

    return sorted(results, key=lambda r: (-r['score'], r['chunk']['chunk_id']))[:k]
