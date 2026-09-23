"""Controlled RAG feedback and the approved 30-day chat retention window.

The migration is additive.  It neither reads nor changes existing chat content;
new sessions receive the approved retention period when the migration is run.
"""
from alembic import op


revision = "0014_rag_control_feedback"
down_revision = "0013_corpus_release_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    -- The owner-approved retention period applies to sessions created after
    -- this migration.  Existing expiry timestamps are intentionally preserved.
    ALTER TABLE app.chat_sessions
      ALTER COLUMN expires_at SET DEFAULT (now() + interval '30 days');

    CREATE TABLE app.rag_feedback (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id uuid NOT NULL REFERENCES app.users,
      session_id uuid NOT NULL REFERENCES app.chat_sessions,
      client_turn_id uuid NOT NULL,
      label text NOT NULL CHECK(label IN ('helpful','not_helpful','incorrect_citation')),
      rationale text,
      corpus_scope text NOT NULL CHECK(corpus_scope IN ('demo_academic','utt_test','utt_corpus')),
      release_id text,
      retrieval_method text,
      created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
      CHECK (rationale IS NULL OR char_length(rationale) <= 500),
      CHECK (expires_at > created_at AND expires_at <= created_at + interval '30 days'),
      UNIQUE(session_id, client_turn_id),
      FOREIGN KEY(session_id, client_turn_id)
        REFERENCES app.chat_messages(session_id, client_turn_id)
    );
    CREATE INDEX rag_feedback_expiry_idx ON app.rag_feedback(expires_at);
    CREATE INDEX rag_feedback_release_idx ON app.rag_feedback(release_id, created_at DESC);
    """)


def downgrade():
    raise RuntimeError("Retention data requires reviewed backup/restore; no destructive downgrade")
