import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def jsonl(path, records):
    Path(path).write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False)+'\n' for r in records), encoding='utf-8')


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def environment():
    packages = {}
    for name in ['numpy','pandas','scipy','scikit-learn','joblib','sic-advisor-core','jsonschema','shap','chromadb','sentence-transformers']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {'python_version': platform.python_version(), 'platform': platform.platform(), 'packages': packages,
            'recorded_at': datetime.now(timezone.utc).isoformat()}


def freeze(path):
    Path(path).write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'], text=True), encoding='utf-8')


def require_approval(path, expected_hash, key='audit_sha256'):
    approval = load(path)
    if approval.get('approved') is not True or not approval.get('owner') or approval.get(key) != expected_hash:
        raise ValueError('APPROVAL_REQUIRED: inspect output, approve its exact hash; do not bypass this gate')
    return approval
