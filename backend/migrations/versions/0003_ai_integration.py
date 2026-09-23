"""Immutable research snapshots and model/prediction provenance."""
from alembic import op

revision = "0003_ai_integration"
down_revision = "0002_academic_app"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
    CREATE TABLE app.feature_snapshots (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), research_case_id uuid NOT NULL REFERENCES app.research_cases,
      domain_id text NOT NULL CHECK(domain_id='oulad'), data_origin text NOT NULL CHECK(data_origin='public_dataset'),
      feature_schema_id text NOT NULL, feature_schema_version text NOT NULL, cutoff_day integer NOT NULL CHECK(cutoff_day=28),
      features_json jsonb NOT NULL, source_completeness jsonb NOT NULL, snapshot_sha256 text NOT NULL UNIQUE,
      created_by uuid NOT NULL REFERENCES app.users, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.model_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), model_id text NOT NULL, model_version text NOT NULL,
      bundle_name text NOT NULL UNIQUE, manifest_sha256 text NOT NULL UNIQUE, manifest_json jsonb NOT NULL,
      domain_id text NOT NULL CHECK(domain_id='oulad'), target_id text NOT NULL, feature_schema_version text NOT NULL,
      cutoff_day integer NOT NULL CHECK(cutoff_day=28), activated_by text NOT NULL, activated_at timestamptz NOT NULL DEFAULT now(),
      is_active boolean NOT NULL DEFAULT false, UNIQUE(model_id,model_version));
    CREATE UNIQUE INDEX one_active_oulad_model ON app.model_versions(domain_id,target_id,feature_schema_version,cutoff_day) WHERE is_active;
    CREATE TABLE app.predictions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), research_case_id uuid NOT NULL REFERENCES app.research_cases,
      feature_snapshot_id uuid NOT NULL REFERENCES app.feature_snapshots, model_version_id uuid NOT NULL REFERENCES app.model_versions,
      probability numeric(18,12) NOT NULL CHECK(probability>=0 AND probability<=1), threshold numeric(18,12) NOT NULL CHECK(threshold>=0 AND threshold<=1),
      risk_label text NOT NULL CHECK(risk_label IN ('at_risk','not_at_risk')), created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ON app.feature_snapshots(research_case_id,created_at DESC);
    CREATE INDEX ON app.predictions(research_case_id,created_at DESC);
    """)

def downgrade():
    raise RuntimeError("Destructive rollback requires explicit review; restore a reviewed backup instead.")
