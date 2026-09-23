"""Sign an already completed owner review; never fills review decisions."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from app.corpus_manifest import canonical_hash, load_reviewed_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args()
    if args.confirm != 'OWNER_REVIEWED_44_SOURCES':
        raise ValueError('EXPLICIT_OWNER_REVIEW_CONFIRMATION_REQUIRED')
    if args.output.exists():
        raise ValueError('OUTPUT_EXISTS_USE_A_NEW_SIGNED_FILE')
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    if len(payload.get('documents', [])) != 44:
        raise ValueError('EXACTLY_44_REVIEWED_SOURCES_REQUIRED')
    for item in payload['documents']:
        if item.get('review_state') != 'reviewed' or not item.get('reviewer'):
            raise ValueError(f'SOURCE_NOT_REVIEWED: {item.get("source_id")}')
        if not all(item.get(key) is True for key in (
                'title_verified','source_verified','page_coverage_verified','table_coverage_verified')):
            raise ValueError(f'REVIEW_FLAGS_INCOMPLETE: {item.get("source_id")}')
    payload.update(manifest_version='2.0.0', status='owner_reviewed', owner=args.owner,
                   reviewed_at=datetime.now(timezone.utc).isoformat())
    payload.pop('manifest_sha256', None)
    payload['manifest_sha256'] = canonical_hash(payload)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    # Re-open using the same fail-closed validator used by the builder.
    load_reviewed_manifest(args.output, expected_count=44)
    print(json.dumps({'output':str(args.output),'document_count':44,
                      'manifest_sha256':payload['manifest_sha256']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
