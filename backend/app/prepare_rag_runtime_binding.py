"""Build the immutable runtime identity used by RAG Benchmark V3 approvals."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from app.llm_runtime import prompt_sha256
from app.apply_effectivity_review import canonical_hash
from app.rag_benchmark_v2 import canonical_sha256, file_sha256


HEX64 = re.compile(r"^[a-f0-9]{64}$")
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
IMAGE_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def _load(path: Path, label: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label}_NOT_OBJECT")
    return value


def _implementation_hash(paths: list[Path], settings: dict) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            raise ValueError(f"IMPLEMENTATION_FILE_MISSING:{path}")
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--retriever-version", required=True)
    parser.add_argument("--retriever-method", choices=("keyword", "dense", "hybrid"), required=True)
    parser.add_argument("--minimum-evidence-score", type=float, required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--provider-version", required=True)
    parser.add_argument("--provider-model", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--source-archive-sha256", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("RUNTIME_BINDING_OUTPUT_EXISTS")
    if not GIT_SHA.fullmatch(args.git_commit) or not HEX64.fullmatch(args.source_archive_sha256):
        raise ValueError("RUNTIME_BINDING_SOURCE_PROVENANCE_INVALID")
    if not IMAGE_DIGEST.fullmatch(args.image_digest):
        raise ValueError("RUNTIME_BINDING_IMAGE_DIGEST_INVALID")
    receipt, manifest = _load(args.receipt, "RECEIPT"), _load(args.manifest, "MANIFEST")
    release_id = str(receipt.get("release_id") or "")
    if not release_id or manifest.get("release_id") != release_id:
        raise ValueError("RUNTIME_BINDING_RELEASE_ID_MISMATCH")
    internal_receipt_hash = str(receipt.get("receipt_sha256") or "")
    chunks_hash, source_manifest_hash = str(receipt.get("chunks_hash") or ""), str(receipt.get("source_manifest_hash") or "")
    if not all(HEX64.fullmatch(value) for value in (internal_receipt_hash, chunks_hash, source_manifest_hash)):
        raise ValueError("RUNTIME_BINDING_RELEASE_HASH_INVALID")
    if canonical_hash(receipt, omit=("receipt_sha256",)) != internal_receipt_hash:
        raise ValueError("RUNTIME_BINDING_RELEASE_RECEIPT_INVALID")
    if manifest.get("source_manifest_hash") != source_manifest_hash:
        raise ValueError("RUNTIME_BINDING_SOURCE_MANIFEST_HASH_MISMATCH")

    retriever_settings = {
        "version": args.retriever_version,
        "method": args.retriever_method,
        "minimum_evidence_score": args.minimum_evidence_score,
    }
    retriever_hash = _implementation_hash([
        args.repo_root / "backend/app/knowledge.py",
        args.repo_root / "backend/app/dense_runtime.py",
        args.repo_root / "backend/app/rag_runtime.py",
    ], retriever_settings)
    provider_settings = {"version": args.provider_version, "provider": "gemini", "model": args.provider_model}
    provider_hash = _implementation_hash([args.repo_root / "backend/app/llm_runtime.py"], provider_settings)
    release_file_binding = {
        "release_id": release_id,
        "receipt_sha256": file_sha256(args.receipt),
        "manifest_sha256": file_sha256(args.manifest),
    }
    runtime_release_context = {
        "release_id": release_id,
        "chunks_hash": chunks_hash,
        "receipt_sha256": internal_receipt_hash,
        "source_manifest_hash": source_manifest_hash,
    }
    value = {
        "release_id": release_id,
        "release": release_file_binding,
        "runtime_release_context": runtime_release_context,
        "retriever": {**retriever_settings, "sha256": retriever_hash},
        "prompt": {"version": args.prompt_version, "sha256": prompt_sha256()},
        "provider": {**provider_settings, "sha256": provider_hash},
        "source_provenance": {
            "source_kind": "clean_git_commit_source_archive",
            "clean_tree": True,
            "git_commit": args.git_commit,
            "source_archive_sha256": args.source_archive_sha256,
        },
        "execution": {"image_digest": args.image_digest, "source_mounted": False},
    }
    value["binding_sha256"] = canonical_sha256(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "RUNTIME_BINDING_CREATED", "release_id": release_id, "binding_sha256": value["binding_sha256"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
