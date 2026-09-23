"""POL-01 candidate pure primitives. Activation requires explicit retake semantics.

Score bands match the supplied demo data. These functions never reinterpret
counts_for_gpa or mutate existing DEMO-1 policy.
"""
from decimal import Decimal, ROUND_HALF_UP

BANDS = ((Decimal('8.5'), Decimal('4')), (Decimal('8'), Decimal('3.5')),
         (Decimal('7'), Decimal('3')), (Decimal('6.5'), Decimal('2.5')),
         (Decimal('5.5'), Decimal('2')), (Decimal('5'), Decimal('1.5')),
         (Decimal('4'), Decimal('1')), (Decimal('0'), Decimal('0')))


def grade_point(score):
    value = Decimal(str(score))
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(10):
        raise ValueError('INVALID_SCORE')
    return next(point for lower, point in BANDS if value >= lower)


def weighted_final(components):
    if not components:
        raise ValueError('MISSING_COMPONENTS')
    total = Decimal(0)
    weights = Decimal(0)
    for component in components:
        score = Decimal(str(component['score']))
        weight = Decimal(str(component['weight']))
        if not score.is_finite() or not weight.is_finite() or not 0 <= score <= 10 or not 0 < weight <= 1:
            raise ValueError('INVALID_COMPONENT')
        weights += weight
        total += score * weight
    if weights != 1:
        raise ValueError('INVALID_WEIGHTS')
    return total.quantize(Decimal('.1'), rounding=ROUND_HALF_UP)


def dual_gpa(courses):
    """Explicit preview: highest score per course; all supplied rows GPA-bearing.

    Not an importer: source counts_for_gpa flags require resolved semantics.
    """
    best = {}
    attempts = set()
    for item in courses:
        code = str(item['code']).strip().upper()
        score, credits = Decimal(str(item['score'])), Decimal(str(item['credits']))
        grade_point(score)
        if not code or not credits.is_finite() or credits <= 0:
            raise ValueError('INVALID_CREDITS')
        attempt = int(item['attempt'])
        if attempt <= 0 or (code, attempt) in attempts:
            raise ValueError('INVALID_ATTEMPT')
        attempts.add((code, attempt))
        if code in best and credits != best[code][1]:
            raise ValueError('INCONSISTENT_CREDITS')
        if code not in best or score > best[code][0]:
            best[code] = (score, credits)
    credits = sum((credit for score, credit in best.values()), Decimal(0))
    total10 = sum((score * credit for score, credit in best.values()), Decimal(0))
    total4 = sum((grade_point(score) * credit for score, credit in best.values()), Decimal(0))
    wire = lambda v: format(v.quantize(Decimal('.000001'), rounding=ROUND_HALF_UP), 'f')
    return {'gpa_10': wire(total10 / credits) if credits else None,
            'gpa_4': wire(total4 / credits) if credits else None,
            'quality_points_4': wire(total4), 'gpa_credits': wire(credits),
            'earned_credits': wire(sum((credit for score, credit in best.values() if score >= 4), Decimal(0))),
            'policy_version': 'POL-01-demo', 'retake_rule': 'highest_score',
            'assumptions': ['Mọi môn được nhập đều tính GPA; cùng mã môn lấy điểm cao nhất.',
                            'GPA thang 4 tính từ điểm quy đổi từng môn, không quy đổi GPA thang 10.']}
