"""Pure validation for reviewed UTT corpus manifests. No DB/index side effects."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

SHA256 = re.compile(r'^[a-f0-9]{64}$')
REQUIRED_REVIEW = ('title_verified', 'source_verified', 'page_coverage_verified', 'table_coverage_verified')


def canonical_hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_reviewed_manifest(path: Path, *, expected_count: int) -> tuple[dict, dict]:
    if not path or not path.is_file():
        raise ValueError('REVIEWED_METADATA_MANIFEST_REQUIRED')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    docs = manifest.get('documents')
    if manifest.get('manifest_version') != '2.0.0' or manifest.get('status') != 'owner_reviewed':
        raise ValueError('REVIEWED_METADATA_MANIFEST_REQUIRED')
    if not manifest.get('owner') or not manifest.get('reviewed_at') or not isinstance(docs, list):
        raise ValueError('MANIFEST_OWNER_REVIEW_REQUIRED')
    try:
        reviewed_at = datetime.fromisoformat(manifest['reviewed_at'].replace('Z', '+00:00'))
        if reviewed_at.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError) as err:
        raise ValueError('INVALID_REVIEWED_AT') from err
    if len(docs) != expected_count:
        raise ValueError(f'MANIFEST_DOCUMENT_COUNT_MISMATCH: expected {expected_count}, got {len(docs)}')
    lookup = {}
    for item in docs:
        sid = item.get('source_id')
        if not sid or sid in lookup:
            raise ValueError('DUPLICATE_OR_EMPTY_SOURCE_ID')
        if not item.get('filename') or not item.get('title') or not item.get('source'):
            raise ValueError(f'INCOMPLETE_SOURCE_METADATA: {sid}')
        if not (item['source'].startswith('https://') or item['source'].startswith('gdrive:')):
            raise ValueError(f'VERIFIABLE_SOURCE_REQUIRED: {sid}')
        if not item.get('reviewer') or item.get('review_state') != 'reviewed':
            raise ValueError(f'SOURCE_NOT_REVIEWED: {sid}')
        if any(item.get(flag) is not True for flag in REQUIRED_REVIEW):
            raise ValueError(f'COVERAGE_OR_SOURCE_NOT_VERIFIED: {sid}')
        for name in ('raw_sha256', 'text_sha256'):
            if not SHA256.fullmatch(str(item.get(name, ''))):
                raise ValueError(f'INVALID_{name.upper()}: {sid}')
        if item.get('major') is None or item.get('cohort') is None:
            raise ValueError(f'SCOPE_METADATA_REQUIRED: {sid}')
        verified = item.get('is_effective_date_verified') is True
        if verified and not item.get('effective_from'):
            raise ValueError(f'VERIFIED_EFFECTIVE_DATE_MISSING: {sid}')
        try:
            start = date.fromisoformat(item['effective_from']) if item.get('effective_from') else None
            end = date.fromisoformat(item['effective_until']) if item.get('effective_until') else None
        except (TypeError, ValueError) as err:
            raise ValueError(f'INVALID_EFFECTIVE_DATE: {sid}') from err
        if start and end and end <= start:
            raise ValueError(f'INVALID_EFFECTIVE_INTERVAL: {sid}')
        lookup[sid] = item
    declared = manifest.get('manifest_sha256')
    unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    if not declared or declared != canonical_hash(unsigned):
        raise ValueError('MANIFEST_SHA256_MISMATCH')
    return manifest, lookup


def validate_source(item: dict, extracted: dict, raw_dir: Path) -> tuple[str, str]:
    raw_path = raw_dir / item['filename']
    if not raw_path.is_file() or raw_path.resolve().parent != raw_dir.resolve():
        raise ValueError(f'RAW_SOURCE_NOT_FOUND: {item["source_id"]}')
    actual_raw = file_hash(raw_path)
    actual_text = text_hash(extracted['content'])
    if actual_raw != item['raw_sha256']:
        raise ValueError(f'RAW_HASH_MISMATCH: {item["source_id"]}')
    if actual_text != item['text_sha256']:
        raise ValueError(f'TEXT_HASH_MISMATCH: {item["source_id"]}')
    return actual_raw, actual_text
