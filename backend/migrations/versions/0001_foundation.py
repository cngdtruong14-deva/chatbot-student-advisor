"""Empty business baseline; version metadata only."""
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Runtime must not alter migration bookkeeping.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON app.alembic_version FROM advisor_app")


def downgrade():
    pass
