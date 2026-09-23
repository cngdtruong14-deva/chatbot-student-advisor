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

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from app.store import engine, one, rows, run, transaction
from app.corpus_release import build_staging_release, activate_release, rollback_release, get_active_release, RELEASE_CONFIG
from app.knowledge import search


def main():
    # In container: /artifacts, on host: artifacts/
    extracted_dir = Path("/artifacts/phase_b/project_extracted_44")
    if not extracted_dir.exists():
        extracted_dir = Path("artifacts/phase_b/project_extracted_44")

    exclusions_file = Path("/artifacts/phase_b/owner_exclusions_batch01.json")
    if not exclusions_file.exists():
        exclusions_file = Path("artifacts/phase_b/owner_exclusions_batch01.json")

    manifest_file = Path(os.environ.get('UTT_REVIEWED_MANIFEST', 'artifacts/corpus/metadata_manifest_v2.reviewed.json'))
    raw_value = os.environ.get('UTT_RAW_DIR', '').strip()
    if not raw_value:
        raise ValueError('UTT_RAW_DIR_REQUIRED')
    raw_dir = Path(raw_value)
    action = os.environ.get('CORPUS_RELEASE_ACTION', 'build').strip().lower()
    output_dir = Path("/tmp/phase_c_v2")
    output_dir.mkdir(parents=True, exist_ok=True)

    release_id = os.environ.get('CORPUS_RELEASE_ID', 'UTT-CORPUS-2026-V2')
    corpus_scope = "utt_corpus"

    print(f"=== [PHASE C] Building Staging Corpus Release: {release_id} ===")
    print(f"Source Extracted Directory: {extracted_dir}")
    print(f"Exclusions File: {exclusions_file}")

    from app.dense_runtime import client as get_chroma_client, embedder as get_embedder
    chroma_client = get_chroma_client()
    embedder = get_embedder()


    if action == 'activate':
        print(activate_release(release_id, client_instance=chroma_client)); return
    if action == 'rollback':
        target = os.environ.get('CORPUS_ROLLBACK_TARGET', '').strip()
        if not target: raise ValueError('CORPUS_ROLLBACK_TARGET_REQUIRED')
        print(rollback_release(target, None, chroma_client)); return
    if action != 'build': raise ValueError('CORPUS_RELEASE_ACTION must be build, activate, or rollback')

    # Build only. Activation is a separate, reviewed invocation.
    staging_res = build_staging_release(
        release_id=release_id,
        corpus_scope=corpus_scope,
        extracted_dir=extracted_dir,
        owner_exclusions_file=exclusions_file if exclusions_file.exists() else None,
        metadata_manifest_file=manifest_file,
        raw_dir=raw_dir,
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

    # Export staging evidence; owner verifies before a separate activation run.
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

    print("\n=== V2 STAGING BUILT; NOT ACTIVE ===")


if __name__ == "__main__":
    main()
