"""Permit explicitly labelled synthetic OULAD-style research artifacts."""
from alembic import op

revision = '0008_synthetic_research_origin'
down_revision = '0007_isolated_utt_test_corpus'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.research_cases DROP CONSTRAINT IF EXISTS research_cases_data_origin_check;
    ALTER TABLE app.research_cases ADD CONSTRAINT research_cases_data_origin_check
      CHECK(data_origin IN ('public_dataset','synthetic'));
    ALTER TABLE app.feature_snapshots DROP CONSTRAINT IF EXISTS feature_snapshots_data_origin_check;
    ALTER TABLE app.feature_snapshots ADD CONSTRAINT feature_snapshots_data_origin_check
      CHECK(data_origin IN ('public_dataset','synthetic'));
    """)


def downgrade():
    raise RuntimeError('Destructive rollback requires reviewed backup restore.')
