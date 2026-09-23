"""Receive the owner-provided final-002 ZIP without deserializing any model."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

archive=Path(sys.argv[1])
root=Path(__file__).resolve().parents[1]/'artifacts'/'approved'
expected='6e705e96a96da6223ede29070104defddcd4fd98fe59c8997e8e92684540085d'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise ValueError('HANDOFF_HASH_MISMATCH')
with zipfile.ZipFile(archive) as z:
    prefix='final-002/'
    manifest_bytes=z.read(prefix+'manifest.json')
    manifest=json.loads(manifest_bytes)
    content={'manifest.json':manifest_bytes}
    for name,meta in manifest['files'].items():
        if Path(name).name!=name or ':' in name or '\\' in name:raise ValueError('UNSAFE_PATH')
        value=z.read(prefix+name)
        if len(value)!=meta['size_bytes'] or hashlib.sha256(value).hexdigest()!=meta['sha256']:raise ValueError('ARTIFACT_HASH_MISMATCH')
        content[name]=value
    target=root/'final-002'
    if target.exists():
        if any(not (target/name).is_file() or (target/name).read_bytes()!=value for name,value in content.items()):raise ValueError('EXISTING_BUNDLE_DIFFERS')
    else:
        target.mkdir(parents=True)
        for name,value in content.items():
            with (target/name).open('xb') as stream:stream.write(value)
    receipt={'approved':True,'owner':'Doan Truong','bundle_directory':'final-002','manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest()}
    path=root/'active.json'
    if path.exists():
        if json.loads(path.read_text())!=receipt:raise ValueError('ACTIVE_RECEIPT_CONFLICT')
    else:
        with path.open('x',encoding='utf-8') as stream:json.dump(receipt,stream,indent=2)
print('PASS: handoff SHA256 and 9 files verified; received immutable final-002. Activation still requires smoke parity.')
