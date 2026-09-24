"""Read-only verification for the Azure staging runtime."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from app.store import engine


def main() -> None:
    paths = [
        Path("/artifacts/stage7/benchmark_v4/rag_runtime_approval_capstone_v4.signed.json"),
        Path("/artifacts/stage7/benchmark_v4/rag_high_stakes_grounded_capstone_v4.signed.json"),
        Path("/artifacts/stage7/effectivity/release_receipt.current.json"),
    ]
    print(
        "FILES="
        + json.dumps(
            [
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in paths
            ]
        )
    )
    with engine().connect() as connection:
        values = {
            "users": connection.exec_driver_sql("SELECT count(*) FROM app.users").scalar(),
            "utt_versions": connection.exec_driver_sql(
                "SELECT count(*) FROM app.document_versions WHERE scope_key='utt_corpus'"
            ).scalar(),
            "utt_chunks": connection.exec_driver_sql(
                "SELECT count(*) FROM app.chunks c "
                "JOIN app.document_versions v ON v.id=c.version_id "
                "WHERE v.scope_key='utt_corpus'"
            ).scalar(),
            "active_release": connection.exec_driver_sql(
                "SELECT coalesce(max(id),'none') FROM app.corpus_releases "
                "WHERE corpus_scope='utt_corpus' AND status='active'"
            ).scalar(),
        }
    print("COUNTS=" + json.dumps(values))


if __name__ == "__main__":
    main()
