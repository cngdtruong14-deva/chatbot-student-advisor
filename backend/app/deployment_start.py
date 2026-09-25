"""Run the bounded deployment smoke before starting the production API."""
from __future__ import annotations

import json
import os
import sys

from app.grounded_smoke import main as grounded_smoke


def preflight() -> None:
    if os.environ.get("RAG_DEPLOYMENT_GROUNDED_SMOKE_REQUIRED", "").strip().lower() not in {
        "1", "true", "yes",
    }:
        return
    exit_code = grounded_smoke()
    if exit_code != 0:
        raise RuntimeError("RAG_DEPLOYMENT_GROUNDED_SMOKE_FAILED")
    print(json.dumps({"status": "RAG_DEPLOYMENT_GROUNDED_SMOKE_PASSED"}), flush=True)


def main() -> None:
    preflight()
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "DEPLOYMENT_PREFLIGHT_FAILED", "reason": type(exc).__name__}),
              file=sys.stderr, flush=True)
        raise
