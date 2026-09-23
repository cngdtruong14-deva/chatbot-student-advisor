"""Phase C: Corpus release, scope and citation metadata schema.

Additive and backward-compatible migration for corpus releases,
hierarchical locators, verification dates and provenance ranges.
Existing DEMO-1 and isolated test corpora remain 100% valid and untouched.
"""
from alembic import op


revision = "0010_phase_c_corpus_release"
down_revision = "0009_academic_demo_v2_ml_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    -- 1. Extend document_versions constraints and metadata columns
    ALTER TABLE app.document_versions DROP CONSTRAINT IF EXISTS document_versions_scope_key_check;
    ALTER TABLE app.document_versions
      ADD CONSTRAINT document_versions_scope_key_check
      CHECK(scope_key IN ('demo_academic', 'utt_test', 'utt_corpus'));

    ALTER TABLE app.document_versions DROP CONSTRAINT IF EXISTS document_versions_review_state_check;
    ALTER TABLE app.document_versions
      ADD CONSTRAINT document_versions_review_state_check
      CHECK(review_state IN ('approved_demo', 'test_only', 'reviewed', 'staging_pending'));

    ALTER TABLE app.document_versions
      ADD COLUMN IF NOT EXISTS raw_sha256 text,
      ADD COLUMN IF NOT EXISTS effective_from date,
      ADD COLUMN IF NOT EXISTS effective_until date,
      ADD COLUMN IF NOT EXISTS is_effective_date_verified boolean NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS available_from date NOT NULL DEFAULT CURRENT_DATE,
      ADD COLUMN IF NOT EXISTS available_until date NOT NULL DEFAULT '9999-12-31',
      ADD COLUMN IF NOT EXISTS major text,
      ADD COLUMN IF NOT EXISTS cohort text,
      ADD COLUMN IF NOT EXISTS education_level text DEFAULT 'dai_hoc',
      ADD COLUMN IF NOT EXISTS reviewer text,
      ADD COLUMN IF NOT EXISTS release_id text;

    -- 2. Extend chat_sessions corpus_scope constraint
    ALTER TABLE app.chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_corpus_scope_check;
    ALTER TABLE app.chat_sessions
      ADD CONSTRAINT chat_sessions_corpus_scope_check
      CHECK(corpus_scope IN ('demo_academic', 'utt_test', 'utt_corpus'));

    -- 3. Extend chunks table for hierarchical legal locators and provenance
    ALTER TABLE app.chunks
      ADD COLUMN IF NOT EXISTS page_number integer,
      ADD COLUMN IF NOT EXISTS locator_type text NOT NULL DEFAULT 'section',
      ADD COLUMN IF NOT EXISTS locator_label text,
      ADD COLUMN IF NOT EXISTS heading text,
      ADD COLUMN IF NOT EXISTS article text,
      ADD COLUMN IF NOT EXISTS clause text,
      ADD COLUMN IF NOT EXISTS table_id text,
      ADD COLUMN IF NOT EXISTS char_start integer,
      ADD COLUMN IF NOT EXISTS char_end integer,
      ADD COLUMN IF NOT EXISTS chunker_version text NOT NULL DEFAULT 'v1';

    -- 4. Create corpus_releases table with release receipt and status tracking
    CREATE TABLE IF NOT EXISTS app.corpus_releases (
      id text PRIMARY KEY,
      corpus_scope text NOT NULL,
      status text NOT NULL DEFAULT 'staging' CHECK(status IN ('staging', 'active', 'retired', 'failed')),
      chunker_version text NOT NULL,
      embedding_model text NOT NULL,
      embedding_revision text NOT NULL,
      embedding_dimension integer NOT NULL DEFAULT 384,
      collection_name text NOT NULL,
      chunk_count integer NOT NULL,
      chunks_hash text NOT NULL,
      source_manifest_hash text NOT NULL,
      receipt jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      activated_at timestamptz,
      activated_by uuid REFERENCES app.users
    );

    CREATE INDEX IF NOT EXISTS corpus_releases_scope_status_idx
      ON app.corpus_releases(corpus_scope, status);

    -- 5. Baseline active release record for DEMO-1
    INSERT INTO app.corpus_releases(
      id, corpus_scope, status, chunker_version, embedding_model, embedding_revision,
      embedding_dimension, collection_name, chunk_count, chunks_hash, source_manifest_hash,
      receipt, activated_at
    )
    VALUES (
      'DEMO-1-RELEASE', 'demo_academic', 'active', 'v1',
      'intfloat/multilingual-e5-small', '614241f622f53c4eeff9890bdc4f31cfecc418b3',
      384, 'demo-academic-v1', 1, 'demo-1-baseline-hash', 'demo-1-source-manifest',
      jsonb_build_object('status', 'active', 'description', 'Baseline DEMO-1 synthetic policy release', 'verified', true),
      now()
    )
    ON CONFLICT (id) DO NOTHING;
    """)


def downgrade():
    raise RuntimeError("Destructive rollback requires explicit reviewed backup restore.")
