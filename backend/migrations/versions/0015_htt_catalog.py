"""UTT Information Systems curriculum catalog supplied by the owner.

This migration is additive for schema and scoped/idempotent for catalog data.
It never writes students, enrollments, grades, offerings, or ML artifacts.
"""
import json
from alembic import op
from sqlalchemy import text

from app.seed_httt_curriculum import (
    CURRICULUM_CODE,
    CURRICULUM_CREDITS,
    CURRICULUM_FACULTY,
    CURRICULUM_MAJOR,
    CURRICULUM_VERSION,
    DOMAIN_ID,
    ELECTIVE_CODES,
    HTTT_COURSES,
    NON_GPA_CODES,
    POLICY_CODE,
    POLICY_VERSION,
    PREREQUISITES,
    SOURCE_NAME,
    SOURCE_SHA256,
)

revision = "0015_htt_catalog"
down_revision = "0014_rag_control_feedback"
branch_labels = None
depends_on = None


def upgrade():
    if (len(HTTT_COURSES) != 72 or len(ELECTIVE_CODES) != 19
            or len(NON_GPA_CODES) != 8 or len(PREREQUISITES) != 45):
        raise RuntimeError("HTTT_CATALOG_INTEGRITY_FAILED")
    bind = op.get_bind()
    op.execute("""
      ALTER TABLE app.curricula ADD COLUMN faculty text;
      ALTER TABLE app.curricula ADD COLUMN source_name text;
      ALTER TABLE app.curricula ADD COLUMN source_sha256 text;
      ALTER TABLE app.curriculum_courses ALTER COLUMN recommended_term_no DROP NOT NULL;
      ALTER TABLE app.curriculum_courses ADD COLUMN counts_for_gpa boolean NOT NULL DEFAULT true;
    """)
    policy_rules = {
        "policy_version": "ACADEMIC-DEMO-2.0.0", "data_origin": "synthetic",
        "retake_rule": "latest_resolved_attempt_replaces_previous_even_if_lower",
        "absent_or_barred": "incomplete with effective 0 until later attempt",
        "non_gpa_courses": ["GEN402", "PE101", "PE201", "PE301"],
        "pass_score_10": 4,
        "gpa_4_bands": [[0, 0], [4, 1], [5, 1.5], [5.5, 2], [6.5, 2.5],
                         [7, 3], [8, 3.5], [8.5, 4]],
    }
    bind.execute(text("""INSERT INTO app.grading_policies(code,version,status,rules)
      VALUES(:code,:version,'demo',CAST(:rules AS jsonb))
      ON CONFLICT(code,version) DO NOTHING"""), {
        "code": POLICY_CODE, "version": POLICY_VERSION,
        "rules": json.dumps(policy_rules),
    })
    policy = bind.execute(text("""
      SELECT id FROM app.grading_policies
      WHERE code=:code AND version=:version
    """), {"code": POLICY_CODE, "version": POLICY_VERSION}).mappings().first()
    if not policy:
        raise RuntimeError("HTTT_POLICY_MISSING")
    curriculum = bind.execute(text("""
      INSERT INTO app.curricula(
        code,version,major,total_required_credits,policy_id,status,
        faculty,source_name,source_sha256)
      VALUES(:code,:version,:major,:credits,:policy,'demo',:faculty,:source,:source_hash)
      ON CONFLICT(code,version) DO UPDATE SET
        major=excluded.major,total_required_credits=excluded.total_required_credits,
        policy_id=excluded.policy_id,faculty=excluded.faculty,
        source_name=excluded.source_name,source_sha256=excluded.source_sha256
      RETURNING id
    """), {
        "code": CURRICULUM_CODE, "version": CURRICULUM_VERSION,
        "major": CURRICULUM_MAJOR, "credits": CURRICULUM_CREDITS,
        "policy": policy["id"], "faculty": CURRICULUM_FACULTY,
        "source": SOURCE_NAME, "source_hash": SOURCE_SHA256,
    }).mappings().first()
    course_ids = {}
    for code, title, credits, _term_no in HTTT_COURSES:
        row = bind.execute(text("""
          INSERT INTO app.courses(code,title,domain_id)
          VALUES(:code,:title,:domain)
          ON CONFLICT(domain_id,code) DO UPDATE SET title=excluded.title
          RETURNING id
        """), {"code": code, "title": title, "domain": DOMAIN_ID}).mappings().first()
        course_ids[code] = row["id"]
        bind.execute(text("""
          INSERT INTO app.curriculum_courses(
            curriculum_id,course_id,credits,required,recommended_term_no,counts_for_gpa)
          VALUES(:curriculum,:course,:credits,:required,NULL,:counts_for_gpa)
          ON CONFLICT(curriculum_id,course_id) DO UPDATE SET
            credits=excluded.credits,required=excluded.required,recommended_term_no=NULL,
            counts_for_gpa=excluded.counts_for_gpa
        """), {
            "curriculum": curriculum["id"], "course": row["id"],
            "credits": credits, "required": code not in ELECTIVE_CODES,
            "counts_for_gpa": code not in NON_GPA_CODES,
        })
    bind.execute(text("""UPDATE app.curriculum_courses cc SET counts_for_gpa=false
      FROM app.courses c WHERE c.id=cc.course_id
      AND c.code IN ('PE101','PE201','PE301','GEN402')"""))
    for course_code, prerequisite_code in PREREQUISITES:
        bind.execute(text("""
          INSERT INTO app.prerequisites(
            curriculum_id,course_id,prerequisite_course_id,min_grade_point)
          VALUES(:curriculum,:course,:prerequisite,1)
          ON CONFLICT(curriculum_id,course_id,prerequisite_course_id)
          DO UPDATE SET min_grade_point=excluded.min_grade_point
        """), {
            "curriculum": curriculum["id"], "course": course_ids[course_code],
            "prerequisite": course_ids[prerequisite_code],
        })
    bind.execute(text("""
      INSERT INTO app.audit_logs(action,entity_type,entity_id,status,request_id)
      VALUES('migrate_htt_catalog','curriculum',:entity,'completed',:request)
    """), {"entity": f"{CURRICULUM_CODE}/{CURRICULUM_VERSION}",
            "request": "migration-0015-htt-catalog"})


def downgrade():
    raise RuntimeError("Reviewed backup/restore required; no destructive automatic downgrade")
