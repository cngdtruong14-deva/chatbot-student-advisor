"""Add reviewed demo career/skill reference data for the HTTT curriculum."""
from alembic import op
from sqlalchemy import text

from app.career_data import (
    CAREERS, CAREER_SKILLS, CERTIFICATIONS, COURSE_SKILLS_SHA256,
    COURSE_SKILLS_SOURCE, CURATION_STATUS, CURRICULUM_CODE, CURRICULUM_VERSION,
    EXCLUDED_COURSES, MAPPING_VERSION, SKILLS, TECHNICAL_SCOPE_EXCLUSIONS,
    load_course_skills, validate_reference_data,
)


revision = "0016_career_skills"
down_revision = "0015_htt_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE TABLE app.skills (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        skill_code text NOT NULL, name text NOT NULL,
        category text NOT NULL CHECK(category IN ('Business','Technical','Tool','Soft')),
        mapping_version text NOT NULL, curation_status text NOT NULL CHECK(curation_status='owner_approved_demo'),
        UNIQUE(skill_code,mapping_version));
      CREATE TABLE app.careers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        career_code text NOT NULL, title text NOT NULL, description text NOT NULL,
        major_code text NOT NULL, mapping_version text NOT NULL,
        curation_status text NOT NULL CHECK(curation_status='owner_approved_demo'),
        UNIQUE(career_code,mapping_version));
      CREATE TABLE app.career_skill_requirements (
        career_id uuid NOT NULL REFERENCES app.careers,
        skill_id uuid NOT NULL REFERENCES app.skills,
        importance_weight numeric(9,6) NOT NULL CHECK(importance_weight>0 AND importance_weight<=1),
        required_level numeric(9,6) CHECK(required_level>0 AND required_level<=5),
        mapping_version text NOT NULL,
        PRIMARY KEY(career_id,skill_id,mapping_version));
      CREATE TABLE app.course_skills (
        course_id uuid NOT NULL REFERENCES app.courses,
        skill_id uuid NOT NULL REFERENCES app.skills,
        contribution_weight numeric(9,6) NOT NULL CHECK(contribution_weight>0 AND contribution_weight<=1),
        mapping_version text NOT NULL,
        review_status text NOT NULL CHECK(review_status='owner_approved_demo'),
        source_name text NOT NULL, source_sha256 text NOT NULL,
        PRIMARY KEY(course_id,skill_id,mapping_version));
      CREATE TABLE app.course_skill_exclusions (
        course_id uuid NOT NULL REFERENCES app.courses,
        mapping_version text NOT NULL,
        reason_code text NOT NULL CHECK(reason_code IN ('non_career_foundation','outside_selected_career_scope')),
        review_status text NOT NULL CHECK(review_status='owner_approved_demo'),
        PRIMARY KEY(course_id,mapping_version));
      CREATE TABLE app.certifications (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cert_code text NOT NULL,
        name text NOT NULL, related_skill_id uuid NOT NULL REFERENCES app.skills,
        mapping_version text NOT NULL,
        curation_status text NOT NULL CHECK(curation_status='owner_approved_demo'),
        UNIQUE(cert_code,mapping_version));
      CREATE INDEX ix_course_skills_skill ON app.course_skills(skill_id,mapping_version);
      CREATE INDEX ix_career_skill_requirements_skill ON app.career_skill_requirements(skill_id,mapping_version);
    """)
    bind = op.get_bind()
    catalog = bind.execute(text("""SELECT c.code,c.title,c.id FROM app.courses c
      JOIN app.curriculum_courses cc ON cc.course_id=c.id JOIN app.curricula cur ON cur.id=cc.curriculum_id
      WHERE cur.code=:code AND cur.version=:version"""),
      {"code": CURRICULUM_CODE, "version": CURRICULUM_VERSION}).mappings().all()
    catalog_codes = {row["code"] for row in catalog}
    validate_reference_data(catalog_codes)
    courses = {row["code"]: row for row in catalog}

    skill_ids = {}
    for code, name, category in SKILLS:
        skill_ids[code] = bind.execute(text("""INSERT INTO app.skills(
          skill_code,name,category,mapping_version,curation_status)
          VALUES(:code,:name,:category,:version,:status) RETURNING id"""),
          {"code": code, "name": name, "category": category, "version": MAPPING_VERSION,
           "status": CURATION_STATUS}).scalar_one()
    career_ids = {}
    for code, title, description in CAREERS:
        career_ids[code] = bind.execute(text("""INSERT INTO app.careers(
          career_code,title,description,major_code,mapping_version,curation_status)
          VALUES(:code,:title,:description,:major,:version,:status) RETURNING id"""),
          {"code": code, "title": title, "description": description, "major": CURRICULUM_CODE,
           "version": MAPPING_VERSION, "status": CURATION_STATUS}).scalar_one()
    for career, skill, weight in CAREER_SKILLS:
        bind.execute(text("""INSERT INTO app.career_skill_requirements(
          career_id,skill_id,importance_weight,required_level,mapping_version)
          VALUES(:career,:skill,:weight,NULL,:version)"""),
          {"career": career_ids[career], "skill": skill_ids[skill], "weight": weight,
           "version": MAPPING_VERSION})
    for row in load_course_skills():
        if row["course_title"] != courses[row["course_code"]]["title"]:
            raise RuntimeError("COURSE_SKILLS_TITLE_MISMATCH:" + row["course_code"])
        bind.execute(text("""INSERT INTO app.course_skills(
          course_id,skill_id,contribution_weight,mapping_version,review_status,source_name,source_sha256)
          VALUES(:course,:skill,:weight,:version,:status,:source,:source_hash)"""), {
          "course": courses[row["course_code"]]["id"], "skill": skill_ids[row["skill_id"]],
          "weight": row["weight"], "version": MAPPING_VERSION, "status": CURATION_STATUS,
          "source": COURSE_SKILLS_SOURCE, "source_hash": COURSE_SKILLS_SHA256,
        })
    for code in sorted(EXCLUDED_COURSES):
        bind.execute(text("""INSERT INTO app.course_skill_exclusions(
          course_id,mapping_version,reason_code,review_status)
          VALUES(:course,:version,:reason,:status)"""), {
          "course": courses[code]["id"], "version": MAPPING_VERSION,
          "reason": "outside_selected_career_scope" if code in TECHNICAL_SCOPE_EXCLUSIONS else "non_career_foundation",
          "status": CURATION_STATUS,
        })
    for code, name, skill in CERTIFICATIONS:
        bind.execute(text("""INSERT INTO app.certifications(
          cert_code,name,related_skill_id,mapping_version,curation_status)
          VALUES(:code,:name,:skill,:version,:status)"""), {
          "code": code, "name": name, "skill": skill_ids[skill],
          "version": MAPPING_VERSION, "status": CURATION_STATUS,
        })
    bind.execute(text("""INSERT INTO app.audit_logs(action,entity_type,entity_id,status,request_id)
      VALUES('migrate_career_skills','career_mapping',:entity,'completed',:request)"""),
      {"entity": MAPPING_VERSION, "request": "migration-0016-career-skills"})


def downgrade():
    raise RuntimeError("Reviewed backup/restore required; no destructive automatic downgrade")
