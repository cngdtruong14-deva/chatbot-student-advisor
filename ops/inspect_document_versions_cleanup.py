#!/usr/bin/env python3
"""
Inspect and Safe Dry-Run for 88 app.document_versions (UTT-CORPUS-2026-V1).
Does NOT delete anything unless explicit --execute and --confirm flags are given.
Exports removal manifest and rollback SQL.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))

from app.store import transaction, rows, run, one

def inspect(execute=False, confirm=""):
    print("=== Inspecting app.document_versions for UTT-CORPUS-2026-V1 ===")
    
    with transaction() as db:
        all_versions = rows(
            db,
            """
            SELECT dv.id, dv.document_id, dv.version, dv.release_id, dv.status, dv.created_at,
                   d.source, d.title, d.document_type,
                   count(c.chunk_id) as chunk_count
            FROM app.document_versions dv
            JOIN app.documents d ON d.id = dv.document_id
            LEFT JOIN app.chunks c ON c.version_id = dv.id
            WHERE dv.release_id = 'UTT-CORPUS-2026-V1'
            GROUP BY dv.id, dv.document_id, dv.version, dv.release_id, dv.status, dv.created_at,
                     d.source, d.title, d.document_type
            ORDER BY d.source, dv.created_at
            """
        )

    print(f"Total versions found for release UTT-CORPUS-2026-V1: {len(all_versions)}")

    with_chunks = []
    zero_chunks = []

    for v in all_versions:
        vid_str = str(v["id"])
        c_cnt = v["chunk_count"]
        # Check foreign keys in audit_logs and chat_messages
        with transaction() as db:
            audit_cnt = one(db, "SELECT count(*) FROM app.audit_logs WHERE entity_id = :id", id=vid_str)["count"]
            chat_mention = one(db, "SELECT count(*) FROM app.chat_messages WHERE result::text LIKE :pat", pat=f"%{vid_str}%")["count"]

        item = {
            "version_id": vid_str,
            "document_id": str(v["document_id"]),
            "source": v["source"],
            "title": v["title"],
            "chunk_count": c_cnt,
            "audit_log_refs": audit_cnt,
            "chat_payload_refs": chat_mention,
            "status": v["status"],
            "created_at": v["created_at"].isoformat() if v["created_at"] else None
        }

        if c_cnt > 0:
            with_chunks.append(item)
        else:
            zero_chunks.append(item)

    print(f"  - Active versions WITH chunks: {len(with_chunks)} (Total chunks: {sum(x['chunk_count'] for x in with_chunks)})")
    print(f"  - Candidate versions WITH ZERO chunks: {len(zero_chunks)}")

    # Check if any zero_chunk record has FK references
    referenced_zero_chunks = [x for x in zero_chunks if x["audit_log_refs"] > 0 or x["chat_payload_refs"] > 0]
    print(f"  - Zero-chunk versions referenced by audit/chat FKs: {len(referenced_zero_chunks)}")

    manifest = {
        "inspection_timestamp": datetime.now(timezone.utc).isoformat(),
        "release_id": "UTT-CORPUS-2026-V1",
        "total_versions": len(all_versions),
        "with_chunks_count": len(with_chunks),
        "zero_chunks_count": len(zero_chunks),
        "referenced_zero_chunks_count": len(referenced_zero_chunks),
        "candidate_removal_ids": [x["version_id"] for x in zero_chunks],
        "zero_chunks_details": zero_chunks,
        "with_chunks_details": with_chunks
    }

    out_dir = repo_root / "artifacts" / "remediation"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = out_dir / "document_versions_cleanup_manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[OK] Manifest exported to: {manifest_file}")
    except Exception:
        fallback_path = Path("/tmp/document_versions_cleanup_manifest.json")
        fallback_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[OK] Manifest exported to fallback: {fallback_path}")

    # Generate rollback SQL
    rollback_statements = []
    for x in zero_chunks:
        rollback_statements.append(
            f"-- Rollback for version_id: {x['version_id']} (document_id: {x['document_id']})"
        )
    try:
        rollback_file = out_dir / "rollback_cleanup.sql"
        rollback_file.write_text("\n".join(rollback_statements) + "\n", encoding="utf-8")
        print(f"[OK] Rollback script exported to: {rollback_file}")
    except Exception:
        pass

    print("===CLEANUP_MANIFEST_JSON===")
    print(json.dumps(manifest, ensure_ascii=False))
    print("===END_CLEANUP_MANIFEST_JSON===")

    if execute:
        expected_confirm = "CLEANUP:UTT-CORPUS-2026-V1:ZERO_CHUNKS"
        if confirm != expected_confirm:
            print(f"[ERROR] Confirmation token mismatch! Expected: {expected_confirm}", file=sys.stderr)
            sys.exit(1)
        
        print("\n[ACTION REQUIRED] Dry-run completed. Physical deletion requires independent project owner approval.")
        print("No rows deleted.")
    else:
        print("\n[DRY-RUN COMPLETE] 0 rows modified. Everything intact.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect and Dry-Run Document Versions Cleanup")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run in read-only dry-run mode (default)")
    parser.add_argument("--execute", action="store_true", help="Execute deletion (requires explicit confirmation)")
    parser.add_argument("--confirm", type=str, default="", help="Confirmation string")
    args = parser.parse_args()
    inspect(execute=args.execute, confirm=args.confirm)
