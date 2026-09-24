"""Import the hash-bound UTT V2 release into an empty staging database.

The persistent Chroma collection and signed inputs must already be mounted.
No local users, chats, or unrelated database rows are copied.
"""
from __future__ import annotations

import hashlib
import faulthandler
import json
import secrets
import shutil
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

faulthandler.enable()
faulthandler.dump_traceback_later(120, repeat=True)
print(json.dumps({"status": "BOOTSTRAP", "step": "python_started"}), flush=True)

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/packages/advisor_core/src")

import chromadb
from chromadb.config import Settings
print(json.dumps({"status": "BOOTSTRAP", "step": "chromadb_imported"}), flush=True)

from advisor_core.legal_chunker import chunk_hierarchical_legal
from app.apply_effectivity_review import CONFIRM, apply_review, validate_review
from app.corpus_manifest import load_reviewed_manifest, validate_source
from app.corpus_release import RELEASE_CONFIG, activate_release
from app.security import password_hash
from app.store import one, rows, run, transaction
print(json.dumps({"status": "BOOTSTRAP", "step": "application_imports_ready"}), flush=True)


RELEASE_ID = "UTT-CORPUS-2026-V2"
ROOT = Path("/artifacts/corpus/utt-corpus-2026-v2")
EXTRACTED = ROOT / "extracted"
RAW = ROOT / "raw"
MANIFEST = ROOT / "utt_corpus_manifest_v2_signed.json"
EXCLUSIONS = ROOT / "owner_exclusions_batch01.json"
RECEIPT_PATH = Path("/artifacts/stage7/effectivity/release_receipt.current.json")
EFFECTIVITY_PATH = Path(
    "/artifacts/stage7/effectivity/utt_effectivity_review.current.signed.json"
)
CHROMA_ROOT = Path("/vectorstore/chroma")
LOCAL_CHROMA_ROOT = Path("/tmp/utt-v2-chroma")


def canonical_hash(value: dict, *, omit: tuple[str, ...] = ()) -> str:
    material = {key: item for key, item in value.items() if key not in omit}
    payload = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def prepare_release() -> tuple[dict, list[dict], list[dict], object]:
    manifest, ledger = load_reviewed_manifest(MANIFEST, expected_count=44)
    effectivity = json.loads(EFFECTIVITY_PATH.read_text(encoding="utf-8"))
    validate_review(effectivity)
    exclusions_raw = EXCLUSIONS.read_text(encoding="utf-8")
    exclusions = json.loads(exclusions_raw)
    if exclusions.get("status") != "temporarily_excluded" or not exclusions.get("owner"):
        raise ValueError("INVALID_OWNER_EXCLUSIONS_DECISION")
    excluded = {
        str(item.get("source_id"))
        for item in exclusions.get("exclusions", [])
        if item.get("source_id")
    } | {str(item) for item in exclusions.get("source_ids", [])}

    documents: list[tuple[str, Path, dict]] = []
    for path in sorted(EXTRACTED.glob("*.json")):
        if path.name in {"summary.json", "results.json"}:
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("format") not in {"pdf", "docx"} or not value.get("content"):
            continue
        if path.stem in excluded:
            continue
        if path.stem not in ledger:
            raise ValueError(f"SOURCE_NOT_IN_REVIEWED_MANIFEST:{path.stem}")
        documents.append((path.stem, path, value))
    if {item[0] for item in documents} != set(ledger) or len(documents) != 44:
        raise ValueError("SOURCE_SET_MISMATCH")

    chunks: list[dict] = []
    sources: list[dict] = []
    for source_id, _, document in documents:
        metadata = ledger[source_id]
        if document.get("filename") != metadata["filename"]:
            raise ValueError(f"EXTRACTED_FILENAME_MISMATCH:{source_id}")
        raw_hash, text_hash = validate_source(metadata, document, RAW)
        document_chunks = chunk_hierarchical_legal(
            document["content"],
            document_id=source_id,
            version_id=RELEASE_ID,
            scope="utt_corpus",
            source=metadata["filename"],
            valid_from=date.today().isoformat(),
            major=metadata["major"],
            cohort=metadata["cohort"],
            chunker_version=RELEASE_CONFIG["chunker_version"],
        )
        chunks.extend(document_chunks)
        sources.append(
            {
                "source_id": source_id,
                "filename": metadata["filename"],
                "title": metadata["title"],
                "source": metadata["source"],
                "raw_sha256": raw_hash,
                "text_sha256": text_hash,
                "major": metadata["major"],
                "cohort": metadata["cohort"],
                "reviewer": metadata["reviewer"],
            }
        )

    root_hash = hashlib.sha256(
        "\n".join(sorted(f"{item['chunk_id']}:{item['text_hash']}" for item in chunks)).encode()
    ).hexdigest()
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    if canonical_hash(receipt, omit=("receipt_sha256",)) != receipt.get("receipt_sha256"):
        raise ValueError("RECEIPT_HASH_INVALID")
    expected = {
        "release_id": RELEASE_ID,
        "document_count": 44,
        "chunk_count": len(chunks),
        "chunks_hash": root_hash,
        "source_manifest_hash": manifest["manifest_sha256"],
        "embedding_model": RELEASE_CONFIG["embedding_model"],
        "embedding_revision": RELEASE_CONFIG["embedding_revision"],
        "embedding_dimension": RELEASE_CONFIG["embedding_dimension"],
        "chunker_version": RELEASE_CONFIG["chunker_version"],
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"RECEIPT_{key.upper()}_MISMATCH")
    if not all(receipt.get("checks", {}).values()):
        raise ValueError("RECEIPT_CHECKS_FAILED")

    # Chroma's SQLite/Rust backend must not be opened directly on Azure Files
    # (SMB locking can block indefinitely).  The approved V4 runtime uses the
    # keyword retriever; this local copy is only an immutable activation check.
    if LOCAL_CHROMA_ROOT.exists():
        raise ValueError("LOCAL_CHROMA_SNAPSHOT_ALREADY_EXISTS")
    print(json.dumps({"status": "PREFLIGHT", "step": "copy_chroma_snapshot"}), flush=True)
    shutil.copytree(CHROMA_ROOT, LOCAL_CHROMA_ROOT)
    print(json.dumps({"status": "PREFLIGHT", "step": "open_local_chroma_snapshot"}), flush=True)
    client = chromadb.PersistentClient(
        path=str(LOCAL_CHROMA_ROOT), settings=Settings(anonymized_telemetry=False)
    )
    collection = client.get_collection(receipt["collection_name"], embedding_function=None)
    stored = collection.get(include=["metadatas"])
    expected_by_id = {item["chunk_id"]: item["text_hash"] for item in chunks}
    stored_by_id = {
        chunk_id: metadata.get("text_hash")
        for chunk_id, metadata in zip(stored["ids"], stored["metadatas"], strict=True)
    }
    if collection.count() != 514 or stored_by_id != expected_by_id:
        raise ValueError("CHROMA_RELEASE_CONTENT_MISMATCH")
    return receipt, sources, chunks, client


def import_database(receipt: dict, sources: list[dict], chunks: list[dict], client: object) -> None:
    with transaction() as database:
        existing = one(database, "SELECT status FROM app.corpus_releases WHERE id=:id", id=RELEASE_ID)
        if existing:
            if existing["status"] == "active":
                print(json.dumps({"status": "ALREADY_ACTIVE", "release_id": RELEASE_ID}))
                return
            raise ValueError("IMMUTABLE_RELEASE_ID_ALREADY_EXISTS")
        count = one(
            database,
            "SELECT count(*) AS count FROM app.document_versions WHERE scope_key='utt_corpus'",
        )["count"]
        if count:
            raise ValueError("UTT_CORPUS_DATABASE_NOT_EMPTY")

        owner = one(database, "SELECT id FROM app.users WHERE lower(email)='admin@demo.local'")
        if not owner:
            owner = one(
                database,
                """INSERT INTO app.users(email,username,password_hash,role,is_active)
                   VALUES('admin@demo.local','admin-demo',:password,'admin',true)
                   RETURNING id""",
                password=password_hash(secrets.token_urlsafe(48)),
            )
        owner_id = owner["id"]
        run(
            database,
            """INSERT INTO app.corpus_releases(
                 id,corpus_scope,status,chunker_version,embedding_model,embedding_revision,
                 embedding_dimension,collection_name,chunk_count,chunks_hash,
                 source_manifest_hash,receipt)
               VALUES(:id,'utt_corpus','staging',:chunker,:model,:revision,:dimension,
                 :collection,:count,:chunks_hash,:manifest_hash,CAST(:receipt AS jsonb))""",
            id=RELEASE_ID,
            chunker=receipt["chunker_version"],
            model=receipt["embedding_model"],
            revision=receipt["embedding_revision"],
            dimension=receipt["embedding_dimension"],
            collection=receipt["collection_name"],
            count=receipt["chunk_count"],
            chunks_hash=receipt["chunks_hash"],
            manifest_hash=receipt["source_manifest_hash"],
            receipt=json.dumps(receipt, ensure_ascii=False),
        )
        for source in sources:
            document = one(
                database,
                """INSERT INTO app.documents(title,document_type,source,created_by)
                   VALUES(:title,'policy',:source,:owner) RETURNING id""",
                title=source["title"],
                source=source["filename"],
                owner=owner_id,
            )
            version = one(
                database,
                """INSERT INTO app.document_versions(
                     document_id,version,content,sha256,scope_key,data_origin,corpus_label,
                     review_state,valid_from,valid_until,status,raw_sha256,effective_from,
                     effective_until,is_effective_date_verified,available_from,major,cohort,
                     education_level,reviewer,release_id,source_id,source_url,document_authority)
                   VALUES(:document,:version,:content,:sha,'utt_corpus',
                     'user_provided_institutional_document',:label,'reviewed',CURRENT_DATE,
                     '9999-12-31','ready',:raw_hash,NULL,NULL,false,CURRENT_DATE,:major,
                     :cohort,'dai_hoc',:reviewer,:release,:source_id,:source_url,
                     'official_utt_source') RETURNING id""",
                document=document["id"],
                version=RELEASE_ID,
                content="\n\n".join(
                    item["text"] for item in chunks if item["document_id"] == source["source_id"]
                ),
                sha=source["text_sha256"],
                label=f"UTT-Corpus · {RELEASE_ID} · verified",
                raw_hash=source["raw_sha256"],
                major=source["major"],
                cohort=source["cohort"],
                reviewer=source["reviewer"],
                release=RELEASE_ID,
                source_id=source["source_id"],
                source_url=source["source"],
            )
            for item in chunks:
                if item["document_id"] != source["source_id"]:
                    continue
                run(
                    database,
                    """INSERT INTO app.chunks(
                         chunk_id,version_id,section,content,text_hash,page_number,
                         locator_type,locator_label,heading,article,clause,char_start,
                         char_end,chunker_version)
                       VALUES(:chunk_id,:version_id,:section,:content,:text_hash,:page_number,
                         :locator_type,:locator_label,:heading,:article,:clause,:char_start,
                         :char_end,:chunker_version)""",
                    version_id=version["id"],
                    section=item.get("locator_label") or item["section"],
                    content=item["text"],
                    **{
                        key: item.get(key)
                        for key in (
                            "chunk_id", "text_hash", "page_number", "locator_type",
                            "locator_label", "heading", "article", "clause", "char_start",
                            "char_end", "chunker_version",
                        )
                    },
                )

    owner_id = None
    with transaction() as database:
        owner_id = one(database, "SELECT id FROM app.users WHERE lower(email)='admin@demo.local'")["id"]
    activation = activate_release(RELEASE_ID, owner_id, client)
    effectivity = json.loads(EFFECTIVITY_PATH.read_text(encoding="utf-8"))
    effectivity_result = apply_review(
        effectivity, validate_review(effectivity), confirm=CONFIRM
    )
    with transaction() as database:
        counts = one(
            database,
            """SELECT count(DISTINCT v.id) AS documents,count(c.chunk_id) AS chunks
               FROM app.document_versions v JOIN app.chunks c ON c.version_id=v.id
               WHERE v.release_id=:release AND v.status='active'
                 AND v.is_effective_date_verified=true""",
            release=RELEASE_ID,
        )
    print(
        json.dumps(
            {"status": "IMPORTED", "activation": activation, "effectivity": effectivity_result,
             "counts": counts},
            ensure_ascii=False,
            default=str,
        )
    )


def main() -> None:
    receipt, sources, chunks, client = prepare_release()
    print(json.dumps({"status": "PREFLIGHT_PASS", "documents": len(sources), "chunks": len(chunks)}))
    import_database(receipt, sources, chunks, client)
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
