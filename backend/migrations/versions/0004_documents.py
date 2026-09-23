"""Versioned database corpus and immutable research evidence."""
from alembic import op

revision = '0004_documents'
down_revision = '0003_ai_integration'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    CREATE TABLE app.documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), title text NOT NULL,
      document_type text NOT NULL, source text NOT NULL, created_by uuid NOT NULL REFERENCES app.users,
      created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.document_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), document_id uuid NOT NULL REFERENCES app.documents,
      version text NOT NULL, content text NOT NULL, sha256 text NOT NULL,
      scope_key text NOT NULL CHECK(scope_key='demo_academic'),
      data_origin text NOT NULL CHECK(data_origin='synthetic'),
      valid_from date NOT NULL, valid_until date NOT NULL CHECK(valid_until>valid_from),
      status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','ready','active','retired','failed')),
      error_code text, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(document_id,version), UNIQUE(document_id,sha256));
    CREATE TABLE app.chunks (
      chunk_id text PRIMARY KEY, version_id uuid NOT NULL REFERENCES app.document_versions,
      section text NOT NULL, content text NOT NULL, text_hash text NOT NULL);
    CREATE INDEX ON app.document_versions(status,scope_key,valid_from,valid_until);
    CREATE INDEX ON app.chunks(version_id);
    CREATE FUNCTION app.reject_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Evidence is immutable'; END $$;
    CREATE TRIGGER immutable_feature_snapshots BEFORE UPDATE OR DELETE ON app.feature_snapshots
      FOR EACH ROW EXECUTE FUNCTION app.reject_evidence_mutation();
    CREATE TRIGGER immutable_predictions BEFORE UPDATE OR DELETE ON app.predictions
      FOR EACH ROW EXECUTE FUNCTION app.reject_evidence_mutation();
    """)

def downgrade():
    raise RuntimeError('Destructive rollback requires explicit review.')
