"""Generate the owner-operated Academic Demo v2 Colab training notebook."""
import json
from pathlib import Path


def cell(kind, source):
    return {"cell_type": kind, "metadata": {}, "source": [line + "\n" for line in source.splitlines()]}


def create_notebook():
    cells = [
        cell("markdown", """# Academic Demo v2 — Colab train, test and export

This notebook trains a **synthetic** day-28 course non-completion/failure-risk model. It is not a numeric grade predictor and it must not be used on real student profiles.

The notebook requires two uploads:

1. A clean committed source archive made with `ml/scripts/Pack-ColabSource.ps1`.
2. A ZIP containing the approved synthetic release folder `academic_demo_v2_audit_20260909_r2`, including `normalized_enrollments.jsonl` and `output_manifest.json`.

It creates a new immutable run directory, then exports audit, approvals, splits, metrics, report tables and a backend-compatible bundle. Do not rerun a final test inside an existing run directory."""),
        cell("code", """from pathlib import Path
import hashlib, json, shutil, subprocess, sys, zipfile

from google.colab import files

BASE = Path('/content')
REPO = BASE / 'student-advisor'
WORK = BASE / 'academic-demo-v2-work'
WORK.mkdir(exist_ok=True)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            assert target.is_relative_to(destination), 'Unsafe ZIP path'
            # ZIP symlink bit: never accept links from an uploaded archive.
            assert (member.external_attr >> 16) & 0o170000 != 0o120000, 'ZIP symlink rejected'
        package.extractall(destination)

print('Upload ONE clean source archive created by Pack-ColabSource.ps1')
uploaded = files.upload()
assert len(uploaded) == 1, 'Upload exactly one source archive in this cell.'
SOURCE_ZIP = BASE / next(iter(uploaded))
assert SOURCE_ZIP.suffix.lower() == '.zip', 'Expected a ZIP source archive.'
if REPO.exists():
    raise RuntimeError('Fresh runtime required: /content/student-advisor already exists.')
safe_extract(SOURCE_ZIP, REPO)

source_manifest = json.loads((REPO / 'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
assert source_manifest.get('source_kind') == 'clean_git_commit_source_archive'
SOURCE_COMMIT = source_manifest.get('source_commit')
assert isinstance(SOURCE_COMMIT, str) and len(SOURCE_COMMIT) == 40
for relative, expected_sha in source_manifest['files'].items():
    candidate = (REPO / relative).resolve()
    assert candidate.is_relative_to(REPO.resolve()) and candidate.is_file(), f'Missing source file: {relative}'
    assert sha(candidate) == expected_sha, f'Source hash mismatch: {relative}'
print('Clean source verified:', SOURCE_COMMIT)
"""),
        cell("code", """assert sys.version_info[:2] == (3, 13), 'Use Colab Python 3.13 to match the backend runtime.'
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(REPO / 'ml/requirements-colab.txt')], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', str(REPO / 'packages/advisor_core')], check=True)
sys.path.insert(0, str(REPO))
print('Python:', sys.version.split()[0])
"""),
        cell("code", """print('Upload ONE ZIP of academic_demo_v2_audit_20260909_r2')
uploaded = files.upload()
assert len(uploaded) == 1, 'Upload exactly one dataset-release ZIP in this cell.'
RELEASE_ZIP = BASE / next(iter(uploaded))
assert RELEASE_ZIP.suffix.lower() == '.zip', 'Expected a dataset-release ZIP.'
RELEASE_ROOT = WORK / 'release'
if RELEASE_ROOT.exists():
    raise RuntimeError('Fresh runtime required: release folder already exists.')
safe_extract(RELEASE_ZIP, RELEASE_ROOT)
normalized = list(RELEASE_ROOT.rglob('normalized_enrollments.jsonl'))
manifests = list(RELEASE_ROOT.rglob('output_manifest.json'))
assert len(normalized) == 1 and len(manifests) == 1, 'Release must contain one normalized data file and one output manifest.'
NORMALIZED = normalized[0]
release_manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
assert release_manifest['normalized_enrollments.jsonl'] == sha(NORMALIZED), 'Normalized release hash mismatch.'
print('Synthetic release verified:', NORMALIZED.name, sha(NORMALIZED), NORMALIZED.stat().st_size, 'bytes')
"""),
        cell("code", """from datetime import datetime, timezone
from ml.scripts.build_academic_demo_v2_events import build as build_events

RUN_ID = 'academic-demo-v2-colab-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
RUN_ROOT = WORK / 'runs' / RUN_ID
PREVIEW_ROOT = WORK / 'preflight' / RUN_ID
assert not RUN_ROOT.exists() and not PREVIEW_ROOT.exists(), 'Run path exists: choose a new runtime/run id.'

# Deterministic preflight lets the owner inspect source counts before authorizing training.
preview = build_events(NORMALIZED, PREVIEW_ROOT / 'processed', seed=20260912)
preview_audit = PREVIEW_ROOT / 'processed' / 'audit.json'
approval_template = {
    'approved': False, 'owner': '', 'audit_sha256': sha(preview_audit),
    'domain_id': 'academic_demo_v2', 'data_origin': 'synthetic',
    'target_id': 'non_completion_at_end', 'cutoff_day': 28,
    'approval_context': 'Review the synthetic source, target and cutoff before training.'
}
(PREVIEW_ROOT / 'approval.template.json').write_text(json.dumps(approval_template, indent=2), encoding='utf-8')
print(json.dumps(preview, indent=2))
print('Review:', PREVIEW_ROOT / 'processed' / 'audit.json')
print('Approval template:', PREVIEW_ROOT / 'approval.template.json')
"""),
        cell("markdown", """## Owner gate

Open the two preflight files above. Confirm that the data is synthetic, the target is `non_completion_at_end`, the cutoff is day 28, and the split/event assumptions are appropriate. Only then change both flags in the next cell to `True`.

That invocation performs model selection on dev, freezes selection, and evaluates test exactly once inside its new run directory."""),
        cell("code", """OWNER = 'cngdt-owner'
OWNER_APPROVES_DATASET = False
OWNER_APPROVES_FINAL_TEST = False

MODEL_VERSION = 'academic-demo-v2-risk-colab-' + RUN_ID.rsplit('-', 1)[-1].lower()
BUNDLE_DIRECTORY = 'academic-demo-v2-risk-colab-' + RUN_ID.rsplit('-', 1)[-1].lower()

if OWNER_APPROVES_DATASET and OWNER_APPROVES_FINAL_TEST:
    command = [
        sys.executable, str(REPO / 'ml/scripts/govern_academic_demo_v2_artifact.py'),
        str(NORMALIZED), str(REPO), str(RUN_ROOT),
        '--owner', OWNER,
        '--source-commit', SOURCE_COMMIT,
        '--model-version', MODEL_VERSION,
        '--bundle-directory', BUNDLE_DIRECTORY,
    ]
    subprocess.run(command, check=True)
    print('Governed training/final test complete:', RUN_ROOT)
else:
    print('STOP: review preflight output, then set both approval flags to True.')
"""),
        cell("code", """assert (RUN_ROOT / 'run_report.json').is_file(), 'Run the approved training cell once first.'
report = json.loads((RUN_ROOT / 'run_report.json').read_text(encoding='utf-8'))
final = json.loads((RUN_ROOT / 'run' / 'final_metrics.json').read_text(encoding='utf-8'))
print('Selected:', report['selected_model'])
print('Final AP:', final['average_precision'])
print('Final threshold:', final['threshold'])
print('Report tables:')
for path in sorted((RUN_ROOT / 'report_tables').iterdir()):
    print('-', path.name)
"""),
        cell("markdown", """## Export

The ZIP contains the audit and approvals, processed split manifest, train/dev comparison, final metrics, report tables, bundle and activation receipt. Download it, inspect it locally, and only then place its `bundle/` plus reviewed receipt into the backend artifact directory. The notebook never activates a backend model by itself."""),
        cell("code", """EXPORT_HANDOFF = False
if EXPORT_HANDOFF:
    archive_base = BASE / f'{RUN_ID}-handoff'
    archive = shutil.make_archive(str(archive_base), 'zip', root_dir=RUN_ROOT)
    print('Created:', archive, 'sha256:', sha(archive))
    files.download(archive)
else:
    print('Set EXPORT_HANDOFF=True after reviewing final metrics and artifact files.')
"""),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    target = Path(__file__).resolve().parents[1] / "notebooks" / "09_academic_demo_v2_train_and_export.ipynb"
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    create_notebook()
