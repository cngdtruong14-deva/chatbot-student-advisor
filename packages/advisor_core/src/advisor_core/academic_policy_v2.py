"""Offline candidate policy; never changes the running DEMO-1 service."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from .academic_demo_policy import grade_point

POLICY_VERSION = 'ACADEMIC-DEMO-2.0.0'
NON_GPA_COURSES = frozenset({'PE101', 'PE201', 'PE301', 'GEN402'})
REQUIRED_CREDITS = Decimal('130')


def normalize_attempt(*, course, attempt, credits, score, gpa_bearing, status):
    if not course or isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError('INVALID_ATTEMPT')
    credit = Decimal(str(credits))
    if not credit.is_finite() or credit <= 0 or not isinstance(gpa_bearing, bool):
        raise ValueError('INVALID_CREDITS_OR_CLASSIFICATION')
    if status not in ('graded', 'absent_or_barred'):
        raise ValueError('UNRESOLVED_STATUS')
    if status == 'absent_or_barred':
        if score is not None:
            raise ValueError('CONFLICTING_ABSENCE_SCORE')
        value = Decimal(0)
    else:
        if score is None:
            raise ValueError('MISSING_GRADED_SCORE')
        value = Decimal(str(score))
    point = grade_point(value)
    return {'course': course, 'attempt': attempt, 'credits': credit,
            'source_score': score, 'effective_score_10': value,
            'effective_score_4': point, 'gpa_bearing': gpa_bearing,
            'status': status, 'completed': value >= 4,
            'policy_version': POLICY_VERSION}


def summarize(attempts):
    """Latest resolved attempt replaces earlier attempts, even if its score is lower.

    Caller must filter by genuine availability time before historical/ML use.
    Missing availability times cannot be silently filled with semester dates.
    """
    latest, seen = {}, set()
    for row in attempts:
        code, number = row['course'], row['attempt']
        if (code, number) in seen:
            raise ValueError('DUPLICATE_ATTEMPT')
        seen.add((code, number))
        if code in latest and (latest[code]['credits'], latest[code]['gpa_bearing']) != (row['credits'], row['gpa_bearing']):
            raise ValueError('INCONSISTENT_COURSE_POLICY')
        if code not in latest or number > latest[code]['attempt']:
            latest[code] = row
    eligible = [r for r in latest.values() if r['gpa_bearing']]
    credits = sum((r['credits'] for r in eligible), Decimal(0))
    q10 = sum((r['credits'] * r['effective_score_10'] for r in eligible), Decimal(0))
    q4 = sum((r['credits'] * r['effective_score_4'] for r in eligible), Decimal(0))
    wire = lambda v: format(v.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP), 'f')
    return {'policy_version': POLICY_VERSION, 'gpa_10': wire(q10 / credits) if credits else None,
            'gpa_4': wire(q4 / credits) if credits else None, 'gpa_credits': wire(credits),
            'quality_points_10': wire(q10), 'quality_points_4': wire(q4),
            'earned_credits': wire(sum((r['credits'] for r in latest.values() if r['completed']), Decimal(0))),
            'selected_courses': len(latest), 'superseded_attempts': len(seen)-len(latest),
            'incomplete_courses': sorted(c for c,r in latest.items() if not r['completed']),
            'non_gpa_incomplete_courses': sorted(c for c,r in latest.items() if not r['gpa_bearing'] and not r['completed'])}


def required_gpa(summary, target_gpa, future_gpa_credits):
    """Project only new GPA-bearing credits on the 4-point scale.

    A projected 4-point GPA cannot truthfully imply a projected 10-point GPA,
    because the v2 conversion is course-banded rather than linear.
    """
    target = Decimal(str(target_gpa))
    future = Decimal(str(future_gpa_credits))
    if not target.is_finite() or not Decimal(0) <= target <= Decimal(4):
        raise ValueError('INVALID_TARGET_GPA')
    if not future.is_finite() or future < 0:
        raise ValueError('INVALID_FUTURE_GPA_CREDITS')
    qp, credits = Decimal(summary['quality_points_4']), Decimal(summary['gpa_credits'])
    current = qp / credits if credits else None
    required = (target * (credits + future) - qp) / future if future else None
    feasibility = ('impossible' if required > 4 else 'achievable') if required is not None else (
        'insufficient_data' if current is None else 'completed_target_met' if current >= target else 'completed_target_not_met')
    wire = lambda value: format(value.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP), 'f')
    return {'current_gpa': wire(current) if current is not None else None, 'target_gpa': wire(target),
            'gap': wire(target-current) if current is not None else None,
            'required_future_gpa': wire(max(Decimal(0), required)) if required is not None else None,
            'feasibility': feasibility, 'gpa_scale_max': '4.000000', 'policy_version': POLICY_VERSION,
            'data_origin': 'synthetic', 'assumptions': [
                'Projection is on the 4-point scale only.',
                'Only future GPA-bearing credits are added; no retake score is replaced.'
            ]}


def project_gpa_4(summary, assumed_gpa, future_gpa_credits):
    """Project new GPA-bearing credits without mutating the transcript.

    The projection intentionally stays on the 4-point scale: a letter/term GPA
    does not provide enough information to derive a truthful 10-point GPA.
    """
    assumed = Decimal(str(assumed_gpa))
    future = Decimal(str(future_gpa_credits))
    if not assumed.is_finite() or not Decimal(0) <= assumed <= Decimal(4):
        raise ValueError('INVALID_ASSUMED_GPA')
    if not future.is_finite() or future <= 0:
        raise ValueError('INVALID_FUTURE_GPA_CREDITS')
    quality_points = Decimal(summary['quality_points_4'])
    current_credits = Decimal(summary['gpa_credits'])
    projected_credits = current_credits + future
    projected_points = quality_points + assumed * future
    wire = lambda value: format(value.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP), 'f')
    return {
        'current_gpa': wire(quality_points / current_credits) if current_credits else None,
        'projected_gpa': wire(projected_points / projected_credits),
        'assumed_gpa': wire(assumed),
        'future_gpa_credits': wire(future),
        'projected_gpa_credits': wire(projected_credits),
        'projected_quality_points_4': wire(projected_points),
        'projection_scale': '4.000000',
        'policy_version': POLICY_VERSION,
        'assumptions': [
            'Only future GPA-bearing credits are added.',
            'The transcript is not changed.',
            'A projected 10-point GPA is not inferred from a 4-point average.',
        ],
    }


def preview_attempts(rows):
    """Preview v2 rows without mutating a transcript or accepting a policy bypass."""
    attempts = [normalize_attempt(course=row['course'], attempt=int(row['attempt']), credits=row['credits'],
                                  score=row.get('score'), gpa_bearing=row.get('gpa_bearing', row['course'] not in NON_GPA_COURSES),
                                  status=row.get('status', 'graded')) for row in rows]
    return summarize(attempts)


def semester_history(rows):
    """Conservative v2 snapshots using only source-provided finalization dates.

    Records without ``finalized_at`` are never assigned an invented date.  Each
    snapshot therefore exposes coverage rather than claiming a complete term
    history when an absence/barred result has unknown availability.
    """
    def as_date(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    ordered_terms = {}
    for row in rows:
        end = as_date(row.get('end_date'))
        if end is None:
            raise ValueError('MISSING_SEMESTER_END_DATE')
        ordered_terms.setdefault((end, str(row.get('semester_id'))), row)
    history = []
    for (end, semester_id), representative in sorted(ordered_terms.items()):
        available = [row for row in rows if (as_date(row.get('finalized_at')) is not None and
                     as_date(row.get('finalized_at')) <= end)]
        term_rows = [row for row in available if str(row.get('semester_id')) == semester_id]
        prior_scope = [row for row in rows if as_date(row.get('end_date')) <= end]
        unknown = [row for row in prior_scope if as_date(row.get('finalized_at')) is None]
        term = transcript_summary(term_rows) if term_rows else None
        cumulative = transcript_summary(available) if available else None
        history.append({'semester_id': semester_id, 'semester_code': representative.get('semester_code'),
                        'term_gpa': term['gpa_4'] if term else None,
                        'term_credits': term['gpa_credits'] if term else '0.000000',
                        'term_earned_credits': term['earned_credits'] if term else '0.000000',
                        'cumulative_gpa': cumulative['gpa_4'] if cumulative else None,
                        'cumulative_earned_credits': cumulative['earned_credits'] if cumulative else '0.000000',
                        'snapshot_rule': 'only_source_finalized_at_on_or_before_semester_end',
                        'availability_coverage': {'available_rows': len(available), 'unknown_rows_in_scope': len(unknown),
                                                   'state': 'partial' if unknown else 'complete'}})
    return history


def transcript_summary(rows):
    attempts = []
    for row in rows:
        status = row['status']
        attempts.append(normalize_attempt(course=row['code'], attempt=int(row['attempt_no']),
            credits=row['credits'], score=row['final_score'] if status == 'graded' else None,
            gpa_bearing=row.get('counts_for_gpa', row['code'] not in NON_GPA_COURSES),
            status='graded' if status == 'graded' else 'absent_or_barred'))
    result = summarize(attempts)
    remaining = max(Decimal(0), REQUIRED_CREDITS - Decimal(result['earned_credits']))
    wire = lambda value: format(value.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP), 'f')
    return {'quality_points':result['quality_points_4'], 'gpa_credits':result['gpa_credits'],
            'cumulative_gpa':result['gpa_4'], 'earned_credits':result['earned_credits'],
            'required_credits':'130.000000', 'remaining_required_credits':wire(remaining),
            'failed_course_codes':result['incomplete_courses'], 'policy_version':POLICY_VERSION,
            'data_origin':'synthetic', 'gpa_scale':'4.000000', 'gpa_10':result['gpa_10'],
            'gpa_4':result['gpa_4'], 'quality_points_10':result['quality_points_10'],
            'quality_points_4':result['quality_points_4'], 'selected_courses':result['selected_courses'],
            'superseded_attempts':result['superseded_attempts'], 'incomplete_courses':result['incomplete_courses'],
            'non_gpa_incomplete_courses':result['non_gpa_incomplete_courses'], 'assumptions':['Latest attempt replaces earlier attempt.',
              'PE and defence-security courses do not count toward GPA.',
              'Incomplete source rows are owner-classified absent/barred with effective score 0.']}
