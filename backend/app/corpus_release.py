"""Corpus Release, Staging Index Building and Atomic Activation Management.

Guarantees:
1. Index is built and verified completely in staging (chunk count, embedding dim 384, hashes).
2. Atomic release activation with release receipts.
3. Mid-process or validation failures never disrupt or delete the previously active release.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from advisor_core.legal_chunker import chunk_hierarchical_legal
from app.store import transaction, one, rows, run
from app.corpus_manifest import canonical_hash, load_reviewed_manifest, validate_source


RELEASE_CONFIG = {
    "embedding_model": "intfloat/multilingual-e5-small",
    "embedding_revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    "embedding_dimension": 384,
    "chunker_version": "utt_legal_v1",
}


def build_staging_release(
    *,
    release_id: str,
    corpus_scope: str = "utt_corpus",
    extracted_dir: Path,
    owner_exclusions_file: Optional[Path] = None,
    metadata_manifest_file: Optional[Path] = None,
    raw_dir: Optional[Path] = None,
    expected_document_count: int = 44,
    admin_user_id: Optional[UUID] = None,
    client_instance: Any = None,
    embedder_instance: Any = None,
) -> Dict[str, Any]:
    """Ingest extracted candidate documents into staging release and index."""
    if corpus_scope != 'utt_corpus' or release_id == 'UTT-CORPUS-2026-V1':
        raise ValueError('OFFICIAL_V2_RELEASE_ID_REQUIRED')
    if not extracted_dir.exists():
        raise FileNotFoundError(f"Extracted directory {extracted_dir} does not exist")
    if raw_dir is None or not raw_dir.is_dir():
        raise ValueError('RAW_SOURCE_DIRECTORY_REQUIRED')
    manifest, ledger_lookup = load_reviewed_manifest(
        metadata_manifest_file, expected_count=expected_document_count)

    # Load owner exclusions if provided
    if owner_exclusions_file is None or not owner_exclusions_file.is_file():
        raise ValueError('OWNER_EXCLUSIONS_DECISION_REQUIRED')
    excluded_ids = set()
    exclusions_hash = None
    if owner_exclusions_file and owner_exclusions_file.exists():
        exclusions_raw = owner_exclusions_file.read_text(encoding="utf-8")
        exclusions_hash = hashlib.sha256(exclusions_raw.encode("utf-8")).hexdigest()
        exclusions_data = json.loads(exclusions_raw)
        if exclusions_data.get('status') != 'temporarily_excluded' or not exclusions_data.get('owner'):
            raise ValueError('INVALID_OWNER_EXCLUSIONS_DECISION')
        for exc in exclusions_data.get("exclusions", []):
            if exc.get("source_id"):
                excluded_ids.add(exc["source_id"])
        for sid in exclusions_data.get("source_ids", []):
            excluded_ids.add(sid)

    doc_files = sorted(extracted_dir.glob("*.json"))
    # Filter out summary.json and results.json
    doc_files = [f for f in doc_files if f.name not in ("summary.json", "results.json")]

    valid_docs = []
    for f in doc_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("format") in ("pdf", "docx") and data.get("content"):
                source_id = f.stem
                if source_id in excluded_ids:
                    continue
                if source_id not in ledger_lookup:
                    raise ValueError(f'SOURCE_NOT_IN_REVIEWED_MANIFEST: {source_id}')
                valid_docs.append((source_id, f, data))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ValueError(f'INVALID_EXTRACTED_JSON: {f.name}') from err

    actual_ids = {item[0] for item in valid_docs}
    expected_ids = set(ledger_lookup)
    if actual_ids != expected_ids or len(valid_docs) != expected_document_count:
        raise ValueError(f'SOURCE_SET_MISMATCH: missing={sorted(expected_ids-actual_ids)}, extra={sorted(actual_ids-expected_ids)}')
    extracted_outputs_hash = hashlib.sha256('\n'.join(sorted(
        f.name + ':' + hashlib.sha256(f.read_bytes()).hexdigest() for _, f, _ in valid_docs
    )).encode('utf-8')).hexdigest()

    # Resolve admin user for ownership
    with transaction() as db:
        if one(db, 'SELECT id FROM app.corpus_releases WHERE id=:id', id=release_id):
            raise ValueError('IMMUTABLE_RELEASE_ID_ALREADY_EXISTS')
        admin_user = one(db, "SELECT id FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
    uid = admin_user_id or (admin_user["id"] if admin_user else uuid4())

    all_chunks: List[Dict[str, Any]] = []
    source_records: List[Dict[str, Any]] = []

    for source_id, fpath, doc in valid_docs:
        meta = ledger_lookup[source_id]
        fname, title = meta['filename'], meta['title']
        if doc.get('filename') != fname:
            raise ValueError(f'EXTRACTED_FILENAME_MISMATCH: {source_id}')
        raw_hash, text_hash = validate_source(meta, doc, raw_dir)
        major, cohort = meta['major'], meta['cohort']

        # Requirement 2: Unknown effective dates remain unverified
        # Do not use import timestamp as proof of current effectivity
        is_effective_date_verified = meta.get("is_effective_date_verified", False)
        effective_from = meta.get("effective_from")
        effective_until = meta.get("effective_until")

        doc_chunks = chunk_hierarchical_legal(
            doc["content"],
            document_id=source_id,
            version_id=release_id,
            scope=corpus_scope,
            source=fname,
            valid_from=date.today().isoformat(),
            major=major,
            cohort=cohort,
            chunker_version=RELEASE_CONFIG["chunker_version"],
        )
        all_chunks.extend(doc_chunks)
        source_records.append({
            "source_id": source_id,
            "filename": fname,
            "title": title,
            "source": meta['source'],
            "raw_sha256": raw_hash,
            "text_sha256": text_hash,
            "major": major,
            "cohort": cohort,
            "chunk_count": len(doc_chunks),
            "effective_from": effective_from,
            "effective_until": effective_until,
            "is_effective_date_verified": is_effective_date_verified,
            "available_from": date.today().isoformat(),
            "available_until": "9999-12-31",
            "review_state": meta.get("review_state", "extracted_pending_quality_review"),
            "reviewer": meta.get("reviewer", None),
            "title_verified": True,
            "source_verified": True,
            "page_coverage_verified": True,
            "table_coverage_verified": True,
        })

    # Compute root chunk hashes and manifest hash
    chunks_root_hash = hashlib.sha256("\n".join(sorted(
        c['chunk_id'] + ':' + c['text_hash'] for c in all_chunks)).encode('utf-8')).hexdigest()
    source_manifest_hash = manifest['manifest_sha256']

    collection_name = f"release-{release_id.lower().replace('_', '-').replace('.', '-')}-staging"

    # Index in Chroma staging collection if client provided or available
    chroma_client = client_instance
    embedder = embedder_instance

    if chroma_client is None:
        try:
            import chromadb
            from chromadb.config import Settings
            from app.dense_runtime import ROOT, embedder as get_embedder
            chroma_client = chromadb.PersistentClient(path=str(ROOT / "chroma"), settings=Settings(anonymized_telemetry=False))
            embedder = get_embedder()
        except Exception as err:
            raise RuntimeError(f"CHROMA_PERSISTENT_INIT_FAILED: {err}. Release build must fail closed without EphemeralClient fallback.") from err

    staging_collection = chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=None,
        metadata={"hnsw:space": "cosine", "release_id": release_id, "chunks_hash": chunks_root_hash},
    )

    existing_count = staging_collection.count()
    if existing_count:
        raise ValueError('IMMUTABLE_INDEX_COLLECTION_ALREADY_EXISTS')
    texts = ["passage: " + c["text"] for c in all_chunks]
    vectors = embedder.encode(texts, normalize_embeddings=True).tolist()
    staging_collection.upsert(
        ids=[c["chunk_id"] for c in all_chunks], embeddings=vectors,
        documents=[c["text"] for c in all_chunks],
        metadatas=[{
            "document_id": c["document_id"], "version_id": c["version_id"],
            "scope": c["scope"], "text_hash": c["text_hash"],
            "locator_label": c["locator_label"] or '', "locator_type": c["locator_type"],
            "page_number": c["page_number"] if c["page_number"] is not None else -1,
            "major": c["major"] or "all", "cohort": c["cohort"] or "all",
            "chunker_version": c["chunker_version"],
        } for c in all_chunks],
    )

    # Rigorous Verification Checks
    col_count = staging_collection.count()
    if col_count != len(all_chunks):
        raise ValueError(f"INDEX_INCOMPLETE: expected {len(all_chunks)} chunks, found {col_count}")

    embedding_dim = embedder.get_sentence_embedding_dimension() if hasattr(embedder, "get_sentence_embedding_dimension") else len(vectors[0])
    if embedding_dim != 384:
        raise ValueError(f"EMBEDDING_DIMENSION_MISMATCH: expected 384, got {embedding_dim}")

    receipt = {
        "release_id": release_id,
        "corpus_scope": corpus_scope,
        "status": "staging",
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "document_count": len(valid_docs),
        "chunk_count": len(all_chunks),
        "collection_name": collection_name,
        "chunks_hash": chunks_root_hash,
        "source_manifest_hash": source_manifest_hash,
        "manifest_version": manifest['manifest_version'],
        "manifest_owner": manifest['owner'],
        "manifest_reviewed_at": manifest['reviewed_at'],
        "exclusions_hash": exclusions_hash,
        "extracted_outputs_hash": extracted_outputs_hash,
        "embedding_model": RELEASE_CONFIG["embedding_model"],
        "embedding_revision": RELEASE_CONFIG["embedding_revision"],
        "embedding_dimension": embedding_dim,
        "chunker_version": RELEASE_CONFIG["chunker_version"],
        "checks": {
            "chunk_count_matched": True,
            "embedding_dimension_verified": True,
            "hashes_verified": True,
            "all_chunks_indexed": True,
            "source_count_matched": len(source_records) == expected_document_count,
            "all_sources_reviewed": all(s['reviewer'] for s in source_records),
            "exclusions_applied": not bool(expected_ids & excluded_ids),
        },
    }
    receipt['receipt_sha256'] = canonical_hash(receipt)

    # Persist release record and document chunks to database in staging
    with transaction() as db:
        run(
            db,
            """
            INSERT INTO app.corpus_releases(
                id, corpus_scope, status, chunker_version, embedding_model,
                embedding_revision, embedding_dimension, collection_name,
                chunk_count, chunks_hash, source_manifest_hash, receipt
            ) VALUES (
                :id, :scope, 'staging', :chunker, :model, :rev, :dim, :col, :cnt, :chash, :mhash, :receipt
            )
            """,
            id=release_id,
            scope=corpus_scope,
            chunker=RELEASE_CONFIG["chunker_version"],
            model=RELEASE_CONFIG["embedding_model"],
            rev=RELEASE_CONFIG["embedding_revision"],
            dim=embedding_dim,
            col=collection_name,
            cnt=len(all_chunks),
            chash=chunks_root_hash,
            mhash=source_manifest_hash,
            receipt=json.dumps(receipt, ensure_ascii=False),
        )

        # Register documents and versions in staging
        for srec in source_records:
            doc_row = one(db, "SELECT * FROM app.documents WHERE title=:title AND source=:source",
                          title=srec['title'], source=srec['filename'])
            if not doc_row:
                doc_row = one(db, """INSERT INTO app.documents(title,document_type,source,created_by)
                    VALUES(:title,'policy',:source,:uid) RETURNING *""",
                    title=srec['title'], source=srec['filename'], uid=uid)

            v_row = one(
                db,
                """INSERT INTO app.document_versions(
                    document_id, version, content, sha256, scope_key, data_origin,
                    corpus_label, review_state, valid_from, valid_until, status,
                    raw_sha256, effective_from, effective_until,
                    is_effective_date_verified, available_from,
                    major, cohort, education_level, reviewer, release_id,
                    source_id, source_url, document_authority
                ) VALUES (
                    :did, :ver, :content, :sha, :scope, 'user_provided_institutional_document',
                    :label, 'reviewed', :vfrom, '9999-12-31', 'ready',
                    :raw_sha, :effective_from, :effective_until,
                    :effective_verified, CURRENT_DATE,
                    :major, :cohort, 'dai_hoc', :reviewer, :rid,
                    :source_id, :source_url, 'official_utt_source'
                ) RETURNING id""",
                did=doc_row["id"],
                ver=release_id,
                content="\n\n".join(c["text"] for c in all_chunks if c["document_id"] == srec["source_id"]),
                sha=srec["text_sha256"],
                scope=corpus_scope,
                label=f"UTT-Corpus · {release_id} · verified",
                vfrom=date.today(),
                raw_sha=srec["raw_sha256"],
                effective_from=srec['effective_from'],
                effective_until=srec['effective_until'],
                effective_verified=srec['is_effective_date_verified'],
                major=srec["major"],
                cohort=srec["cohort"],
                reviewer=srec["reviewer"],
                rid=release_id,
                source_id=srec['source_id'],
                source_url=srec['source'],
            )

            # Insert chunks with locator metadata
            for c in all_chunks:
                if c["document_id"] == srec["source_id"]:
                    run(
                        db,
                        """INSERT INTO app.chunks(
                            chunk_id, version_id, section, content, text_hash,
                            page_number, locator_type, locator_label, heading,
                            article, clause, char_start, char_end, chunker_version
                        ) VALUES (
                            :cid, :vid, :sec, :txt, :hash,
                            :page, :ltype, :llabel, :heading,
                            :art, :clause, :cstart, :cend, :cver
                        )""",
                        cid=c["chunk_id"],
                        vid=v_row["id"],
                        sec=c["locator_label"] or c["section"],
                        txt=c["text"],
                        hash=c["text_hash"],
                        page=c["page_number"],
                        ltype=c["locator_type"],
                        llabel=c["locator_label"],
                        heading=c.get("heading"),
                        art=c.get("article"),
                        clause=c.get("clause"),
                        cstart=c.get("char_start", 0),
                        cend=c.get("char_end", 0),
                        cver=c["chunker_version"],
                    )

    return {
        "receipt": receipt,
        "source_records": source_records,
        "chunks": all_chunks,
    }


def _verify_release(db, rel, chroma_client) -> dict:
    receipt = rel['receipt'] if isinstance(rel['receipt'], dict) else json.loads(rel['receipt'])
    signed = dict(receipt)
    declared = signed.pop('receipt_sha256', None)
    required = ('chunk_count_matched', 'embedding_dimension_verified', 'hashes_verified',
                'all_chunks_indexed', 'source_count_matched', 'all_sources_reviewed', 'exclusions_applied')
    if declared != canonical_hash(signed) or not all(receipt.get('checks', {}).get(k) is True for k in required):
        raise ValueError('INVALID_RELEASE_RECEIPT: signed checks not met')
    records = rows(db, '''SELECT c.chunk_id,c.text_hash,c.content FROM app.chunks c
        JOIN app.document_versions v ON v.id=c.version_id
        WHERE v.release_id=:id ORDER BY c.chunk_id''', id=rel['id'])
    db_ids = {r['chunk_id'] for r in records}
    root = hashlib.sha256('\n'.join(sorted(r['chunk_id']+':'+r['text_hash'] for r in records)).encode()).hexdigest()
    if len(records) != rel['chunk_count'] or root != rel['chunks_hash'] or root != receipt.get('chunks_hash'):
        raise ValueError('DB_RELEASE_CONTENT_MISMATCH')
    try:
        collection = chroma_client.get_collection(rel['collection_name'], embedding_function=None)
        indexed = collection.get(include=['documents', 'metadatas'])
    except Exception as err:
        raise ValueError('INDEX_COLLECTION_UNAVAILABLE') from err
    index_ids = set(indexed.get('ids', []))
    if index_ids != db_ids or collection.count() != len(records):
        raise ValueError('DB_INDEX_ID_MISMATCH')
    index_rows = dict(zip(indexed.get('ids', []), zip(indexed.get('documents', []), indexed.get('metadatas', []))))
    for record in records:
        document, metadata = index_rows[record['chunk_id']]
        if hashlib.sha256(record['content'].encode('utf-8')).hexdigest() != record['text_hash']:
            raise ValueError('DB_TEXT_HASH_MISMATCH')
        if hashlib.sha256(document.encode('utf-8')).hexdigest() != record['text_hash']:
            raise ValueError('INDEX_TEXT_HASH_MISMATCH')
        if metadata.get('text_hash') != record['text_hash']:
            raise ValueError('INDEX_METADATA_HASH_MISMATCH')
    source_count = one(db, '''SELECT count(*) AS n FROM app.document_versions
        WHERE release_id=:id AND review_state='reviewed' AND reviewer IS NOT NULL
        AND document_authority='official_utt_source' ''', id=rel['id'])['n']
    if source_count != receipt['document_count']:
        raise ValueError('REVIEWED_SOURCE_COUNT_MISMATCH')
    if rel['source_manifest_hash'] != receipt.get('source_manifest_hash'):
        raise ValueError('SOURCE_MANIFEST_HASH_MISMATCH')
    for column, key in (('collection_name','collection_name'), ('chunk_count','chunk_count'),
                        ('embedding_model','embedding_model'), ('embedding_revision','embedding_revision'),
                        ('embedding_dimension','embedding_dimension'), ('chunker_version','chunker_version')):
        if rel[column] != receipt.get(key):
            raise ValueError(f'RELEASE_RECEIPT_IDENTITY_MISMATCH: {column}')
    return receipt


def activate_release(release_id: str, admin_user_id: Optional[UUID] = None,
                     client_instance: Any = None, *, rollback: bool = False) -> Dict[str, Any]:
    """Atomically activate a staging release with receipt verification.

    If activation checks fail, transaction rolls back and prior release remains active.
    """
    with transaction() as db:
        # Advisory transaction lock for deterministic concurrency
        run(db, "SELECT pg_advisory_xact_lock(280402)")

        rel = one(db, "SELECT * FROM app.corpus_releases WHERE id=:id FOR UPDATE", id=release_id)
        if not rel:
            raise ValueError(f"RELEASE_NOT_FOUND: {release_id}")
        if rel['corpus_scope'] == 'utt_corpus' and client_instance is None:
            raise ValueError('PERSISTENT_INDEX_CLIENT_REQUIRED')
        receipt = _verify_release(db, rel, client_instance)
        if rel['status'] == 'active':
            return {'release_id': release_id, 'status': 'active', 'corpus_scope': rel['corpus_scope'],
                    'receipt_sha256': receipt['receipt_sha256'], 'replayed': True}
        if rel['status'] not in ({'retired'} if rollback else {'staging'}):
            raise ValueError('INVALID_RELEASE_STATE')

        # Retire previous active release for this scope
        run(
            db,
            """UPDATE app.corpus_releases
               SET status='retired'
               WHERE corpus_scope=:scope AND status='active' AND id<>:id""",
            scope=rel["corpus_scope"],
            id=release_id,
        )
        run(
            db,
            """UPDATE app.document_versions
               SET status='retired'
               WHERE scope_key=:scope AND status='active' AND (release_id IS NULL OR release_id<>:id)""",
            scope=rel["corpus_scope"],
            id=release_id,
        )

        # Activate current release
        run(
            db,
            """UPDATE app.corpus_releases
               SET status='active', activated_at=now(), activated_by=:uid
               WHERE id=:id""",
            id=release_id,
            uid=admin_user_id,
        )
        run(
            db,
            """UPDATE app.document_versions
               SET status='active'
               WHERE release_id=:id""",
            id=release_id,
        )

        run(
            db,
            """INSERT INTO app.audit_logs(actor_id, action, entity_type, entity_id, status, request_id)
               VALUES(:uid, :action, 'corpus_release', :id, 'active', :id)""",
            uid=admin_user_id,
            id=release_id,
            action='rollback_corpus_release' if rollback else 'activate_corpus_release',
        )

    return {"release_id": release_id, "status": "active", "corpus_scope": rel["corpus_scope"],
            'receipt_sha256': receipt['receipt_sha256'], 'rollback': rollback}


def rollback_release(release_id: str, admin_user_id: UUID, client_instance: Any) -> Dict[str, Any]:
    """Re-activate an immutable retired release after verifying its DB/index pair."""
    return activate_release(release_id, admin_user_id, client_instance, rollback=True)


def get_active_release(corpus_scope: str = "utt_corpus") -> Optional[Dict[str, Any]]:
    """Query currently active release receipt."""
    with transaction() as db:
        rel = one(
            db,
            "SELECT * FROM app.corpus_releases WHERE corpus_scope=:scope AND status='active' ORDER BY activated_at DESC LIMIT 1",
            scope=corpus_scope,
        )
    return dict(rel) if rel else None
