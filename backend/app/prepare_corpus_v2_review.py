"""Create an unsigned owner-review template. Never marks a source reviewed."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from app.corpus_manifest import file_hash, text_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extracted-dir', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--exclusions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('OUTPUT_EXISTS_USE_A_NEW_REVIEW_FILE')
    ledger = json.loads(args.ledger.read_text(encoding='utf-8'))
    prior = {d['source_id']: d for d in ledger.get('documents', [])}
    exclusions = json.loads(args.exclusions.read_text(encoding='utf-8'))
    excluded = set(exclusions.get('source_ids', [])) | {
        e['source_id'] for e in exclusions.get('exclusions', []) if e.get('source_id')}
    documents = []
    for path in sorted(args.extracted_dir.glob('*.json')):
        if path.name in {'summary.json', 'results.json'} or path.stem in excluded:
            continue
        extracted = json.loads(path.read_text(encoding='utf-8'))
        meta = prior.get(path.stem, {})
        filename = extracted.get('filename')
        raw = args.raw_dir / filename
        if not raw.is_file():
            raise ValueError(f'RAW_SOURCE_NOT_FOUND: {path.stem}')
        documents.append({
            'source_id': path.stem, 'filename': filename,
            'title': meta.get('title') or Path(filename).stem,
            'source': meta.get('source') or filename,
            'format': extracted.get('format'), 'major': meta.get('major', 'all'),
            'cohort': meta.get('cohort', 'all'),
            'effective_from': meta.get('effective_from'), 'effective_until': meta.get('effective_until'),
            'is_effective_date_verified': False,
            'raw_sha256': file_hash(raw), 'text_sha256': text_hash(extracted['content']),
            'page_count': extracted.get('page_count'), 'warnings': extracted.get('warnings', []),
            'review_state': 'pending_owner_review', 'reviewer': None,
            'title_verified': False, 'source_verified': False,
            'page_coverage_verified': False, 'table_coverage_verified': False,
        })
    payload = {'manifest_version': '2.0.0', 'status': 'pending_owner_review',
               'created_at': datetime.now(timezone.utc).isoformat(), 'reviewed_at': None,
               'owner': None, 'documents': documents, 'manifest_sha256': None}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'document_count': len(documents),
                      'status': payload['status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
