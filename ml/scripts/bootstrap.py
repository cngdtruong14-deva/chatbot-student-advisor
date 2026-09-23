"""Run provenance and source safety, no runtime secrets."""
from pathlib import Path
import hashlib
import zipfile
from .common import save,environment,sha


def assert_offline_boundary():
    import os
    forbidden=['DATABASE_URL','DB_PASSWORD','APP_DB_PASSWORD','MIGRATOR_DB_PASSWORD','ADMIN_DB_PASSWORD','JWT_SECRET']
    if any(name in os.environ for name in forbidden):
        raise RuntimeError('RUNTIME_CREDENTIAL_PRESENT: use clean Colab; values deliberately not printed')


def record_environment(repo,work):
    assert_offline_boundary()
    repo,work=Path(repo),Path(work)
    sources={}
    for folder in ['ml','contracts','packages/advisor_core/src']:
        for file in sorted((repo/folder).rglob('*')):
            if file.is_file() and file.suffix in ['.py','.json','.jsonl','.md','.txt','.ipynb']:
                sources[str(file.relative_to(repo)).replace('\\','/')]=sha(file)
    source_manifest = repo/'SOURCE_MANIFEST.json'
    provenance = {'source_kind':'unverified_source_tree'}
    if source_manifest.exists():
        provenance = __import__('json').loads(source_manifest.read_text(encoding='utf-8'))
    record={'environment':environment(),'source_files':sources,
      'source_tree_sha256':hashlib.sha256(str(sorted(sources.items())).encode()).hexdigest(),
      'source_provenance':provenance,
      'git_commit_status':'must be pinned and approved before training/export'}
    save(work/'environment.json',record)
    return record
