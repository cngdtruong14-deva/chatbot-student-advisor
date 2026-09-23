"""Read-only verifier for the owner-approved ACADEMIC-DEMO-2 data release.

The release is intentionally stored outside the repository: it contains a
large normalized snapshot and must not be committed with application code.
This utility validates its manifest before comparing the running database.
"""
import argparse
import hashlib
import json
from pathlib import Path

from app.api import transcript
from app.store import transaction, one, rows
from advisor_core.academic_policy_v2 import POLICY_VERSION, transcript_summary


REQUIRED_FILES = frozenset({'audit.json', 'gpa_reconciliation.jsonl',
                            'normalized_enrollments.jsonl', 'policy.json',
                            'source_manifest.json'})


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_release_files(root):
    root = Path(root).resolve(strict=True)
    manifest = load_json(root / 'output_manifest.json')
    if set(manifest) != REQUIRED_FILES:
        raise ValueError('RELEASE_MANIFEST_FILE_SET_MISMATCH')
    for name, expected in manifest.items():
        if sha256(root / name) != expected:
            raise ValueError(f'RELEASE_HASH_MISMATCH:{name}')
    audit, policy = load_json(root / 'audit.json'), load_json(root / 'policy.json')
    if audit.get('dataset_id') != 'academic_demo_v2' or audit.get('policy_version') != POLICY_VERSION:
        raise ValueError('RELEASE_ID_OR_POLICY_MISMATCH')
    if policy.get('policy_version') != POLICY_VERSION or policy.get('data_origin') != 'synthetic':
        raise ValueError('RELEASE_POLICY_MISMATCH')
    return {'root': str(root), 'manifest_sha256': sha256(root / 'output_manifest.json'),
            'audit': audit, 'policy': policy}


def expected_summaries(path):
    result = {}
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            item = json.loads(line)
            code = item['student_code']
            if code in result:
                raise ValueError(f'DUPLICATE_RECONCILIATION_STUDENT:{code}')
            result[code] = item
    return result


def verify_database(release):
    audit = release['audit']
    expected_counts = audit['rows']
    expected = expected_summaries(Path(release['root']) / 'gpa_reconciliation.jsonl')
    mismatches = []
    with transaction() as db:
        actual_counts = {
            'students': one(db, 'SELECT count(*) AS n FROM app.students')['n'],
            'courses': one(db, 'SELECT count(*) AS n FROM app.courses')['n'],
            'offerings': one(db, 'SELECT count(*) AS n FROM app.course_offerings')['n'],
            'enrollments': one(db, 'SELECT count(*) AS n FROM app.enrollments')['n'],
            'grade_component_scores': one(db, 'SELECT count(*) AS n FROM app.grade_components')['n'],
        }
        count_fields = {'students': 'students', 'courses': 'courses', 'offerings': 'offerings',
                        'enrollments': 'enrollments', 'grade_component_scores': 'grade_component_scores'}
        for actual_name, audit_name in count_fields.items():
            if actual_counts[actual_name] != expected_counts[audit_name]:
                mismatches.append(f'COUNT:{actual_name}:{actual_counts[actual_name]}')
        policy = one(db, "SELECT p.code,p.version FROM app.curricula c JOIN app.grading_policies p ON p.id=c.policy_id LIMIT 1")
        if policy != {'code': 'ACADEMIC-DEMO-2', 'version': '2.0.0'}:
            mismatches.append('ACTIVE_POLICY_MISMATCH')
        students = rows(db, 'SELECT * FROM app.students ORDER BY student_code')
        if len(students) != len(expected):
            mismatches.append('RECONCILIATION_POPULATION_MISMATCH')
        for student in students:
            actual = transcript_summary(transcript(db, student))
            wanted = expected.get(student['student_code'])
            if not wanted:
                mismatches.append(f'UNEXPECTED_STUDENT:{student["student_code"]}')
            elif any(actual[field] != wanted[field] for field in ('gpa_10', 'gpa_4', 'gpa_credits', 'quality_points_10', 'quality_points_4', 'selected_courses', 'superseded_attempts', 'incomplete_courses', 'non_gpa_incomplete_courses')):
                mismatches.append(f'SUMMARY:{student["student_code"]}')
            if len(mismatches) >= 20:
                break
    return {'status': 'PASS' if not mismatches else 'FAIL', 'release_manifest_sha256': release['manifest_sha256'],
            'expected_counts': {key: expected_counts[key] for key in count_fields.values()},
            'actual_counts': actual_counts, 'students_compared': len(expected), 'mismatch_samples': mismatches}


def main():
    parser = argparse.ArgumentParser(description='Read-only Academic Demo v2 release verifier')
    parser.add_argument('release_root')
    args = parser.parse_args()
    print(json.dumps(verify_database(verify_release_files(args.release_root)), ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    main()
