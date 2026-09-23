"""Deterministic HTTT career requirements and student skill-gap calculations."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from app.career_data import MAPPING_VERSION


def _rows(db, query, **params):
    from app.store import rows
    return rows(db, query, **params)


def _one(db, query, **params):
    from app.store import one
    return one(db, query, **params)


ALGORITHM = "binary_passed_course_evidence_v1"
CAREER_ALIASES = {
    "CR01": ("business analyst", "phan tich nghiep vu", "ba"),
    "CR02": ("systems analyst", "system analyst", "phan tich he thong"),
    "CR03": ("erp functional consultant", "tu van erp", "erp"),
    "CR04": ("data analyst", "phan tich du lieu"),
    "CR05": ("database administrator", "quan tri co so du lieu", "quan tri csdl", "dba"),
    "CR06": ("it project coordinator", "dieu phoi du an", "quan ly du an cntt"),
}


def _normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.lower())
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


def resolve_career(value: str) -> str | None:
    text = _normalized(value)
    code_match = re.search(r"(?<![a-z0-9])cr0[1-6](?![a-z0-9])", text)
    if code_match:
        return code_match.group(0).upper()
    for code, aliases in CAREER_ALIASES.items():
        for alias in aliases:
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text):
                return code
    return None


def _wire(value: Decimal | None, places: str = ".000001") -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def _passed(attempt: dict) -> bool:
    status = attempt.get("status")
    if status == "P":
        return True
    if status == "exempt":
        return bool(attempt.get("recognized"))
    score = attempt.get("final_score")
    return status == "graded" and score is not None and Decimal(str(score)) >= 4 and bool(attempt.get("minimums_met", True))


def build_skill_profile(mappings: list[dict], attempts: list[dict]) -> dict:
    """Build evidence from only the latest attempt for each course."""
    latest = {}
    for attempt in attempts:
        course_id = str(attempt["course_id"])
        current = latest.get(course_id)
        key = (int(attempt.get("attempt_no") or 0), str(attempt.get("finalized_at") or ""), str(attempt.get("created_at") or ""))
        if current is None or key > current[0]:
            latest[course_id] = (key, attempt)

    accum = defaultdict(lambda: {
        "possible": Decimal(0), "completed": Decimal(0), "scored": Decimal(0),
        "proficiency_points": Decimal(0), "evidence_courses": [], "available_courses": [],
    })
    skill_meta = {}
    for mapping in mappings:
        skill = mapping["skill_code"]
        skill_meta[skill] = {"skill_id": skill, "skill_name": mapping["skill_name"], "category": mapping["category"]}
        credits = Decimal(str(mapping["credits"]))
        contribution = Decimal(str(mapping["contribution_weight"]))
        evidence_weight = credits * contribution
        item = accum[skill]
        item["possible"] += evidence_weight
        item["available_courses"].append({
            "course_id": str(mapping["course_id"]), "course_code": mapping["course_code"],
            "course_title": mapping["course_title"], "credits": _wire(credits),
            "contribution_weight": _wire(contribution),
        })
        attempt_pair = latest.get(str(mapping["course_id"]))
        if not attempt_pair or not _passed(attempt_pair[1]):
            continue
        attempt = attempt_pair[1]
        item["completed"] += evidence_weight
        score = attempt.get("final_score")
        proficiency = None
        if score is not None:
            proficiency = min(Decimal(5), max(Decimal(0), Decimal(str(score)) / 2))
            item["scored"] += evidence_weight
            item["proficiency_points"] += evidence_weight * proficiency
        item["evidence_courses"].append({
            "course_code": mapping["course_code"], "course_title": mapping["course_title"],
            "attempt_no": int(attempt.get("attempt_no") or 0), "final_score": _wire(Decimal(str(score))) if score is not None else None,
            "proficiency_5": _wire(proficiency) if proficiency is not None else None,
            "contribution_weight": _wire(contribution),
        })

    skills = []
    for code in sorted(skill_meta):
        item = accum[code]
        proficiency = item["proficiency_points"] / item["scored"] if item["scored"] else None
        skills.append({
            **skill_meta[code], "matched": item["completed"] > 0,
            "proficiency_5": _wire(proficiency),
            "course_coverage": _wire(item["completed"] / item["possible"] if item["possible"] else Decimal(0)),
            "scored_coverage": _wire(item["scored"] / item["possible"] if item["possible"] else Decimal(0)),
            "evidence_courses": sorted(item["evidence_courses"], key=lambda row: row["course_code"]),
            "available_courses": sorted(item["available_courses"], key=lambda row: row["course_code"]),
        })
    return {"skills": skills, "latest_attempt_count": len(latest),
            "passed_mapped_course_count": len({course["course_code"] for skill in skills for course in skill["evidence_courses"]})}


def calculate_gap(career: dict, requirements: list[dict], profile: dict, certifications: list[dict]) -> dict:
    skills = {row["skill_id"]: row for row in profile["skills"]}
    total = sum((Decimal(str(row["importance_weight"])) for row in requirements), Decimal(0))
    matched_weight = Decimal(0)
    strong, missing = [], []
    for requirement in sorted(requirements, key=lambda row: (-Decimal(str(row["importance_weight"])), row["skill_id"])):
        skill = skills.get(requirement["skill_id"], {
            "skill_id": requirement["skill_id"], "skill_name": requirement["skill_name"],
            "category": requirement["category"], "matched": False, "proficiency_5": None,
            "course_coverage": "0.000000", "evidence_courses": [], "available_courses": [],
        })
        detail = {**skill, "importance_weight": _wire(Decimal(str(requirement["importance_weight"])))}
        if skill["matched"]:
            matched_weight += Decimal(str(requirement["importance_weight"]))
            strong.append(detail)
        else:
            missing.append(detail)

    missing_ids = {row["skill_id"] for row in missing}
    course_candidates = defaultdict(lambda: {"score": Decimal(0), "skills": set()})
    for requirement in requirements:
        if requirement["skill_id"] not in missing_ids:
            continue
        importance = Decimal(str(requirement["importance_weight"]))
        skill = skills.get(requirement["skill_id"])
        for course in (skill or {}).get("available_courses", []):
            item = course_candidates[(course["course_code"], course["course_title"], course["credits"])]
            item["score"] += importance * Decimal(str(course["contribution_weight"]))
            item["skills"].add(requirement["skill_name"])
    recommended_courses = [{
        "course_code": key[0], "course_title": key[1], "credits": key[2],
        "relevance_score": _wire(value["score"]), "missing_skills": sorted(value["skills"]),
    } for key, value in course_candidates.items()]
    recommended_courses.sort(key=lambda row: (-Decimal(row["relevance_score"]), row["course_code"]))

    score = Decimal(0) if not total else Decimal(100) * matched_weight / total
    return {
        "career": career, "match_score": _wire(score), "algorithm": ALGORITHM,
        "data_status": "sufficient_for_demo" if profile["passed_mapped_course_count"] else "insufficient_evidence",
        "mapping_version": MAPPING_VERSION,
        "passed_mapped_course_count": profile["passed_mapped_course_count"],
        "strong_skills": strong, "missing_skills": missing,
        "recommended_courses": recommended_courses[:8],
        "recommended_certifications": [row for row in certifications if row["skill_id"] in missing_ids],
        "limitations": [
            "Match score is weighted coverage of reviewed demo requirements, not a hiring probability.",
            "Only the latest passed attempt of each mapped HTTT course is evidence.",
            "Unknown evidence is not treated as verified proficiency.",
        ],
    }


def list_careers(db) -> list[dict]:
    return _rows(db, """SELECT career_code,title,description,major_code,mapping_version,curation_status
        FROM app.careers WHERE mapping_version=:version ORDER BY career_code""", version=MAPPING_VERSION)


def _career(db, career_code: str) -> dict | None:
    return _one(db, """SELECT career_code,title,description,major_code,mapping_version,curation_status
        FROM app.careers WHERE career_code=:code AND mapping_version=:version""",
        code=career_code, version=MAPPING_VERSION)


def _requirements(db, career_code: str) -> list[dict]:
    return _rows(db, """SELECT s.skill_code AS skill_id,s.name AS skill_name,s.category,
          csr.importance_weight,csr.required_level
        FROM app.career_skill_requirements csr JOIN app.careers c ON c.id=csr.career_id
        JOIN app.skills s ON s.id=csr.skill_id
        WHERE c.career_code=:code AND c.mapping_version=:version
        ORDER BY csr.importance_weight DESC,s.skill_code""", code=career_code, version=MAPPING_VERSION)


def _certifications(db) -> list[dict]:
    return _rows(db, """SELECT c.cert_code,c.name,s.skill_code AS skill_id,s.name AS skill_name
        FROM app.certifications c JOIN app.skills s ON s.id=c.related_skill_id
        WHERE c.mapping_version=:version ORDER BY c.cert_code""", version=MAPPING_VERSION)


def _mappings(db, curriculum_id) -> list[dict]:
    return _rows(db, """SELECT c.id AS course_id,c.code AS course_code,c.title AS course_title,
          cc.credits,s.skill_code,s.name AS skill_name,s.category,cs.contribution_weight
        FROM app.course_skills cs JOIN app.courses c ON c.id=cs.course_id
        JOIN app.curriculum_courses cc ON cc.course_id=c.id AND cc.curriculum_id=:curriculum
        JOIN app.skills s ON s.id=cs.skill_id WHERE cs.mapping_version=:version
        ORDER BY c.code,s.skill_code""", curriculum=curriculum_id, version=MAPPING_VERSION)


def _attempts(db, student_id) -> list[dict]:
    return _rows(db, """SELECT e.course_id,e.attempt_no,e.status,e.final_score,e.recognized,
          e.minimums_met,e.finalized_at,e.created_at
        FROM app.enrollments e WHERE e.student_id=:student ORDER BY e.course_id,e.attempt_no""", student=student_id)


def career_requirements(db, career_code: str) -> dict | None:
    career = _career(db, career_code)
    if not career:
        return None
    requirements = _requirements(db, career_code)
    curriculum = _one(db, """SELECT id FROM app.curricula WHERE code=:code
        ORDER BY version DESC LIMIT 1""", code=career["major_code"])
    mapped_courses = defaultdict(list)
    if curriculum:
        for mapping in _mappings(db, curriculum["id"]):
            mapped_courses[mapping["skill_code"]].append({
                "course_code": mapping["course_code"], "course_title": mapping["course_title"],
                "credits": _wire(Decimal(str(mapping["credits"]))),
                "contribution_weight": _wire(Decimal(str(mapping["contribution_weight"]))),
            })
    requirements = [{**row, "courses": mapped_courses[row["skill_id"]]} for row in requirements]
    certifications = _certifications(db)
    return {"career": career, "skills": requirements,
            "certifications": [row for row in certifications if row["skill_id"] in {r["skill_id"] for r in requirements}],
            "mapping_version": MAPPING_VERSION, "curation_status": career["curation_status"]}


def student_skill_gap(db, student: dict, career_code: str) -> dict | None:
    career = _career(db, career_code)
    if not career:
        return None
    profile = build_skill_profile(_mappings(db, student["curriculum_id"]), _attempts(db, student["id"]))
    result = calculate_gap(career, _requirements(db, career_code), profile, _certifications(db))
    result["student_id"] = str(student["id"])
    result["academic_revision"] = student["academic_revision"]
    return result


def career_matches(db, student: dict) -> dict:
    matches = [student_skill_gap(db, student, career["career_code"]) for career in list_careers(db)]
    matches = [match for match in matches if match]
    matches.sort(key=lambda row: (-Decimal(row["match_score"]), row["career"]["career_code"]))
    return {"matches": matches, "mapping_version": MAPPING_VERSION,
            "academic_revision": student["academic_revision"],
            "data_status": "sufficient_for_demo" if any(m["passed_mapped_course_count"] for m in matches) else "insufficient_evidence"}
