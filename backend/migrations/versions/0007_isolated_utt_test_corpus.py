"""Add an explicitly non-authoritative UTT test corpus alongside DEMO-1."""
from alembic import op

revision = '0007_isolated_utt_test_corpus'
down_revision = '0006_cohort_catalog'
branch_labels = None
depends_on = None


def upgrade():
    # Existing DEMO rows remain valid and untouched. Named constraints make
    # future migration review deterministic rather than relying on PG names.
    op.execute("""
    ALTER TABLE app.document_versions DROP CONSTRAINT IF EXISTS document_versions_scope_key_check;
    ALTER TABLE app.document_versions DROP CONSTRAINT IF EXISTS document_versions_data_origin_check;
    ALTER TABLE app.document_versions
      ADD CONSTRAINT document_versions_scope_key_check CHECK(scope_key IN ('demo_academic','utt_test')),
      ADD CONSTRAINT document_versions_data_origin_check CHECK(data_origin IN ('synthetic','user_provided_institutional_document')),
      ADD COLUMN corpus_label text NOT NULL DEFAULT 'DEMO-1',
      ADD COLUMN review_state text NOT NULL DEFAULT 'approved_demo'
        CHECK(review_state IN ('approved_demo','test_only','reviewed'));
    ALTER TABLE app.chat_sessions
      ADD COLUMN corpus_scope text NOT NULL DEFAULT 'demo_academic'
        CHECK(corpus_scope IN ('demo_academic','utt_test'));
    CREATE INDEX IF NOT EXISTS document_versions_corpus_scope_idx
      ON app.document_versions(status,scope_key,valid_from,valid_until);
    CREATE INDEX IF NOT EXISTS chat_sessions_user_corpus_idx
      ON app.chat_sessions(user_id,corpus_scope,created_at DESC);
    """)


def downgrade():
    raise RuntimeError('Destructive rollback requires explicit review.')
