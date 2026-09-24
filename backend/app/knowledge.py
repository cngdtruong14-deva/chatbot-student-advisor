"""Database-backed versioned corpora; DEMO-1 and isolated UTT test evidence."""
import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from uuid import UUID
from fastapi import File, Request, UploadFile
from pydantic import Field, model_validator
from typing import Literal
from advisor_core.rag import chunk_markdown, lexical_search, evidence_response
from app.api import router, DTO, Actor, APIError, require_role, envelope, rate_limit
from app.store import transaction, one, rows, run
from app.document_extract import DocumentExtractionError, extract_document
from app.rag_runtime import controlled_note, decide_generation

# Passing None intentionally means an unscoped source.  A student whose scope
# cannot be resolved must never be treated as unscoped, so callers can pass
# this sentinel to make retrieval return no chunks instead.
UNRESOLVED_SCOPE = object()


class DocumentInput(DTO):
    title: str = Field(min_length=1, max_length=200)
    document_type: str = Field(default='policy', pattern='^(policy|procedure|guide)$')
    source: str = Field(min_length=1, max_length=500)
    version: str = Field(default='1', min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=100000)
    valid_from: date
    valid_until: date = date(9999, 12, 31)
    document_id: UUID | None = None
    corpus_scope: Literal['demo_academic', 'utt_test'] = 'demo_academic'

    @model_validator(mode='after')
    def validate_content(self):
        if not self.content.strip() or not self.title.strip() or not self.source.strip() or '\x00' in self.content:
            raise ValueError('EMPTY_OR_INVALID_DOCUMENT')
        if self.valid_until <= self.valid_from:
            raise ValueError('INVALID_VALIDITY_INTERVAL')
        return self


def register_document(body, uid):
    digest = hashlib.sha256(body.content.encode()).hexdigest()
    with transaction() as db:
        # Serialize idempotent registrations without changing existing content.
        run(db, 'SELECT pg_advisory_xact_lock(280401)')
        doc = one(db, 'SELECT * FROM app.documents WHERE id=:id', id=body.document_id) if body.document_id else None
        if body.document_id and not doc:
            raise APIError('RESOURCE_NOT_FOUND', 404)
        if not body.document_id:
            doc = one(db, '''SELECT d.* FROM app.documents d JOIN app.document_versions v ON v.document_id=d.id
              WHERE d.title=:title AND d.source=:source AND d.document_type=:kind AND v.sha256=:sha
              ORDER BY d.created_at LIMIT 1''', title=body.title, source=body.source, kind=body.document_type, sha=digest)
        if not doc:
            doc = one(db, '''INSERT INTO app.documents(title,document_type,source,created_by)
              VALUES(:title,:kind,:source,:uid) RETURNING *''', title=body.title, kind=body.document_type, source=body.source, uid=uid)
        prior = one(db, '''SELECT * FROM app.document_versions WHERE document_id=:id AND (version=:version OR sha256=:sha)''', id=doc['id'], version=body.version, sha=digest)
        if prior:
            if prior['sha256'] != digest or prior['version'] != body.version or prior['valid_from'] != body.valid_from or prior['valid_until'] != body.valid_until or prior['scope_key'] != body.corpus_scope:
                raise APIError('DOCUMENT_VERSION_CONFLICT', 409)
            return {'id': prior['id'], 'document_id': doc['id'], 'status': prior['status'], 'replayed': True}
        utt = body.corpus_scope in ('utt_test', 'utt_corpus')
        label = ('UTT-Corpus · verified' if body.corpus_scope == 'utt_corpus' else ('UTT-test · user-provided · not verified' if utt else ('ACADEMIC-DEMO-2.0.0' if body.version.startswith('ACADEMIC-DEMO-2.') else 'DEMO-1')))
        review = 'reviewed' if body.corpus_scope == 'utt_corpus' else ('test_only' if utt else 'approved_demo')
        item = one(db, '''INSERT INTO app.document_versions(document_id,version,content,sha256,scope_key,data_origin,corpus_label,review_state,valid_from,valid_until)
          VALUES(:id,:version,:content,:sha,:scope,:origin,:label,:review,:start,:end) RETURNING id,document_id,status,scope_key,data_origin,corpus_label,review_state''',
          id=doc['id'], version=body.version, content=body.content, sha=digest, scope=body.corpus_scope,
          origin='user_provided_institutional_document' if utt else 'synthetic',
          label=label, review=review, start=body.valid_from, end=body.valid_until)
        run(db, "INSERT INTO app.audit_logs(actor_id,action,entity_type,entity_id,status,request_id) VALUES(:uid,'register_document','document_version',:id,'pending',:id)", uid=uid, id=str(item['id']))
        return item


@router.post('/admin/documents')
def register(body: DocumentInput, user: Actor):
    require_role(user, 'admin')
    return envelope(register_document(body, user['id']))


@router.get('/admin/documents')
def list_documents(user: Actor):
    require_role(user, 'admin')
    with transaction() as db:
        return envelope({'items': rows(db, '''SELECT d.id AS document_id,d.title,d.source,d.document_type,v.id,v.version,v.status,
          v.scope_key,v.data_origin,v.corpus_label,v.review_state,v.valid_from,v.valid_until,v.error_code,v.sha256,
          v.raw_sha256,v.source_id,v.source_url,v.document_authority,v.release_id,v.reviewer,
          v.is_effective_date_verified,v.effective_from,v.effective_until,
          (SELECT count(*) FROM app.chunks c WHERE c.version_id=v.id) AS chunk_count
          FROM app.documents d JOIN app.document_versions v ON v.document_id=d.id ORDER BY v.created_at DESC LIMIT 200''')})


@router.post('/admin/documents/{version_id}/ingest')
def ingest_document(version_id: UUID, user: Actor):
    require_role(user, 'admin')
    return envelope(ingest(version_id))


@router.post('/admin/documents/{version_id}/activate')
def activate_document(version_id: UUID, user: Actor):
    require_role(user, 'admin')
    return envelope(activate(version_id))


@router.post('/admin/documents/extract')
async def extract_upload(request: Request, user: Actor, file: UploadFile = File(...)):
    require_role(user, 'admin')
    rate_limit(request, 'document_upload', 5)
    payload = await file.read(5 * 1024 * 1024 + 1)
    try:
        return envelope(extract_document(file.filename, payload, file.content_type))
    except DocumentExtractionError as exc:
        raise APIError(str(exc), 422) from exc


def _ingest(version_id):
    # Single transaction: interrupted/failed work cannot publish a partial corpus.
    with transaction() as db:
        item = one(db, 'SELECT * FROM app.document_versions WHERE id=:id FOR UPDATE', id=version_id)
        if not item:
            raise ValueError('DOCUMENT_NOT_FOUND')
        if item['status'] in ('ready','active','retired'):
            return {'id': str(version_id), 'status': item['status']}
        run(db, "UPDATE app.document_versions SET status='running',error_code=NULL WHERE id=:id", id=version_id)
        # Keep paragraph boundaries; split unusually long paragraphs deterministically.
        paragraphs = item['content'].split('\n\n')
        normalized = '\n\n'.join(p[i:i+1400] for p in paragraphs for i in range(0,len(p),1400))
        chunks = chunk_markdown(normalized, document_id=str(item['document_id']), version_id=str(item['id']),
          scope=item['scope_key'],source='database',valid_from=item['valid_from'].isoformat())
        for c in chunks:
            run(db, '''INSERT INTO app.chunks(chunk_id,version_id,section,content,text_hash)
              VALUES(:chunk,:version,:section,:content,:hash)''', chunk=c['chunk_id'],version=item['id'],section=c['section'],content=c['text'],hash=c['text_hash'])
        if os.environ.get('RAG_METHOD')=='dense':
            from app.dense_runtime import index
            index(item['id'],chunks)
        run(db, "UPDATE app.document_versions SET status='ready' WHERE id=:id", id=version_id)
    return {'id': str(version_id), 'status': 'ready', 'chunks': len(chunks)}


def ingest(version_id):
    try:
        return _ingest(version_id)
    except Exception:
        with transaction() as db:
            run(db,"UPDATE app.document_versions SET status='failed',error_code='INGEST_FAILED' WHERE id=:id AND status IN ('pending','failed')",id=version_id)
        raise


def activate(version_id):
    with transaction() as db:
        run(db, 'SELECT pg_advisory_xact_lock(280401)')
        item = one(db, 'SELECT * FROM app.document_versions WHERE id=:id FOR UPDATE', id=version_id)
        if not item or item['status'] not in ('ready','active'):
            raise ValueError('DOCUMENT_NOT_READY')
        if one(db, '''SELECT id FROM app.document_versions WHERE document_id=:doc AND id<>:id AND status='active'
          AND valid_from<:end AND valid_until>:start''', doc=item['document_id'],id=version_id,start=item['valid_from'],end=item['valid_until']):
            raise ValueError('ACTIVE_VERSION_INTERVAL_CONFLICT: retire the previous version first')
        run(db, "UPDATE app.document_versions SET status='active' WHERE id=:id", id=version_id)
        run(db, "INSERT INTO app.audit_logs(action,entity_type,entity_id,status,request_id) VALUES('activate_document','document_version',:id,'active',:id)", id=str(version_id))
    return {'id': str(version_id), 'status': 'active'}


def resolve_actor_scope(actor):
    """Resolve a student's document scope server-side.

    ``None`` remains a trusted unscoped admin/evaluator query.  An unlinked or
    incomplete student receives the literal ``all`` scope, which matches only
    documents published for every major/cohort.  A linked academic profile may
    additionally receive documents for its own major and cohort.
    """
    if not isinstance(actor, dict) or actor.get('role') != 'student':
        return {'major': None, 'cohort': None, 'resolved': True}
    user_id = actor.get('id')
    if not user_id:
        return {'major': UNRESOLVED_SCOPE, 'cohort': UNRESOLVED_SCOPE, 'resolved': False}
    try:
        with transaction() as db:
            profile = one(db, '''SELECT s.cohort,c.major
                FROM app.students s JOIN app.curricula c ON c.id=s.curriculum_id
                WHERE s.user_id=:uid''', uid=user_id)
    except Exception:
        profile = None
    if not profile or not str(profile.get('major') or '').strip() or not str(profile.get('cohort') or '').strip():
        return {'major': 'all', 'cohort': 'all', 'resolved': False}
    return {'major': profile['major'], 'cohort': profile['cohort'], 'resolved': True}


def accessible_chunks(as_of=None, document_types=None, corpus_scope='demo_academic', major=None, cohort=None):
    if major is UNRESOLVED_SCOPE or cohort is UNRESOLVED_SCOPE:
        return []
    when = as_of.date() if as_of else date.today()
    with transaction() as db:
        records = rows(db, '''SELECT c.*, d.id AS document_id, d.title, d.source, d.document_type,
          v.scope_key, v.data_origin, v.valid_from, v.valid_until, v.version,
          v.effective_from, v.effective_until, v.is_effective_date_verified,
          v.available_from, v.available_until, v.major AS doc_major, v.cohort AS doc_cohort,
          v.release_id, v.source_id, v.source_url, v.document_authority
          FROM app.chunks c JOIN app.document_versions v ON v.id=c.version_id JOIN app.documents d ON d.id=v.document_id
          WHERE v.status='active' AND v.scope_key=:scope
          AND v.valid_from<=:when AND v.valid_until>:when
          AND v.available_from<=:when AND v.available_until>:when
          AND (NOT v.is_effective_date_verified OR
              ((v.effective_from IS NULL OR v.effective_from<=:when)
               AND (v.effective_until IS NULL OR v.effective_until>:when)))''', when=when, scope=corpus_scope)
    chunks = []
    for r in records:
        if document_types and r['document_type'] not in document_types:
            continue
        # Strict scope filter by major if specified
        doc_major = (r.get('doc_major') or 'all').strip()
        if major and not _scope_matches(doc_major, major):
            continue
        # Strict scope filter by cohort if specified
        doc_cohort = (r.get('doc_cohort') or 'all').strip()
        if cohort and not _scope_matches(doc_cohort, cohort, cohort_mode=True):
            continue

        c_dict = dict(r, text=r['content'], scope=r['scope_key'], status='active', version_id=str(r['version_id']),
                     document_id=str(r['document_id']), source=r.get('source_url') or r['source'],
                     valid_from=r['valid_from'].isoformat(), valid_until=r['valid_until'].isoformat(),
                     version=r.get('version', '1'),
                     page_number=r.get('page_number'), locator_label=r.get('locator_label') or r.get('section'),
                     locator_type=r.get('locator_type', 'section'),
                     effective_from=r['effective_from'].isoformat() if r.get('effective_from') else None,
                     effective_until=r['effective_until'].isoformat() if r.get('effective_until') else None,
                     is_effective_date_verified=bool(r.get('is_effective_date_verified', False)),
                     major=r.get('doc_major'), cohort=r.get('doc_cohort'), release_id=r.get('release_id'),
                     source_id=r.get('source_id'), document_authority=r.get('document_authority'))
        chunks.append(c_dict)
    return chunks


def _scope_matches(document_scope, user_scope, cohort_mode=False):
    """Fail closed for scoped sources; support explicit comma lists and K75+."""
    allowed = [part.strip().upper() for part in str(document_scope or '').split(',') if part.strip()]
    value = str(user_scope or '').strip().upper()
    if not allowed or 'ALL' in allowed:
        return True
    if value in allowed:
        return True
    if cohort_mode:
        match = __import__('re').fullmatch(r'K(\d+)\+', allowed[0]) if len(allowed) == 1 else None
        actual = __import__('re').fullmatch(r'K(\d+)', value)
        if match and actual:
            return int(actual.group(1)) >= int(match.group(1))
    return False


def retrieve_candidates(query, chunks, method="dense", top_k=5, corpus_scope="demo_academic", when=None):
    """Shared retriever implementation supporting dense, lexical, and hybrid (RRF k=60)."""
    if not chunks:
        return []
    when_str = when.isoformat() if hasattr(when, 'isoformat') else (when or date.today().isoformat())
    if method == "dense":
        from app.dense_runtime import search as dense_search
        return dense_search(chunks, query, k=top_k)
    elif method in ("lexical", "keyword"):
        return lexical_search(chunks, query, corpus_scope, when_str, top_k)
    elif method == "hybrid":
        lex_matches = lexical_search(chunks, query, corpus_scope, when_str, 20)
        from app.dense_runtime import search as dense_search
        dense_matches = dense_search(chunks, query, k=20)
        rrf_k = 60
        scores = {}
        chunk_map = {}
        for rank, m in enumerate(lex_matches, start=1):
            cid = m['chunk']['chunk_id']
            chunk_map[cid] = m['chunk']
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
        for rank, m in enumerate(dense_matches, start=1):
            cid = m['chunk']['chunk_id']
            chunk_map[cid] = m['chunk']
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (rrf_k + rank))
        sorted_cids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
        return [{'chunk': chunk_map[cid], 'score': scores[cid]} for cid in sorted_cids]
    else:
        raise ValueError(f"UNSUPPORTED_RETRIEVAL_METHOD: {method}")


def search(query, as_of=None, document_types=None, corpus_scope='demo_academic', major=None, cohort=None):
    method = os.environ.get('RAG_METHOD', 'dense')
    try:
        when = (as_of.date() if as_of else date.today()).isoformat()
        # Authorization and release integrity have different boundaries. A
        # student retrieves only chunks matching their major/cohort, but the
        # signed receipt is bound to the complete active release. Hashing the
        # filtered subset would incorrectly classify a valid release as
        # incomplete for every scoped student.
        chunks = accessible_chunks(as_of, document_types, corpus_scope, major=major, cohort=cohort)
        release_chunks = (
            accessible_chunks(as_of, None, corpus_scope)
            if corpus_scope == 'utt_corpus' and (major is not None or cohort is not None)
            else chunks
        )
        found = retrieve_candidates(query, chunks, method=method, top_k=5, corpus_scope=corpus_scope, when=when)
    except Exception:
        # Retrieval backends can expose local paths, collection names, or vendor
        # details in exceptions.  The chat contract deliberately has one stable
        # public state instead of returning those implementation details.
        result = evidence_response([], query)
        result.update(retrieval_status='unavailable', retrieval_method=method,
                      reason='RETRIEVAL_UNAVAILABLE', response_mode='retrieval_only',
                      rag_mode='beta_controlled' if corpus_scope == 'utt_corpus' else 'standard')
        return result

    # A UTT answer reaches a provider only through this fail-closed decision.
    # In every controlled branch, evidence_response receives no provider and
    # therefore uses GenerationUnavailable without instantiating Gemini.
    decision = decide_generation(query=query, matches=found, corpus_scope=corpus_scope,
                                 method=method, chunks=release_chunks)
    if decision.generation_allowed:
        from app.llm_runtime import OpenAICompatibleProvider
        result = evidence_response(found, query, OpenAICompatibleProvider())
    else:
        result = evidence_response(found, query)
        result.update(status='insufficient_evidence', answer=None, claims=[],
                      generation_status='controlled_retrieval', response_mode=decision.response_mode,
                      rag_mode=decision.rag_mode, reason=decision.reason,
                      note=controlled_note(decision.reason))
    for citation, match in zip(result['citations'], found):
        c = match['chunk']
        citation.update({k: c.get(k) for k in (
            'document_id', 'title', 'valid_from', 'valid_until', 'version',
            'page_number', 'locator_label', 'locator_type', 'major', 'cohort',
            'effective_from', 'effective_until', 'is_effective_date_verified'
            , 'release_id', 'source_id', 'document_authority', 'source', 'text_hash'
        )})
        citation['scope'] = c.get('scope') or c.get('scope_key')
    test_only = corpus_scope == 'utt_test'
    is_official = corpus_scope == 'utt_corpus'
    if test_only:
        result['warning'] = 'Kho UTT-test do người dùng cung cấp để thử truy xuất; hiệu lực và phạm vi văn bản chưa được xác minh chính thức.'
        if result.get('answer'):
            result['answer'] = result['warning'] + '\n\n' + result['answer']
    elif is_official:
        result['warning'] = (
            'Chế độ sinh câu trả lời demo Capstone: Benchmark V4 đạt correctness proxy 87,5% và '
            '59/60 review ngữ nghĩa; mọi câu trả lời phải kèm trích dẫn. Nội dung học vụ quan trọng '
            'vẫn chỉ hiển thị bằng chứng để người dùng đối chiếu.'
            if decision.rag_mode in {'approved_grounded_capstone', 'approved_grounded_capstone_high_stakes'}
            else 'Kho văn bản UTT BETA được phát hành từ nguồn UTT đã được owner duyệt. '
                 'Tài liệu chưa xác minh ngày hiệu lực hoặc chưa có phê duyệt benchmark '
                 'chỉ được hiển thị dưới dạng trích đoạn để người dùng đối chiếu.'
        )
    release_ids = {str(c.get('release_id')) for c in chunks if c.get('release_id')}
    result.update(retrieval_method=method, corpus_scope=corpus_scope,
                  corpus_version=hashlib.sha256(''.join(sorted(c['chunk_id'] for c in chunks)).encode()).hexdigest(),
                  data_origin='user_provided_institutional_document' if (test_only or is_official) else 'synthetic',
                  test_only=test_only,
                  release_id=next(iter(release_ids)) if len(release_ids) == 1 else None)
    # Older/demo callers retain their original generated/fallback behaviour;
    # these fields make the delivery mode explicit to new cards and evaluators.
    result.setdefault('response_mode', decision.response_mode)
    result.setdefault('rag_mode', decision.rag_mode)
    result.setdefault('reason', decision.reason)
    return result


def export_corpus(as_of=None, corpus_scope='demo_academic'):
    """Emit only approved, active corpus data; never mutates benchmarks or index."""
    chunks = accessible_chunks(as_of, corpus_scope=corpus_scope)
    config_path = Path(__file__).with_name('resources').joinpath('rag_config.json')
    config = json.loads(config_path.read_text(encoding='utf-8'))
    payload = {"export_format": "approved-corpus-v1", "chunks": chunks, "config": config}
    payload["chunks_sha256"] = hashlib.sha256(json.dumps(chunks, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    payload["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    return payload


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['ingest','activate','retire','seed-demo','export-evaluation'])
    parser.add_argument('--version-id',type=UUID)
    args=parser.parse_args()
    if args.action == 'export-evaluation':
        print(json.dumps(export_corpus(), ensure_ascii=False, default=str)); return
    if args.action=='seed-demo':
        with transaction() as db:
            owner=one(db,"SELECT id FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
        if not owner: raise ValueError('ADMIN_REQUIRED')
        body=DocumentInput(title='DEMO-1 — Chính sách mô phỏng',source='repo:ml/rag/corpus/DEMO1.md',version='DEMO-1-r1',
            content=Path(__file__).with_name('resources').joinpath('DEMO1.md').read_text(encoding='utf-8'),valid_from=date(2026,9,6))
        item=register_document(body,owner['id']); ingest(item['id']); print(json.dumps(activate(item['id']))); return
    if args.version_id is None: parser.error('--version-id required')
    if args.action=='retire':
        with transaction() as db:
            run(db,"UPDATE app.document_versions SET status='retired' WHERE id=:id AND status='active'",id=args.version_id)
        print('retired'); return
    print(json.dumps(ingest(args.version_id) if args.action=='ingest' else activate(args.version_id)))


if __name__=='__main__': main()
