/** Generated-facing API shapes. Regenerate from /openapi.json before release. */
export type DecimalString = string;
export interface TranscriptRow { id: string; offering_id: string; course_id: string; code: string; title: string; credits: DecimalString; attempt_no: number; status: string; final_score: DecimalString | null; }
export interface SemesterSnapshot { semester_id: string; term_gpa: DecimalString | null; cumulative_gpa: DecimalString | null; term_credits: DecimalString; cumulative_earned_credits: DecimalString; snapshot_rule: string; }
export interface AcademicSummary { student_id: string; academic_revision: number; cumulative_gpa: DecimalString | null; earned_credits: DecimalString; required_credits: DecimalString; gpa_credits: DecimalString; remaining_required_credits: DecimalString; transcript: TranscriptRow[]; semester_history: SemesterSnapshot[]; trend: { state: string; delta: DecimalString | null }; assumptions: string[]; }
export interface Simulation { before: Pick<AcademicSummary, "cumulative_gpa" | "earned_credits" | "gpa_credits">; after: Record<string, DecimalString | null>; academic_revision: number; persisted: false; assumptions: string[]; }
