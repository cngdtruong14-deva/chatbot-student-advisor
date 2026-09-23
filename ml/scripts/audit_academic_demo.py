"""Read-only preflight for the academic demo; never reads account credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd


def audit(directory):
    root = Path(directory)
    names = ['students', 'cohorts', 'courses', 'curricula', 'curriculum_courses',
             'semesters', 'offerings', 'prerequisites', 'enrollments',
             'grade_components', 'grade_component_scores']
    tables = {name: pd.read_csv(root / (name + '.csv')) for name in names}
    e, o, c, g = (tables[x] for x in ['enrollments', 'offerings', 'grade_components', 'grade_component_scores'])
    keys = {
        'students': ['student_code'], 'cohorts': ['code'], 'courses': ['code'],
        'curricula': ['code', 'version'], 'curriculum_courses': ['curriculum_code', 'course_code'],
        'semesters': ['code'], 'offerings': ['offering_code'],
        'prerequisites': ['curriculum_code', 'course_code', 'prerequisite_course_code'],
        'enrollments': ['student_code', 'offering_code'],
        'grade_components': ['offering_code', 'component_code'],
        'grade_component_scores': ['student_code', 'offering_code', 'component_code']}
    duplicates = {name: int(tables[name].duplicated(key).sum()) for name, key in keys.items()}
    report = {'dataset': 'academic_demo_v1', 'data_origin': 'synthetic',
              'source_sha256': {name: hashlib.sha256((root / (name + '.csv')).read_bytes()).hexdigest() for name in names},
              'rows': {name: len(frame) for name, frame in tables.items()},
              'duplicate_keys': duplicates, 'credential_file_processed': False,
              'prediction_time': 'semester_start', 'ready_for_import': False,
              'ready_for_training': False, 'questions': [
                  'Confirm retake policy and meaning of counts_for_gpa=false.',
                  'Define pending/pass-fail/exempt status for missing or excluded scores.',
                  'Confirm elective requirement: 123 mandatory plus 7 elective credits.',
                  'Outcome is course failure unless withdrawal status is explicitly supplied.']}
    if any(duplicates.values()):
        report['status'] = 'duplicate_keys_blocked'
        return report
    def missing(left, right, left_keys, right_keys):
        target = right[right_keys].drop_duplicates().copy()
        target.columns = left_keys
        joined = left.merge(target, on=left_keys, how='left', indicator=True)
        return int(joined['_merge'].eq('left_only').sum())
    report['foreign_key_missing'] = {
        'enrollment_student': missing(e, tables['students'], ['student_code'], ['student_code']),
        'enrollment_offering': missing(e, o, ['offering_code'], ['offering_code']),
        'offering_course': missing(o, tables['courses'], ['course_code'], ['code']),
        'offering_semester': missing(o, tables['semesters'], ['semester_code'], ['code']),
        'score_component': missing(g, c, ['offering_code', 'component_code'], ['offering_code', 'component_code']),
        'score_enrollment': missing(g, e, ['student_code', 'offering_code'], ['student_code', 'offering_code'])}
    cc = tables['curriculum_courses']
    required = cc['required'].astype(str).str.lower().isin(['true', '1'])
    report['credits'] = {'catalog': float(cc.credits.sum()), 'mandatory': float(cc.loc[required].credits.sum()),
                         'declared_total': tables['curricula'].total_required_credits.tolist()}
    report['weight_errors'] = int((c.groupby('offering_code').weight.sum().round(6) != 1).sum())
    merged = g.merge(c, on=['offering_code', 'component_code'], validate='many_to_one')
    merged['weighted'] = merged.score * merged.weight
    totals = merged.groupby(['student_code', 'offering_code']).weighted.sum().reset_index()
    result = e.merge(totals, on=['student_code', 'offering_code'], how='left', validate='one_to_one')
    report['score_errors'] = int((e.final_score.notna() & ~e.final_score.between(0, 10)).sum())
    report['component_score_errors'] = int((g.score.isna() | ~g.score.between(0, 10)).sum())
    report['weighted_score_mismatch_above_rounding_tolerance'] = int(((result.final_score-result.weighted).abs() > .050001).sum())
    report['finalized_without_components'] = int((result.final_score.notna() & result.weighted.isna()).sum())
    report['missing_final_score'] = int(e.final_score.isna().sum())
    report['gpa_linear_conversion_mismatch'] = int(((e.final_score * .4 - e.grade_point).abs() > .000001).sum())
    report['excluded_graded_passes'] = int((e.final_score.ge(4) & e.grade_point.eq(0) & e.counts_for_gpa.astype(str).str.lower().eq('false')).sum())
    report['status'] = 'awaiting_policy_semantics'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), ensure_ascii=False, indent=2))
