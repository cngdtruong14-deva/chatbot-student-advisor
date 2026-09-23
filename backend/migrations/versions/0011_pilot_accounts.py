"""Pilot accounts; additive, not applied by the coding agent."""
from alembic import op

revision = "0011_pilot_accounts"
down_revision = "0010_phase_c_corpus_release"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.users ADD COLUMN username text;
    CREATE UNIQUE INDEX users_username_unique ON app.users(lower(username)) WHERE username IS NOT NULL;
    ALTER TABLE app.users ADD COLUMN auth_version integer NOT NULL DEFAULT 0;
    CREATE TABLE app.pilot_invites (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code_hash text UNIQUE NOT NULL,
      created_by uuid NOT NULL REFERENCES app.users, expires_at timestamptz NOT NULL,
      consumed_by uuid REFERENCES app.users, consumed_at timestamptz);
    CREATE TABLE app.account_recovery (
      user_id uuid PRIMARY KEY REFERENCES app.users, code_hash text UNIQUE NOT NULL,
      expires_at timestamptz NOT NULL, created_by uuid NOT NULL REFERENCES app.users);
    CREATE TABLE app.account_audit (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid REFERENCES app.users,
      subject_id uuid REFERENCES app.users, action text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.onboarding_profiles (
      user_id uuid PRIMARY KEY REFERENCES app.users, display_name text NOT NULL,
      major text NOT NULL DEFAULT '', cohort text NOT NULL DEFAULT '',
      data_origin text NOT NULL DEFAULT 'self_reported' CHECK(data_origin='self_reported'),
      updated_at timestamptz NOT NULL DEFAULT now());
    GRANT SELECT, INSERT, UPDATE ON app.pilot_invites, app.account_recovery,
      app.account_audit, app.onboarding_profiles TO advisor_app;
    GRANT DELETE ON app.account_recovery TO advisor_app;
    """)


def downgrade():
    raise RuntimeError("Reviewed backup/restore required; no destructive automatic downgrade")
