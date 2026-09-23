"""Allow the separately labelled Academic Demo v2 synthetic ML domain.

This is an additive domain-extension migration.  It does not turn an
academic-demo record into OULAD data, alter existing snapshots/predictions,
or create a student-profile inference path.
"""
from alembic import op


revision = "0009_academic_demo_v2_ml_domain"
down_revision = "0008_synthetic_research_origin"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.research_cases DROP CONSTRAINT IF EXISTS research_cases_domain_id_check;
    ALTER TABLE app.research_cases ADD CONSTRAINT research_cases_domain_id_check
      CHECK(domain_id IN ('oulad', 'academic_demo_v2'));

    ALTER TABLE app.feature_snapshots DROP CONSTRAINT IF EXISTS feature_snapshots_domain_id_check;
    ALTER TABLE app.feature_snapshots ADD CONSTRAINT feature_snapshots_domain_id_check
      CHECK(domain_id IN ('oulad', 'academic_demo_v2'));

    ALTER TABLE app.model_versions DROP CONSTRAINT IF EXISTS model_versions_domain_id_check;
    ALTER TABLE app.model_versions ADD CONSTRAINT model_versions_domain_id_check
      CHECK(domain_id IN ('oulad', 'academic_demo_v2'));
    """)


def downgrade():
    raise RuntimeError("Destructive rollback requires a reviewed backup restore.")
