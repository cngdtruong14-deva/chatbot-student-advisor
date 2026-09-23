"""Add explicit source authority/provenance for immutable corpus releases."""
from alembic import op

revision = '0013_corpus_release_v2'
down_revision = '0012_personal_academics'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.document_versions
      ADD COLUMN IF NOT EXISTS source_id text,
      ADD COLUMN IF NOT EXISTS source_url text,
      ADD COLUMN IF NOT EXISTS document_authority text NOT NULL DEFAULT 'unverified'
        CHECK(document_authority IN ('demo','test_only','unverified','official_utt_source'));
    CREATE UNIQUE INDEX IF NOT EXISTS document_versions_release_source_uq
      ON app.document_versions(release_id, source_id)
      WHERE release_id IS NOT NULL AND source_id IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS corpus_releases_one_active_scope_uq
      ON app.corpus_releases(corpus_scope) WHERE status='active';
    """)


def downgrade():
    raise RuntimeError('Destructive rollback requires explicit reviewed backup restore.')
