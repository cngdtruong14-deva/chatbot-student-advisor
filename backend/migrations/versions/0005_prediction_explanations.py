"""Persist explanations with the original prediction; no history rewriting."""
from alembic import op
revision='0005_prediction_explanations'
down_revision='0004_documents'
branch_labels=None
depends_on=None
def upgrade():
    op.execute('ALTER TABLE app.predictions ADD COLUMN explanation_json jsonb')
def downgrade():
    raise RuntimeError('Destructive rollback requires explicit review.')
