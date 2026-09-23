"""Account-owned transcript service. Self-reported dates never become ML events."""
from datetime import date
from decimal import Decimal, ROUND_CEILING
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from advisor_core import academic_policy_v2 as policy
from app.api import Actor, DTO, APIError, envelope, require_role, router
from app.responses import Envelope
from app.store import transaction, one, run

Credit = Annotated[Decimal, Field(gt=0, le=30, decimal_places=6, allow_inf_nan=False)]
Score = Annotated[Decimal, Field(ge=0, le=10, decimal_places=6, allow_inf_nan=False)]


class PersonalTerm(DTO):
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    start_date: date
    end_date: date

    @model_validator(mode='after')
    def dates(self):
        if self.end_date < self.start_date:
            raise ValueError('INVALID_TERM_DATES')
        return self


class PersonalAttempt(DTO):
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    title: str = Field(min_length=1, max_length=160)
    term: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    attempt: int = Field(ge=1, le=30, strict=True)
    credits: Credit
    status: Literal['graded', 'pending', 'absent_or_barred']
    score: Score | None = None
    available_on: date | None = None

    @field_validator('code')
    @classmethod
    def uppercase(cls, v):
        return v.upper()

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, v):
        if not v.strip():
            raise ValueError('EMPTY_COURSE_TITLE')
        return v.strip()

    @model_validator(mode='after')
    def result(self):
        if (self.status == 'graded') != (self.score is not None):
            raise ValueError('SCORE_STATUS_CONFLICT')
        if self.status == 'pending' and self.available_on is not None:
            raise ValueError('PENDING_HAS_NO_RESULT_DATE')
        return self


class PersonalTranscript(DTO):
    policy_version: Literal['ACADEMIC-DEMO-2.0.0'] = 'ACADEMIC-DEMO-2.0.0'
    terms: list[PersonalTerm] = Field(default_factory=list, max_length=50)
    attempts: list[PersonalAttempt] = Field(default_factory=list, max_length=500)
    # User-entered program total; never silently assume the synthetic 130 credits.
    required_credits: Annotated[Decimal, Field(gt=0, le=500, decimal_places=6, allow_inf_nan=False)] | None = None

    @model_validator(mode='after')
    def consistency(self):
        terms = {t.code: t for t in self.terms}
        if len(terms) != len(self.terms):
            raise ValueError('DUPLICATE_TERM')
        seen, credits, courses = set(), {}, {}
        for a in self.attempts:
            if a.term not in terms:
                raise ValueError('UNKNOWN_TERM')
            if (a.code, a.attempt) in seen:
                raise ValueError('DUPLICATE_ATTEMPT')
            seen.add((a.code, a.attempt))
            if a.code in credits and credits[a.code] != a.credits:
                raise ValueError('INCONSISTENT_COURSE_CREDITS')
            credits[a.code] = a.credits
            if a.available_on and (a.available_on < terms[a.term].start_date or a.available_on > date.today()):
                raise ValueError('INVALID_RESULT_DATE')
            courses.setdefault(a.code, []).append(a)
        for attempts in courses.values():
            ordered = sorted(attempts, key=lambda a: a.attempt)
            for earlier, later in zip(ordered, ordered[1:]):
                if terms[earlier.term].start_date > terms[later.term].start_date:
                    raise ValueError('ATTEMPT_TERM_ORDER_CONFLICT')
                if earlier.available_on and later.available_on and earlier.available_on > later.available_on:
                    raise ValueError('ATTEMPT_RESULT_ORDER_CONFLICT')
        return self


class TranscriptSave(DTO):
    expected_revision: int = Field(ge=0, strict=True)
    transcript: PersonalTranscript


class PersonalGoal(DTO):
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    target_gpa: Annotated[Decimal, Field(ge=0, le=4, allow_inf_nan=False)]
    future_gpa_credits: Annotated[Decimal, Field(ge=0, le=500, allow_inf_nan=False)]


class PersonalSimulation(TranscriptSave):
    pass


class TranscriptView(DTO):
    revision: int
    transcript: PersonalTranscript
    data_origin: Literal['self_reported'] = 'self_reported'


class DualSummary(DTO):
    gpa_4: str | None
    gpa_10: str | None
    gpa_credits: str
    quality_points_4: str
    quality_points_10: str
    earned_credits: str
    incomplete_courses: list[str]
    non_gpa_incomplete_courses: list[str]
    pending_attempts: int


class TermHistory(DTO):
    code: str
    term: DualSummary
    cumulative: DualSummary
    unknown_result_dates: int
    pending_results: int
    coverage: Literal['partial', 'complete']


class PersonalSummary(DTO):
    academic_revision: int
    policy_version: str = policy.POLICY_VERSION
    data_origin: Literal['self_reported'] = 'self_reported'
    summary: DualSummary
    required_credits: str | None
    remaining_credits: str | None
    semester_history: list[TermHistory]
    warnings: list[str]
    trend_4: str | None = None
    trend_10: str | None = None


class PersonalGoalResult(DTO):
    academic_revision: int
    data_origin: Literal['self_reported'] = 'self_reported'
    current_gpa: str | None
    target_gpa: str
    required_future_gpa: str | None
    feasibility: str
    assumptions: list[str]


class PersonalSimulationResult(DTO):
    academic_revision: int
    persisted: Literal[False] = False
    before: PersonalSummary
    after: PersonalSummary


class PersonalComponent(DTO):
    weight: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6, allow_inf_nan=False)]
    score: Score | None = None


class PersonalTarget(DTO):
    target_score: Score
    minimum_unknown_score: Score = Decimal(0)
    components: list[PersonalComponent] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def weights(self):
        if sum((c.weight for c in self.components), Decimal(0)) != 1:
            raise ValueError('WEIGHTS_MUST_SUM_TO_ONE')
        if sum(c.score is None for c in self.components) != 1:
            raise ValueError('EXACTLY_ONE_UNKNOWN_COMPONENT_REQUIRED')
        return self


class PersonalTargetResult(DTO):
    required_score: str
    feasibility: Literal['achievable', 'impossible']
    persisted: Literal[False] = False
    assumptions: list[str]


def calculate_target(body):
    known = sum((c.weight*c.score for c in body.components if c.score is not None), Decimal(0))
    missing = next(c for c in body.components if c.score is None)
    required = max(body.minimum_unknown_score, (body.target_score-known)/missing.weight)
    return PersonalTargetResult(required_score=format(required.quantize(Decimal('.000001'), rounding=ROUND_CEILING), 'f'),
        feasibility='impossible' if required > 10 else 'achievable', assumptions=[
            'Điểm thành phần và trọng số do bạn tự khai; tổng trọng số bằng 1.',
            'Chỉ có một thành phần chưa biết. Không suy đoán điểm thiếu hoặc điều kiện điểm sàn của trường.',
            'Điểm yêu cầu làm tròn lên 6 chữ số; chưa áp dụng quy tắc làm tròn tổng kết riêng của trường.'
        ])


@router.post('/account/target-score', response_model=Envelope[PersonalTargetResult])
def personal_target(body: PersonalTarget, user: Actor):
    require_role(user, 'student')
    return envelope(calculate_target(body).model_dump(mode='json'))


def calculate(attempts):
    normalized = [policy.normalize_attempt(course=a.code, attempt=a.attempt,
        credits=a.credits, score=a.score, gpa_bearing=a.code not in policy.NON_GPA_COURSES,
        status=a.status) for a in attempts if a.status != 'pending']
    summary = policy.summarize(normalized)
    return DualSummary(**{key: summary[key] for key in DualSummary.model_fields if key != 'pending_attempts'},
                       pending_attempts=sum(a.status == 'pending' for a in attempts))


def summarize(transcript, revision):
    current = calculate(transcript.attempts)
    history = []
    terms = {t.code: t for t in transcript.terms}
    for t in sorted(transcript.terms, key=lambda t: (t.end_date, t.code)):
        eligible = [a for a in transcript.attempts if a.available_on and a.available_on <= t.end_date
                    and terms[a.term].start_date <= t.end_date]
        unknown = sum(a.status != 'pending' and a.available_on is None and terms[a.term].end_date <= t.end_date
                      for a in transcript.attempts)
        pending = sum(a.status == 'pending' and terms[a.term].end_date <= t.end_date for a in transcript.attempts)
        history.append(TermHistory(code=t.code, term=calculate([a for a in eligible if a.term == t.code]),
            cumulative=calculate(eligible), unknown_result_dates=unknown, pending_results=pending,
            coverage='partial' if unknown or pending else 'complete'))
    required = transcript.required_credits
    # Only compare adjacent, fully covered, ended terms; do not bridge missing history.
    ended = [h for h in history if terms[h.code].end_date <= date.today()]
    deltas = {}
    if len(ended) >= 2 and all(h.coverage == 'complete' for h in ended[-2:]):
        before, after = ended[-2:]
        for scale in ('4', '10'):
            left, right = getattr(before.cumulative, 'gpa_'+scale), getattr(after.cumulative, 'gpa_'+scale)
            if left is not None and right is not None:
                deltas['trend_'+scale] = str(Decimal(right)-Decimal(left))
    return PersonalSummary(academic_revision=revision, summary=current,
        required_credits=str(required) if required is not None else None,
        remaining_credits=str(max(Decimal(0), required-Decimal(current.earned_credits))) if required is not None else None,
        semester_history=history, **deltas, warnings=[
            'Điểm và ngày công bố do bạn tự khai; chưa được trường xác minh.',
            'Áp dụng ACADEMIC-DEMO-2.0.0, chưa khẳng định là quy chế UTT chính thức.',
            'Lần có kết quả mới nhất thay lần cũ, kể cả điểm thấp hơn; lần đang chờ không thay điểm cũ.',
            'Không gán ngày cho kết quả thiếu ngày. Lịch sử chỉ dùng ngày công bố đã nhập.',
            'Tiến độ chỉ là tín chỉ đã đạt so với tổng tự khai, chưa xác minh chương trình/tiên quyết.',
        ])


def load(db, user):
    require_role(user, 'student')
    row = one(db, 'SELECT revision,payload FROM app.personal_transcripts WHERE user_id=:u', u=user['id'])
    return TranscriptView(revision=row['revision'], transcript=PersonalTranscript.model_validate(row['payload'])) if row else TranscriptView(revision=0, transcript=PersonalTranscript())


@router.get('/account/transcript', response_model=Envelope[TranscriptView])
def get_transcript(user: Actor):
    with transaction() as db:
        return envelope(load(db, user).model_dump(mode='json'))


@router.put('/account/transcript', response_model=Envelope[TranscriptView])
def save_transcript(body: TranscriptSave, user: Actor):
    require_role(user, 'student')
    with transaction() as db:
        profile = one(db, 'SELECT user_id FROM app.onboarding_profiles WHERE user_id=:u FOR UPDATE', u=user['id'])
        if not profile:
            raise APIError('PERSONAL_PROFILE_REQUIRED', 409, 'Hãy lưu hồ sơ cá nhân trước khi lưu bảng điểm.')
        current = load(db, user)
        if current.revision != body.expected_revision:
            raise APIError('ACADEMIC_REVISION_CONFLICT', 409, 'Bảng điểm đã đổi. Tải lại trước khi sửa.')
        revision = current.revision+1
        payload = body.transcript.model_dump_json()
        run(db, """INSERT INTO app.personal_transcripts(user_id,revision,policy_version,payload)
            VALUES(:u,:r,:p,CAST(:j AS jsonb)) ON CONFLICT(user_id) DO UPDATE SET
            revision=excluded.revision,payload=excluded.payload,updated_at=now()""",
            u=user['id'], r=revision, p=policy.POLICY_VERSION, j=payload)
        run(db, 'INSERT INTO app.personal_transcript_history(user_id,revision,payload) VALUES(:u,:r,CAST(:j AS jsonb))',
            u=user['id'], r=revision, j=payload)
        run(db, "INSERT INTO app.account_audit(actor_id,subject_id,action) VALUES(:u,:u,'personal_transcript_saved')", u=user['id'])
        return envelope(TranscriptView(revision=revision, transcript=body.transcript).model_dump(mode='json'))


@router.get('/account/academic-summary', response_model=Envelope[PersonalSummary])
def academic_summary(user: Actor):
    with transaction() as db:
        view = load(db, user)
        return envelope(summarize(view.transcript, view.revision).model_dump(mode='json'))


def project_average(user: Actor, assumed_gpa, future_gpa_credits):
    """Deterministic, non-persisted 4-point projection for chat orchestration."""
    require_role(user, 'student')
    with transaction() as db:
        view = load(db, user)
        before = summarize(view.transcript, view.revision)
    from advisor_core.academic_policy_v2 import project_gpa_4
    projection = project_gpa_4(before.summary.model_dump(), assumed_gpa, future_gpa_credits)
    after = before.model_copy(deep=True)
    after.summary.gpa_4 = projection['projected_gpa']
    after.summary.gpa_10 = None
    after.summary.gpa_credits = projection['projected_gpa_credits']
    after.summary.quality_points_4 = projection['projected_quality_points_4']
    return {
        'academic_revision': view.revision,
        'persisted': False,
        'before': before.model_dump(mode='json'),
        'after': after.model_dump(mode='json'),
        'projection': projection,
        'data_origin': 'self_reported',
        'policy_version': policy.POLICY_VERSION,
    }


@router.post('/account/required-gpa', response_model=Envelope[PersonalGoalResult])
def goal(body: PersonalGoal, user: Actor):
    with transaction() as db:
        view = load(db, user)
        if body.expected_revision is not None and body.expected_revision != view.revision:
            raise APIError('ACADEMIC_REVISION_CONFLICT', 409, 'Tải lại bảng điểm trước khi tính mục tiêu.')
        summary = calculate(view.transcript.attempts)
        result = policy.required_gpa(summary.model_dump(), body.target_gpa, body.future_gpa_credits)
        return envelope(PersonalGoalResult(academic_revision=view.revision,
            **{k: result[k] for k in ('current_gpa','target_gpa','required_future_gpa','feasibility','assumptions')}).model_dump(mode='json'))


@router.post('/account/simulations', response_model=Envelope[PersonalSimulationResult])
def simulate(body: PersonalSimulation, user: Actor):
    with transaction() as db:
        view = load(db, user)
        if view.revision != body.expected_revision:
            raise APIError('ACADEMIC_REVISION_CONFLICT', 409)
        return envelope(PersonalSimulationResult(academic_revision=view.revision,
            before=summarize(view.transcript, view.revision),
            after=summarize(body.transcript, view.revision)).model_dump(mode='json'))
