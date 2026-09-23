"""Pure DEMO-1 revision 1 rules. Never use these as institutional policy."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

D = Decimal
POLICY = "DEMO-1"


def decimal(value, low=None, high=None):
    try:
        result = D(str(value))
        if not result.is_finite() or result.as_tuple().exponent < -6:
            raise ValueError()
        if low is not None and result < D(str(low)) or high is not None and result > D(str(high)):
            raise ValueError()
        return result
    except Exception as exc:
        raise ValueError("INVALID_GRADE") from exc


def wire(value):
    return None if value is None else format(value.quantize(D(".000001"), rounding=ROUND_HALF_UP), "f")


def summary(rows, *, raw=False):
    selected, earned = {}, {}
    for row in rows:
        status = row["status"]
        if status not in {"graded", "pending", "incomplete", "withdrawn", "exempt", "P", "F"}:
            raise ValueError("INVALID_STATUS")
        credits = decimal(row["credits"], 0)
        if credits <= 0:
            raise ValueError("INVALID_CREDITS")
        course = row["course_id"]
        if status == "P" or status == "exempt" and row.get("recognized", False):
            earned[course] = credits
        if status != "graded":
            continue
        score = decimal(row["final_score"], 0, 10)
        point = score * D(".4")
        if score >= 4 and row.get("minimums_met", True):
            earned[course] = credits
        candidate = (point, row["attempt_no"], credits, row)
        if course not in selected or candidate[:2] > selected[course][:2]:
            selected[course] = candidate
    with localcontext() as ctx:
        ctx.prec = 28
        qp = sum((r[0] * r[2] for r in selected.values()), D(0))
        credits = sum((r[2] for r in selected.values()), D(0))
        total_earned = sum(earned.values(), D(0))
        if raw:
            return {"quality_points": qp, "gpa_credits": credits, "earned_credits": total_earned}
        return {"quality_points": wire(qp), "gpa_credits": wire(credits),
                "cumulative_gpa": wire(qp / credits) if credits else None,
                "earned_credits": wire(total_earned), "required_credits": "126.000000",
                "remaining_required_credits": wire(max(D(0), D(126) - total_earned)),
                "failed_courses": [str(k) for k, v in selected.items() if k not in earned],
                "policy_version": POLICY, "data_origin": "synthetic", "gpa_scale": "4.000000"}


def required_gpa(qp, current_credits, target, future):
    qp, current_credits = D(qp), D(current_credits)
    target, future = decimal(target, 0, 4), decimal(future, 0, 126)
    current = qp / current_credits if current_credits else None
    required = (target * (current_credits + future) - qp) / future if future else None
    state = ("impossible" if required > 4 else "achievable") if required is not None else (
        "insufficient_data" if current is None else "completed_target_met" if current >= target else "completed_target_not_met")
    return {"current_gpa": wire(current), "target_gpa": wire(target),
            "gap": wire(target - current) if current is not None else None,
            "required_future_gpa": wire(max(D(0), required)) if required is not None else None,
            "feasibility": state, "gpa_scale_max": "4.000000", "policy_version": POLICY,
            "data_origin": "synthetic", "assumptions": ["Chỉ thêm tín chỉ GPA mới, không thay điểm học lại"]}


def target_score(components, target, unknown_code):
    if sum((D(str(c["weight"])) for c in components), D(0)) != 1:
        raise ValueError("INVALID_WEIGHTS")
    missing = [c for c in components if c.get("score") is None]
    if len(missing) != 1:
        raise ValueError("MULTIPLE_UNKNOWN_COMPONENTS")
    unknown = missing[0]
    if unknown["code"] != unknown_code:
        raise ValueError("INVALID_COMPONENT")
    for c in components:
        if decimal(c["weight"], 0, 1) <= 0:
            raise ValueError("INVALID_WEIGHTS")
        if c.get("score") is not None:
            decimal(c["score"], 0, 10)
    known = sum((D(str(c["score"])) * D(str(c["weight"])) for c in components if c.get("score") is not None), D(0))
    needed = max(D(0), D(str(unknown["minimum_required"])), (decimal(target, 0, 10) - known) / D(str(unknown["weight"])))
    failed_minimum = any(c.get("score") is not None and D(str(c["score"])) < D(str(c["minimum_required"])) for c in components)
    return {"required_score": wire(needed), "max_score": "10.000000",
            "minimum_exam_score": wire(D(str(unknown["minimum_required"]))),
            "feasibility": "impossible" if needed > 10 or failed_minimum else "achievable",
            "policy_version": POLICY, "data_origin": "synthetic"}


def semester_history(rows):
    by_semester = {}
    for r in rows:
        sem = str(r.get("semester_id") or "unknown")
        by_semester.setdefault(sem, []).append(r)
    history = []
    accumulated = []
    # Rows arrive chronologically. A snapshot contains only attempts known at
    # that semester end; later retakes never rewrite earlier history.
    for sem, sem_rows in by_semester.items():
        term_sum = summary(sem_rows, raw=True)
        term_cr = term_sum["gpa_credits"]
        term_qp = term_sum["quality_points"]
        term_gpa = term_qp / term_cr if term_cr else None
        accumulated.extend(sem_rows)
        cum_sum = summary(accumulated)
        history.append({
            "semester_id": sem,
            "semester_code": sem_rows[0].get('semester_code'),
            "term_gpa": wire(term_gpa),
            "term_credits": wire(term_cr),
            "term_earned_credits": wire(term_sum["earned_credits"]),
            "cumulative_gpa": cum_sum["cumulative_gpa"],
            "cumulative_earned_credits": cum_sum["earned_credits"],
            "snapshot_rule": "attempts_available_at_semester_end_only",
        })
    return history


def academic_trend(history):
    values = [D(item["cumulative_gpa"]) for item in history if item["cumulative_gpa"] is not None]
    if len(values) < 2:
        return {"state": "insufficient_data", "delta": None}
    delta = values[-1] - values[-2]
    return {"state": "improving" if delta > 0 else "declining" if delta < 0 else "stable", "delta": wire(delta)}


def learning_paths(edges, targets):
    """Prerequisites first per target; union keeps shared ancestors only once."""
    edges = [(str(c), str(p)) for c, p in edges]
    detect_prerequisite_cycles(edges)
    graph = {}
    for course, prerequisite in edges:
        graph.setdefault(course, set()).add(prerequisite)
    paths, union = {}, []
    for target in sorted(set(map(str, targets))):
        ordered, seen = [], set()
        def visit(course):
            if course in seen:
                return
            seen.add(course)
            for prerequisite in sorted(graph.get(course, ())):
                visit(prerequisite)
            ordered.append(course)
        visit(target)
        paths[target] = ordered
        union.extend(course for course in ordered if course not in union)
    return {'by_target': paths, 'union': union}


def detect_prerequisite_cycles(edges):
    graph = {}
    for course, prereq in edges:
        course, prereq = str(course), str(prereq)
        if course == prereq:
            raise ValueError(f"PREREQUISITE_CYCLE_DETECTED: {course} -> {prereq}")
        graph.setdefault(course, []).append(prereq)
        if prereq not in graph:
            graph[prereq] = []
    visited = {}
    cycle_path = []

    def dfs(node, path):
        visited[node] = 1
        path.append(node)
        for neighbor in graph.get(node, []):
            if visited.get(neighbor, 0) == 1:
                idx = path.index(neighbor)
                cycle_path.extend(path[idx:] + [neighbor])
                return True
            if visited.get(neighbor, 0) == 0:
                if dfs(neighbor, path):
                    return True
        path.pop()
        visited[node] = 2
        return False

    for node in graph:
        if visited.get(node, 0) == 0:
            if dfs(node, []):
                raise ValueError(f"PREREQUISITE_CYCLE_DETECTED: {' -> '.join(cycle_path)}")
    return True
