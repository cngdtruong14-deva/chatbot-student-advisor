# CSV imports (DEMO-1 synthetic data)

Only an authenticated Admin may use these endpoints. Download the exact current
template from `GET /api/v1/admin/imports/templates/{type}` before preparing a
batch. Submit the same UTF-8 CSV first with `dry_run=true`; only a response with
`status=validated` may be submitted with `dry_run=false`.

Import dependency order is: `curricula` → `cohorts` and `semesters` → existing
student accounts plus `students` and `courses` → `curriculum_courses` and
`prerequisites` → `offerings` → `grade_components` → `enrollments` →
`grade_component_scores`.  Each child identifies its parent through stable code
(and curriculum/policy version where applicable), never database UUIDs.

`students` requires an existing active `app.users` account with role `student`.
CSV does not create, reset, or otherwise provision credentials. Provision that
account through the dedicated Admin/auth lifecycle, then import its
`account_email` linkage.

Every batch is validated in full before it writes. A dry run never writes
academic data or an import job. A committed batch is one transaction; errors
return `{line, code, field?}` and leave academic data unchanged. Replaying an
identical actor/type/input hash returns the original job without duplicate rows.
The server records actor, type, SHA-256 input hash and status; the frontend shows
the caller's import history. A transaction advisory lock and database unique
constraints protect concurrent retries.

Create/update behavior is idempotent by business key. Catalog fields may be
updated unless a domain rule rejects the row. A finalized enrollment or grade
component score cannot be silently changed: submit the same value again or use a
separate reviewed correction workflow. Any actual enrollment or component-score
mutation increments the affected student's `academic_revision` once per batch.

Prerequisites support DEMO-1 AND-only rules with a numeric minimum grade point.
Self references, duplicates, unresolved codes and cycles across existing plus
incoming edges are rejected. Component definitions must yield exactly total
weight `1.0` after considering the whole resulting offering. Scores resolve an
enrollment and component from the same offering.
