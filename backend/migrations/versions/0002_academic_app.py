"""Additive application tables; DEMO-1 only. No existing table or volume removal."""
from alembic import op

revision = "0002_academic_app"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text UNIQUE NOT NULL,
      password_hash text NOT NULL, role text NOT NULL CHECK(role IN ('student','advisor','admin')),
      is_active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.refresh_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users,
      token_hash text UNIQUE NOT NULL, expires_at timestamptz NOT NULL,
      revoked_at timestamptz, replaced_by uuid REFERENCES app.refresh_sessions,
      created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.grading_policies (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL, version text NOT NULL,
      status text NOT NULL CHECK(status='demo'), rules jsonb NOT NULL,
      UNIQUE(code,version));
    CREATE TABLE app.curricula (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL, version text NOT NULL,
      major text NOT NULL, total_required_credits numeric(18,6) NOT NULL CHECK(total_required_credits>0),
      policy_id uuid NOT NULL REFERENCES app.grading_policies, status text NOT NULL CHECK(status='demo'),
      UNIQUE(code,version));
    CREATE TABLE app.students (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid UNIQUE NOT NULL REFERENCES app.users,
      student_code text NOT NULL, full_name text NOT NULL, curriculum_id uuid NOT NULL REFERENCES app.curricula,
      cohort text NOT NULL, domain_id text NOT NULL CHECK(domain_id='demo_academic'),
      data_origin text NOT NULL CHECK(data_origin='synthetic'), academic_revision integer NOT NULL DEFAULT 1,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(domain_id,student_code));
    CREATE TABLE app.advisor_assignments (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), advisor_user_id uuid NOT NULL REFERENCES app.users,
      student_id uuid NOT NULL REFERENCES app.students, UNIQUE(advisor_user_id,student_id));
    CREATE TABLE app.semesters (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text UNIQUE NOT NULL,
      start_date date NOT NULL, end_date date NOT NULL CHECK(end_date>=start_date));
    CREATE TABLE app.courses (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code text NOT NULL, title text NOT NULL,
      domain_id text NOT NULL CHECK(domain_id='demo_academic'), UNIQUE(domain_id,code));
    CREATE TABLE app.curriculum_courses (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), curriculum_id uuid NOT NULL REFERENCES app.curricula,
      course_id uuid NOT NULL REFERENCES app.courses, credits numeric(18,6) NOT NULL CHECK(credits>0),
      required boolean NOT NULL DEFAULT true, recommended_term_no integer NOT NULL,
      UNIQUE(curriculum_id,course_id));
    CREATE TABLE app.prerequisites (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), curriculum_id uuid NOT NULL REFERENCES app.curricula,
      course_id uuid NOT NULL REFERENCES app.courses, prerequisite_course_id uuid NOT NULL REFERENCES app.courses,
      min_grade_point numeric(18,6) NOT NULL DEFAULT 1.6,
      CHECK(course_id<>prerequisite_course_id), UNIQUE(curriculum_id,course_id,prerequisite_course_id));
    CREATE TABLE app.course_offerings (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), course_id uuid NOT NULL REFERENCES app.courses,
      semester_id uuid NOT NULL REFERENCES app.semesters, policy_id uuid NOT NULL REFERENCES app.grading_policies,
      credits numeric(18,6) NOT NULL CHECK(credits>0), is_open boolean NOT NULL DEFAULT false,
      UNIQUE(course_id,semester_id));
    CREATE TABLE app.enrollments (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), student_id uuid NOT NULL REFERENCES app.students,
      offering_id uuid NOT NULL REFERENCES app.course_offerings, course_id uuid NOT NULL REFERENCES app.courses,
      attempt_no integer NOT NULL CHECK(attempt_no>0), status text NOT NULL CHECK(status IN ('graded','pending','incomplete','withdrawn','exempt','P','F')),
      final_score numeric(18,6) CHECK(final_score BETWEEN 0 AND 10),
      recognized boolean NOT NULL DEFAULT false, minimums_met boolean NOT NULL DEFAULT true,
      finalized_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
      CHECK((status='graded')=(final_score IS NOT NULL)),
      UNIQUE(student_id,offering_id), UNIQUE(student_id,course_id,attempt_no));
    CREATE TABLE app.assessment_components (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), offering_id uuid NOT NULL REFERENCES app.course_offerings,
      code text NOT NULL, weight numeric(18,6) NOT NULL CHECK(weight>0 AND weight<=1),
      max_score numeric(18,6) NOT NULL DEFAULT 10 CHECK(max_score=10),
      minimum_required numeric(18,6) NOT NULL DEFAULT 0 CHECK(minimum_required BETWEEN 0 AND 10),
      UNIQUE(offering_id,code));
    CREATE TABLE app.grade_components (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), enrollment_id uuid NOT NULL REFERENCES app.enrollments,
      component_id uuid NOT NULL REFERENCES app.assessment_components,
      score numeric(18,6) NOT NULL CHECK(score BETWEEN 0 AND 10),
      observed_at timestamptz NOT NULL DEFAULT now(), available_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(enrollment_id,component_id));
    CREATE TABLE app.goals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), student_id uuid UNIQUE NOT NULL REFERENCES app.students,
      target_gpa numeric(18,6) NOT NULL CHECK(target_gpa BETWEEN 0 AND 4),
      target_graduation_semester_id uuid REFERENCES app.semesters, updated_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE app.chat_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES app.users,
      created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days');
    CREATE TABLE app.chat_messages (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id uuid NOT NULL REFERENCES app.chat_sessions,
      client_turn_id uuid NOT NULL, content text NOT NULL, result jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(session_id,client_turn_id));
    CREATE TABLE app.research_cases (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_user_id uuid NOT NULL REFERENCES app.users,
      source_case_key text NOT NULL, domain_id text NOT NULL CHECK(domain_id='oulad'),
      data_origin text NOT NULL CHECK(data_origin='public_dataset'),
      UNIQUE(owner_user_id,source_case_key));
    CREATE TABLE app.import_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid NOT NULL REFERENCES app.users,
      import_type text NOT NULL, input_hash text NOT NULL, status text NOT NULL,
      errors_json jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(actor_id,import_type,input_hash));
    CREATE TABLE app.audit_logs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid REFERENCES app.users,
      action text NOT NULL, entity_type text NOT NULL, entity_id text,
      status text NOT NULL, request_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    REVOKE UPDATE, DELETE ON app.audit_logs FROM advisor_app;
    CREATE INDEX ON app.enrollments(student_id);
    CREATE INDEX ON app.chat_sessions(user_id);
    CREATE INDEX ON app.refresh_sessions(expires_at);
    """)


def downgrade():
    raise RuntimeError("Destructive rollback requires explicit review; restore a reviewed backup instead.")
