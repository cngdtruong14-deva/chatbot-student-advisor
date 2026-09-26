"""Add the reviewed K75 pilot cohort for the HTTT curriculum.

The HTTT catalog migration deliberately did not create student data, but the
account-first linking workflow requires a cohort row before an administrator
can create an account-owned synthetic academic profile.
"""
from alembic import op
from sqlalchemy import text


revision = "0017_pilot_cohort"
down_revision = "0016_career_skills"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    curriculum = bind.execute(text("""
      SELECT id FROM app.curricula
      WHERE code='HTTT-UTT' AND version='2024'
    """)).mappings().first()
    if not curriculum:
        raise RuntimeError("HTTT_CURRICULUM_MISSING")

    bind.execute(text("""
      INSERT INTO app.cohorts(code,curriculum_id)
      VALUES('K75',:curriculum)
      ON CONFLICT(code) DO NOTHING
    """), {"curriculum": curriculum["id"]})
    cohort = bind.execute(text("""
      SELECT curriculum_id FROM app.cohorts WHERE code='K75'
    """)).mappings().first()
    if not cohort or cohort["curriculum_id"] != curriculum["id"]:
        raise RuntimeError("K75_COHORT_OWNERSHIP_CONFLICT")

    bind.execute(text("""
      INSERT INTO app.audit_logs(action,entity_type,entity_id,status,request_id)
      VALUES('migrate_pilot_cohort','cohort','HTTT-UTT/2024/K75','completed',
             'migration-0017-pilot-cohort')
    """))


def downgrade():
    raise RuntimeError("Reviewed backup/restore required; no destructive automatic downgrade")
