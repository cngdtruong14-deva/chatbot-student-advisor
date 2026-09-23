"""Offline audit/normalization. No database or model writes; new output only."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from advisor_core.academic_policy_v2 import POLICY_VERSION, normalize_attempt, summarize
from ml.scripts.audit_academic_demo import audit

NON_GPA = {'PE101', 'PE201', 'PE301', 'GEN402'}


def prepare(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError('USE_NEW_OUTPUT_OUTSIDE_SOURCE')
    files = sorted(p for p in root.iterdir() if p.is_file())
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    def read(name):
        with (root / (name + '.csv')).open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    offerings = {r['offering_code']: r for r in read('offerings')}
    courses = {r['code']: r['title'] for r in read('courses')}
    source = read('enrollments')
    report = audit(root)
    report['source_dataset_id'] = report.pop('dataset')
    report['dataset_id'] = 'academic_demo_v2'
    report.pop('questions', None)
    report.pop('prediction_time', None)
    report['status'] = 'offline_policy_normalized'
    report['policy_version'] = POLICY_VERSION
    report['credential_file_processed'] = 'users.csv hashed only; never parsed or exported'
    for key in ('duplicate_keys', 'foreign_key_missing'):
        if any(report[key].values()): raise ValueError('STRUCTURAL_AUDIT_FAILED:' + key)
    for key in ('score_errors', 'component_score_errors', 'weight_errors', 'weighted_score_mismatch_above_rounding_tolerance', 'finalized_without_components'):
        if report[key]: raise ValueError('STRUCTURAL_AUDIT_FAILED:' + key)
    grouped, normalized, excluded = defaultdict(list), [], Counter()
    conflicts = []
    for line, row in enumerate(source, start=2):
        offering = offerings[row['offering_code']]
        course = offering['course_code']
        absent = row['final_score'] == ''
        bearing = course not in NON_GPA
        source_flag = row['counts_for_gpa'].lower()
        if source_flag not in ('true', 'false'): raise ValueError('INVALID_GPA_FLAG')
        # Missing-score rows are explicitly reclassified by owner-approved policy.
        if not absent and (source_flag == 'true') != bearing:
            conflicts.append(line)
        if not absent and not bearing and float(row['final_score']) >= 4:
            excluded[course] += 1
        record = normalize_attempt(course=course, attempt=int(row['attempt_no']),
            credits=offering['credits'], score=None if absent else row['final_score'],
            gpa_bearing=bearing, status='absent_or_barred' if absent else 'graded')
        grouped[row['student_code']].append(record)
        normalized.append({**record, 'student_code': row['student_code'],
            'offering_code': row['offering_code'], 'semester_code': offering['semester_code'],
            'source_line': line, 'source_counts_for_gpa': source_flag,
            'source_grade_point': row['grade_point'], 'available_at': row['finalized_at'] or None,
            'absence_reason': 'unspecified_absent_or_barred' if absent else None,
            'data_origin': 'synthetic'})
    if conflicts: raise ValueError('COURSE_GPA_CLASSIFICATION_CONFLICT:' + str(conflicts[:20]))
    summaries = []
    for student in read('students'):
        code = student['student_code']
        value = summarize(grouped[code])
        # Independent float arithmetic and explicit band bins cross-check Decimal engine.
        latest = {}
        for r in grouped[code]:
            if r['course'] not in latest or r['attempt'] > latest[r['course']]['attempt']:
                latest[r['course']] = r
        selected = [r for r in latest.values() if r['gpa_bearing']]
        denominator = sum(float(r['credits']) for r in selected)
        points = lambda x: [0,1,1.5,2,2.5,3,3.5,4][sum(x >= b for b in [4,5,5.5,6.5,7,8,8.5])]
        for field, transform in [('gpa_10', lambda x:x), ('gpa_4', points)]:
            expected = sum(float(r['credits']) * transform(float(r['effective_score_10'])) for r in selected) / denominator if denominator else None
            if expected is None:
                assert value[field] is None
            else:
                assert abs(float(value[field]) - expected) <= .00000051
        summaries.append({'student_code': code, 'data_origin': 'synthetic', **value})
    report.update({'excluded_passes_by_course': dict(excluded),
        'approved_non_gpa_courses': {c:courses[c] for c in sorted(NON_GPA)},
        'normalized_rows': len(normalized), 'student_summaries': len(summaries),
        'independent_gpa_crosscheck': 'PASS',
        'absent_or_barred_rows': sum(r['status']=='absent_or_barred' for r in normalized),
        'absent_or_barred_gpa_bearing': sum(r['status']=='absent_or_barred' and r['gpa_bearing'] for r in normalized),
        'missing_available_at': sum(r['available_at'] is None for r in normalized),
        'superseded_attempts': sum(r['superseded_attempts'] for r in summaries),
        'ready_for_import': False, 'ready_for_training': False,
        'limitations': ['Snapshot GPA only; not historical/semester GPA labels.',
            '145 absence/barred records have no result availability date; temporal ML audit pending.',
            'No inferred dates or individual absent/barred classification.',
            'Full relational import dry-run and ML split/target approval still required.',
            'Runtime DEMO-1 and old model artifacts unchanged.']})
    policy = {'policy_version': POLICY_VERSION, 'data_origin': 'synthetic',
        'authority': 'Owner-approved demo rules, not official university policy',
        'retake_rule': 'latest_resolved_attempt_replaces_previous_even_if_lower',
        'missing_score_rule': 'Only this source snapshot: owner identified null scores as absent_or_barred; effective zero',
        'absence_status': 'incomplete_until_replaced', 'non_gpa_courses': sorted(NON_GPA),
        'pass_score_10': 4, 'non_gpa_rule': 'exclude numerator and denominator; latest outcome must pass',
        'bands_lower_bounds_10': [0,4,5,5.5,6.5,7,8,8.5], 'points_4': [0,1,1.5,2,2.5,3,3.5,4],
        'rounding': 'GPA output 6 decimals HALF_UP; no pre-average rounding',
        'historical_rule': 'Filter true available_at before selecting latest; unknown dates block historical use',
        'graduation': '130=123 mandatory+7 elective; completion certification not implemented by this audit'}
    # Recheck source immutability before producing a new, non-overwriting export.
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    save('source_manifest.json', {'dataset_id':'academic_demo_v2', 'data_origin':'synthetic',
        'files':{p.name:{'sha256':hashes[p.name], 'size_bytes':p.stat().st_size} for p in files},
        'notes':'users.csv hash only; credentials not exported',
        'preparation_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    save('policy.json', policy)
    save('audit.json', report)
    for name, records in [('normalized_enrollments.jsonl', normalized), ('gpa_reconciliation.jsonl', summaries)]:
        with (output/name).open('x', encoding='utf-8') as f:
            for row in records: f.write(json.dumps(row, ensure_ascii=False, default=str)+'\n')
    save('output_manifest.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())})
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source')
    p.add_argument('output')
    args = p.parse_args()
    print(json.dumps(prepare(args.source, args.output), ensure_ascii=True, indent=2))
