"""Versioned personal transcripts, isolated from synthetic research records."""
from alembic import op

revision = '0012_personal_academics'
down_revision = '0011_pilot_accounts'
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.personal_transcripts (
      user_id uuid PRIMARY KEY REFERENCES app.onboarding_profiles(user_id),
      revision integer NOT NULL CHECK(revision>0),
      policy_version text NOT NULL CHECK(policy_version='ACADEMIC-DEMO-2.0.0'),
      data_origin text NOT NULL DEFAULT 'self_reported' CHECK(data_origin='self_reported'),
      payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
      updated_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.personal_transcript_history (
      user_id uuid NOT NULL REFERENCES app.onboarding_profiles(user_id),
      revision integer NOT NULL CHECK(revision>0), payload jsonb NOT NULL,
      saved_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,revision));
    GRANT SELECT,INSERT,UPDATE ON app.personal_transcripts TO advisor_app;
    GRANT SELECT,INSERT ON app.personal_transcript_history TO advisor_app;
    """)


def downgrade():
    raise RuntimeError('Reviewed backup/restore required')
