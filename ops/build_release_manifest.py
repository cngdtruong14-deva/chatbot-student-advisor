"""Create a deterministic release receipt without reading environment secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_identity(image: str) -> dict[str, object]:
    raw = command("docker", "image", "inspect", image, "--format", "{{json .}}")
    item = json.loads(raw)
    return {
        "reference": image,
        "local_image_id": item["Id"],
        "repository_digests": sorted(item.get("RepoDigests") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    status = command("git", "status", "--porcelain")
    if args.require_clean and status:
        raise SystemExit("RELEASE_MANIFEST_REQUIRES_CLEAN_WORKTREE")
    artifacts = []
    for supplied in args.artifact:
        path = (ROOT / supplied).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise SystemExit(f"INVALID_OR_MISSING_ARTIFACT: {supplied}")
        artifacts.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
        })
    payload = {
        "schema": "student-advisor-release-manifest/1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": command("git", "rev-parse", "HEAD"),
        "source_clean": not bool(status),
        "images": {
            "api": image_identity(args.api_image),
            "web": image_identity(args.web_image),
        },
        "artifacts": sorted(artifacts, key=lambda value: value["path"]),
    }
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise SystemExit("OUTPUT_MUST_BE_INSIDE_REPOSITORY")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
