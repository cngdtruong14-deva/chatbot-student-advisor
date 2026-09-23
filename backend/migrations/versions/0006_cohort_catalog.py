"""Add a compatible cohort catalog for CSV reference resolution."""
from alembic import op

revision = "0006_cohort_catalog"
down_revision = "0005_prediction_explanations"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.cohorts (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      code text NOT NULL UNIQUE,
      curriculum_id uuid NOT NULL REFERENCES app.curricula,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    ALTER TABLE app.students ADD COLUMN cohort_id uuid REFERENCES app.cohorts;
    """)


def downgrade():
    raise RuntimeError("Destructive rollback requires explicit review; restore a reviewed backup instead.")
