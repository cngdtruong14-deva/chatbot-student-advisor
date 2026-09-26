"""Allow every student account to own a self-reported transcript directly."""
from alembic import op

revision = "0017_direct_transcript_owner"
down_revision = "0016_career_skills"
branch_labels = depends_on = None


def upgrade():
    # Self-reported records are account-owned. An optional onboarding profile
    # must never be an authorization or verification gate for this data.
    op.execute("""
    ALTER TABLE app.personal_transcripts
      DROP CONSTRAINT personal_transcripts_user_id_fkey,
      ADD CONSTRAINT personal_transcripts_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES app.users(id);
    ALTER TABLE app.personal_transcript_history
      DROP CONSTRAINT personal_transcript_history_user_id_fkey,
      ADD CONSTRAINT personal_transcript_history_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES app.users(id);
    """)


def downgrade():
    raise RuntimeError("Reviewed backup/restore required; no destructive automatic downgrade")
