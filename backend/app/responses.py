"""Wire-compatible response DTOs. Decimal values remain six-place strings."""
from typing import Generic, TypeVar, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict

T = TypeVar('T')


class Extensible(BaseModel):
    model_config = ConfigDict(extra='allow')


class Meta(BaseModel):
    request_id: str
    contract_version: Literal['1.0.0']
    warnings: list[str]


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class RegistrationResult(BaseModel):
    registered: Literal[True]


class RecoveryResult(BaseModel):
    recovered: Literal[True]


class OneTimeAccountCode(BaseModel):
    code: str
    expires_at: datetime
    display_once: Literal[True]


class PersonalAccountProfile(BaseModel):
    display_name: str
    major: str
    cohort: str
    data_origin: Literal['self_reported']


class ProfileSaveResult(BaseModel):
    saved: Literal[True]
    data_origin: Literal['self_reported']


class AdminAccountItem(Extensible):
    id: str
    username: str | None
    email: str
    role: Literal['student', 'advisor', 'admin']
    is_active: bool
    created_at: datetime
    display_name: str | None
    self_reported_major: str | None
    self_reported_cohort: str | None
    personal_transcript_revision: int
    student_id: str | None
    student_code: str | None
    full_name: str | None
    curriculum_id: str | None
    curriculum_code: str | None
    curriculum_version: str | None
    curriculum_major: str | None
    cohort_id: str | None
    cohort_code: str | None
    advisor_count: int


class AdminAccountList(BaseModel):
    items: list[AdminAccountItem]


class CohortOption(BaseModel):
    id: str
    code: str
    curriculum_id: str
    curriculum_code: str
    curriculum_version: str
    major: str


class CohortCatalog(BaseModel):
    items: list[CohortOption]


class AdminAcademicProfileLinkResult(BaseModel):
    linked: Literal[True]
    idempotent: bool
    student_id: str
    student_code: str
    data_origin: Literal['synthetic']


class AdminAccountAuditItem(BaseModel):
    id: str
    action: str
    created_at: datetime
    actor: str | None
    subject: str | None


class AdminAccountAuditList(BaseModel):
    items: list[AdminAccountAuditItem]


class AdvisorAssignmentItem(BaseModel):
    advisor_user_id: str
    advisor_name: str
    student_id: str
    student_code: str
    student_name: str


class AdvisorAssignmentList(BaseModel):
    items: list[AdvisorAssignmentItem]


class AdvisorAssignmentResult(BaseModel):
    assigned: bool


class CurriculumOption(BaseModel):
    id: str
    code: str
    version: str
    major: str
    faculty: str | None
    total_required_credits: str
    status: str
    source_name: str | None
    source_sha256: str | None


class CurriculumCatalog(BaseModel):
    items: list[CurriculumOption]


class MajorOptions(BaseModel):
    majors: list[CurriculumOption]


class GPAResult(Extensible):
    cumulative_gpa: str | None
    quality_points: str
    gpa_credits: str


class SemesterResult(Extensible):
    semester_id: str
    semester_code: str | None
    term_gpa: str | None
    term_credits: str
    term_earned_credits: str
    cumulative_gpa: str | None
    cumulative_earned_credits: str
    snapshot_rule: str


class AcademicSummary(GPAResult):
    student_id: str
    curriculum_id: str
    academic_revision: int
    earned_credits: str
    required_credits: str
    remaining_required_credits: str
    failed_courses: list[str]
    semester_history: list[SemesterResult]
    transcript: list[dict]
    goal: dict | None
    policy_version: str
    data_origin: str
    domain_id: str


class RequiredGPA(Extensible):
    current_gpa: str | None
    target_gpa: str
    gap: str | None
    required_future_gpa: str | None
    feasibility: Literal['achievable', 'impossible', 'insufficient_data', 'completed_target_met', 'completed_target_not_met']
    gpa_scale_max: str
    policy_version: str
    data_origin: str
    assumptions: list[str]
    academic_revision: int


class TargetScore(Extensible):
    required_score: str
    max_score: str
    minimum_exam_score: str
    feasibility: Literal['achievable', 'impossible']
    policy_version: str
    data_origin: str


class Simulation(Extensible):
    before: GPAResult
    after: GPAResult
    academic_revision: int
    persisted: Literal[False]
    policy_version: str
    data_origin: str
    assumptions: list[str]


class ChatCard(Extensible):
    # str intentionally permits replay of historical pre-alignment cards.
    # New dispatch outputs are checked against the approved six-type allowlist.
    type: str
    data: dict | list


class ChatTurn(Extensible):
    turn_id: str
    status: Literal['completed', 'needs_clarification', 'failed']
    answer: str
    cards: list[ChatCard]
    citations: list[dict]
    provider_status: str
    follow_up_question: str | None = None


class ChatSession(Extensible):
    id: str
    expires_at: str


class RAGFeedback(Extensible):
    saved: Literal[True]
    label: Literal['helpful', 'not_helpful', 'incorrect_citation']
    expires_at: datetime
    replayed: bool


class ResearchCase(Extensible):
    id: str
    source_case_key: str
    domain_id: Literal['oulad', 'academic_demo_v2']
    data_origin: Literal['public_dataset', 'synthetic']


class ResearchCasePage(Extensible):
    items: list[ResearchCase]
    next_cursor: str | None


class ResearchPrediction(Extensible):
    id: str
    created_at: datetime
    domain_id: Literal['oulad', 'academic_demo_v2']
    data_origin: Literal['public_dataset', 'synthetic']
    model_id: str
    model_version: str
    probability: float
    threshold: float
    risk_label: Literal['at_risk', 'not_at_risk']
    disclaimer: str


class ResearchDashboard(Extensible):
    domain_id: Literal['academic_demo_v2']
    data_origin: Literal['synthetic']
    expected_case_count: int
    case_count: int
    snapshot_count: int
    prediction_count: int
    at_risk_count: int
    not_at_risk_count: int
    average_probability: float | None
    coverage_status: Literal['complete', 'partial', 'empty']
    model_versions: list[dict]
    limitations: list[str]


class Recommendations(Extensible):
    selected: list[dict]
    eligible: list[dict]
    excluded: list[dict]
    total_credits: str
    policy_version: str
    data_origin: str
    algorithm: str
    assumptions: list[str]
    is_optimal: Literal[False]
