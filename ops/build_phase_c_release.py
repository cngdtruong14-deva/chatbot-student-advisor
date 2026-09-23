"""Phase C Official Corpus Release Builder and Verification Script.

Executes staging release build, checks chunk/hash/embedding dimensions,
activates release UTT-CORPUS-2026-V1 with receipt, and exports corpus manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure paths
backend_dir = Path(__file__).resolve().parent.parent / "backend"
advisor_core_dir = Path(__file__).resolve().parent.parent / "packages" / "advisor_core" / "src"
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(advisor_core_dir))

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from app.store import engine, one, rows, run, transaction
from app.corpus_release import build_staging_release, activate_release, get_active_release, RELEASE_CONFIG
from app.knowledge import search


def main():
    root = Path(__file__).resolve().parent.parent
    extracted_dir = root / "artifacts" / "phase_b" / "project_extracted_44"
    exclusions_file = root / "artifacts" / "phase_b" / "owner_exclusions_batch01.json"
    output_dir = root / "artifacts" / "phase_c"
    output_dir.mkdir(parents=True, exist_ok=True)

    release_id = "UTT-CORPUS-2026-V1"
    corpus_scope = "utt_corpus"

    print(f"=== [PHASE C] Building Staging Corpus Release: {release_id} ===")
    print(f"Source Extracted Directory: {extracted_dir}")
    print(f"Exclusions File: {exclusions_file}")

    # Use EphemeralClient for build to avoid Windows/Samba SQLite WAL locks
    chroma_client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    embedder = SentenceTransformer(
        RELEASE_CONFIG["embedding_model"],
        revision=RELEASE_CONFIG["embedding_revision"],
        trust_remote_code=False,
    )

    # 1. Build staging release
    staging_res = build_staging_release(
        release_id=release_id,
        corpus_scope=corpus_scope,
        extracted_dir=extracted_dir,
        owner_exclusions_file=exclusions_file,
        client_instance=chroma_client,
        embedder_instance=embedder,
    )

    receipt = staging_res["receipt"]
    source_records = staging_res["source_records"]
    chunks = staging_res["chunks"]

    print(f"Staging Build Complete:")
    print(f"  - Document Count: {receipt['document_count']}")
    print(f"  - Total Chunks: {receipt['chunk_count']}")
    print(f"  - Embedding Model: {receipt['embedding_model']} (revision: {receipt['embedding_revision'][:10]}...)")
    print(f"  - Embedding Dimension: {receipt['embedding_dimension']}")
    print(f"  - Chunks Root Hash: {receipt['chunks_hash']}")
    print(f"  - Checks: {receipt['checks']}")

    # 2. Activate release with receipt
    print(f"\nActivating Release: {release_id}...")
    act_res = activate_release(release_id)
    print(f"Activation Result: {act_res}")

    active_info = get_active_release(corpus_scope)
    print(f"Verified Active Release in DB: {active_info['id']} (status: {active_info['status']})")

    # 3. Export corpus manifest for Phase D input
    manifest = {
        "manifest_format": "utt-corpus-manifest-v1",
        "release_id": release_id,
        "corpus_scope": corpus_scope,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "chunker_version": RELEASE_CONFIG["chunker_version"],
        "embedding_model": RELEASE_CONFIG["embedding_model"],
        "embedding_revision": RELEASE_CONFIG["embedding_revision"],
        "embedding_dimension": receipt["embedding_dimension"],
        "index_identity": receipt["collection_name"],
        "document_count": receipt["document_count"],
        "chunk_count": receipt["chunk_count"],
        "chunks_sha256": receipt["chunks_hash"],
        "source_manifest_hash": receipt["source_manifest_hash"],
        "source_set": source_records,
        "verification_receipt": receipt,
    }
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest["manifest_sha256"] = manifest_hash

    manifest_file = output_dir / "corpus_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    receipt_file = output_dir / "release_receipt.json"
    receipt_file.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nManifest and Receipt exported:")
    print(f"  - Manifest: {manifest_file} (SHA256: {manifest_hash})")
    print(f"  - Receipt: {receipt_file}")

    # 4. Verify retrieval & citation resolution on active corpus
    print("\n--- Testing Retrieval on Active Release ---")
    test_queries = [
        "Quy chế đào tạo áp dụng cho khóa nào?",
        "Điều kiện xin học lại hoặc phúc khảo bài thi?",
        "Sinh viên cần đạt bao nhiêu điểm rèn luyện để được học bổng?",
    ]

    for q in test_queries:
        res = search(q, corpus_scope=corpus_scope)
        print(f"\nQuery: {q}")
        print(f"Status: {res['status']} (citations count: {len(res['citations'])})")
        for i, cit in enumerate(res["citations"][:2]):
            print(f"  [{i+1}] Title: {cit.get('title')}")
            print(f"      Locator: {cit.get('locator_label')} (Page: {cit.get('page_number')})")
            print(f"      Version: {cit.get('version')}")
            print(f"      Effective Date Verified: {cit.get('is_effective_date_verified')}")
            print(f"      Excerpt snippet: {cit.get('excerpt', '')[:120]}...")

    print("\n=== PHASE C CORPUS RELEASE BUILD SUCCESSFUL ===")


if __name__ == "__main__":
    main()
