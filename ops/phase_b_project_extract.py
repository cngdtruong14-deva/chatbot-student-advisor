"""Run the existing application extractor unchanged, offline and bounded per file."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(repo, out):
    repo, out = Path(repo).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    manifest = repo / 'artifacts/phase_b/source_manifest.jsonl'
    sources = [json.loads(s) for s in manifest.read_text(encoding='utf-8').splitlines() if s.strip()]
    exclusions_path = repo / 'artifacts/phase_b/owner_exclusions_batch01.json'
    exclusions = json.loads(exclusions_path.read_text(encoding='utf-8'))
    if digest(manifest) != exclusions['source_manifest_sha256']:
        raise ValueError('SOURCE_MANIFEST_CHANGED')
    excluded = set(exclusions['source_ids'])
    worker = '''import json,sys
from pathlib import Path
repo_dir = Path(sys.argv[2])
sys.path.insert(0, str(repo_dir / 'backend'))
from app.document_extract import extract_document
p=Path(sys.argv[1])
try:
 r=extract_document(p.name,p.read_bytes())
 print(json.dumps({'result':r},ensure_ascii=False))
except Exception as e:
 print(json.dumps({'error':type(e).__name__+': '+str(e)}))
'''
    records = []
    for source in sources:
        sid = source['source_id']
        raw = (repo / source['internal_path']).resolve()
        if not raw.is_relative_to(repo) or digest(raw) != source['raw_sha256']:
            raise ValueError('RAW_HASH_OR_PATH_MISMATCH')
        row = dict(source_id=sid, title=source['title'], raw_sha256=source['raw_sha256'])
        if sid in excluded or raw.suffix.lower() == '.xlsx':
            row.update(status='excluded', reason='OWNER_TEMPORARY_EXCLUSION')
        else:
            try:
                p = subprocess.run([sys.executable, '-B', '-c', worker, str(raw), str(repo)],
                                   capture_output=True, text=True, timeout=240)
                data = json.loads(p.stdout) if p.returncode == 0 else {'error': 'WORKER_EXIT_NONZERO'}
                if 'error' in data:
                    row.update(status='excluded', reason=data['error'])
                else:
                    result = data['result']
                    locators = [int(n) for n in re.findall(r'^## Trang (\d+)\s*$', result['content'], re.M)]
                    missing = sorted(set(range(1, (result['page_count'] or 0) + 1)) - set(locators))
                    if result['format'] == 'pdf' and missing:
                        row.update(status='excluded', reason='INCOMPLETE_PAGE_COVERAGE', missing_pages=missing)
                    else:
                        dest = out / (sid + '.json')
                        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                        row.update(status='extracted_pending_quality_review', output_file=dest.name,
                                   output_sha256=digest(dest), page_count=result['page_count'],
                                   character_count=result['character_count'], warnings=result['warnings'])
            except subprocess.TimeoutExpired:
                row.update(status='excluded', reason='PROJECT_EXTRACTOR_FILE_TIMEOUT_240S')
            except (ValueError, OSError) as error:
                row.update(status='excluded', reason='WORKER_PROTOCOL_ERROR:' + type(error).__name__)
        records.append(row)
        print(f'{len(records)}/{len(sources)} {sid} {row["status"]}', flush=True)
        (out/'results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = {s: sum(r['status'] == s for r in records) for s in sorted({r['status'] for r in records})}
    report = {'counts': counts, 'source_manifest_sha256': digest(manifest),
              'extractor_sha256': digest(repo/'backend/app/document_extract.py'),
              'exclusion_decisions_sha256': digest(exclusions_path),
              'scope': 'offline project extractor only; no live ingestion or release approval',
              'limitations': ['Successful extraction is not human quality approval.',
                              'Missing pages excluded conservatively, including potentially blank pages.',
                              'DOCX paragraph/table interleaving not guaranteed by current extractor.']}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    main(a.repo, a.out)
