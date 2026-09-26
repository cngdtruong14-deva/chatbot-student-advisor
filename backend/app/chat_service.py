"""Bounded deterministic orchestration. No private academic data goes to a provider."""
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid4
from pydantic import ValidationError

TOOLS = frozenset({'academic_summary', 'required_gpa', 'target_score', 'simulate',
                   'course_result', 'course_recommendations', 'catalog', 'predict', 'explain',
                   'career', 'knowledge_search'})
NUMBER = r'(?<![\w.+-])[+-]?\d+(?:[.,]\d+)?(?![\w.])'
CREDIT = '(' + NUMBER + r')\s*tin(?:\s*chi)?\b'
CONTEXT_TTL_MINUTES = 15
CONTEXT_MAX_TURNS = 3
LETTER_GPA = {'a': '4', 'b+': '3.5', 'b': '3', 'c+': '2.5', 'c': '2',
              'd+': '1.5', 'd': '1', 'f': '0'}
RAG_TOPICS = (
    ('scholarship', ('hoc bong', 'mien giam hoc phi', 'ho tro tai chinh')),
    ('career', ('nghe nghiep', 'dinh huong nghe', 'ky nang nghe', 'skill gap', 'lo trinh nghe')),
    ('partner_jobs', ('viec lam', 'tuyen dung', 'doanh nghiep', 'doi tac', 'thuc tap')),
)
logger = logging.getLogger('advisor.chat')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if unicodedata.category(c) != 'Mn').replace('đ', 'd')


def canonical_student_text(text):
    """Apply only reviewed academic aliases; unknown slang remains untouched."""
    value = normalize(text)
    value = re.sub(r'\bkqht\b', 'ket qua hoc tap', value)
    value = re.sub(r'\bsv\b', 'sinh vien', value)
    value = re.sub(r'(' + NUMBER + r')\s*tin\b', r'\1 tin chi', value)
    return value


def _policy_question(text):
    return any(pattern in text for pattern in (
        'co tinh vao gpa', 'co tinh gpa', 'tinh vao gpa', 'dieu kien tot nghiep',
        'co tot nghiep', 'duoc tot nghiep', 'cong nhan tot nghiep',
        'bao luu ket qua hoc tap', 'nghi hoc tam thoi',
    ))


def gpa_planning_intent(text):
    """Score GPA goal-seeking and forward-projection structure.

    A single word such as ``mo phong`` must not win merely because its branch
    appears first. Strong question structure wins; close competing signals are
    returned as ambiguous so dispatch can ask the user to distinguish the two
    mathematically different operations.
    """
    t = canonical_student_text(text)
    if ('gpa' not in t and not any(term in t for term in (
            'trung binh', 'mo phong', 'what-if', 'gia dinh', 'gia su', 'keo ', 'nang ', 'cham '))):
        return None
    required_score = 0
    simulate_score = 0

    if re.search(r'\b(?:can|phai)\b.*\b(?:bao nhieu|trung binh(?: may| bao nhieu)?)\b', t):
        required_score += 6
    if re.search(r'\b(?:bao nhieu|trung binh bao nhieu)\b.*\b(?:de|cho)\b.*\b(?:dat|cham|len)\b', t):
        required_score += 6
    if any(term in t for term in ('dat muc tieu gpa', 'muc tieu gpa', 'gpa muc tieu')):
        required_score += 4
    if re.search(r'\b(?:keo|nang)\b.*\bgpa\b', t):
        required_score += 3
    if re.search(r'\bde\b.*\b(?:dat|cham|len)\b.*\bgpa\b', t):
        required_score += 3

    if re.search(r'\bneu\b.+\b(?:thi|se|thanh|ra|the nao|bao nhieu)\b', t):
        simulate_score += 6
    if any(term in t for term in ('gia dinh', 'gia su', 'what-if')):
        simulate_score += 3
    if 'mo phong' in t:
        simulate_score += 2
    if re.search(r'\bgpa\b.*\b(?:se|thanh|du kien)\b.*\b(?:bao nhieu|the nao|may)\b', t):
        simulate_score += 3

    if required_score and simulate_score and abs(required_score - simulate_score) <= 1:
        selected = 'gpa_plan_ambiguous'
    elif required_score > simulate_score:
        selected = 'required_gpa'
    elif simulate_score:
        selected = 'simulate'
    else:
        selected = None
    if required_score or simulate_score:
        # Privacy boundary: record routing metadata, never the student's text.
        logger.info('gpa_intent selected=%s required_score=%s simulate_score=%s',
                    selected, required_score, simulate_score)
    return selected


def intent(text):
    t = canonical_student_text(text)
    # Policy questions containing the word GPA must not be hijacked by the
    # personal GPA summary tool.
    if _policy_question(t):
        return 'knowledge_search'
    if any(term in t for term in (
        'nghe nghiep', 'dinh huong nghe', 'ky nang nghe', 'skill gap', 'lo trinh nghe',
        'phu hop nghe nao', 'nghe nao phu hop', 'phu hop voi nghe nao',
        'business analyst', 'systems analyst', 'system analyst', 'data analyst',
        'erp functional consultant', 'tu van erp', 'database administrator',
        'quan tri csdl', 'it project coordinator', 'dieu phoi du an',
    )):
        return 'career'
    if any(term in t for term in ('diem thi', 'qua mon')):
        return 'target_score'
    # Resolve an explicit course-result question before looking for simulation
    # keywords. Course titles can legitimately contain words such as "mo phong".
    if (any(term in t for term in ('diem mon', 'diem hoc phan', 'ket qua mon', 'ket qua hoc phan', 'ten mon', 'ma mon'))
            or re.search(r'\bmon\b.+\b(?:bao nhieu diem|duoc may diem|duoc bao nhieu|ket qua(?: the nao)?)\b', t)
            or re.search(r'\b[a-z]{2,}[a-z0-9_-]*\d[a-z0-9_-]*\b.+\b(?:duoc may|duoc bao nhieu|ket qua)\b', t)):
        return 'course_result'
    planning_intent = gpa_planning_intent(t)
    if planning_intent:
        return planning_intent
    if (any(term in t for term in ('mo phong', 'what-if', 'gia dinh', 'gia su', 'neu duoc', 'neu dat'))
            or ('neu ' in t and any(term in t for term in ('mon con lai', 'tin chi', 'deu a', 'deu b', '/10')))):
        return 'simulate'
    if (('gpa' in t and any(term in t for term in ('keo ', 'len ', 'cham ', 'trung binh bao nhieu')))
            or ('tin chi' in t and 'trung binh bao nhieu' in t and any(term in t for term in ('cham ', 'dat ', 'len ')))):
        return 'required_gpa'
    for tool, terms in [
        ('required_gpa', ('muc tieu gpa', 'gpa muc tieu', 'can bao nhieu gpa', 'can dat gpa', 'dat gpa', 'gpa tuong lai')),
        ('course_recommendations', ('goi y mon', 'dang ky mon', 'mon nen hoc', 'khuyen nghi mon', 'mon mo ky')),
        ('catalog', ('chuong trinh dao tao', 'khung dao tao', 'mon tien quyet', 'danh muc mon')),
        ('explain', ('giai thich du doan', 'giai thich rui ro')),
        ('predict', ('du doan', 'nguy co', 'rui ro')),
        ('academic_summary', ('gpa', 'cpa', 'bang diem', 'xem diem', 'diem cua toi', 'ket qua hoc tap', 'lich su hoc ky', 'diem tung ky', 'qua trinh hoc tap', 'tien do hoc tap', 'xu huong diem', 'thieu bao nhieu tin')),
    ]:
        if any(term in t for term in terms):
            return tool
    return 'knowledge_search'


def knowledge_topic(text):
    normalized = normalize(text)
    for topic, terms in RAG_TOPICS:
        if any(term in normalized for term in terms):
            return topic
    return 'university_policy'


def policy_anchor(text):
    value = canonical_student_text(text)
    if 'hoc bong' in value:
        return 'scholarship'
    if any(term in value for term in ('tot nghiep', 'ra truong')):
        return 'graduation'
    if 'hoc lai' in value:
        return 'retake'
    if any(term in value for term in ('bao luu', 'nghi hoc tam thoi')):
        return 'temporary_leave'
    if any(term in value for term in ('chuan dau ra', 'tin hoc', 'ngoai ngu')):
        return 'outcome_standard'
    return None


def retrieval_fallback_answer(citations, generation_status):
    """Return safe, extractive evidence while the semantic provider is unavailable.

    This deliberately does not join or reinterpret claims. The user receives a
    short, labelled excerpt list and can open the cited source card. It prevents
    a provider timeout from looking like a chatbot crash while preserving the
    fail-closed rule for unsupported conclusions.
    """
    status_label = {
        'timeout': 'Gemini chưa phản hồi kịp',
        'rate_limited': 'Gemini đang quá tải',
        'authentication_error': 'Dịch vụ diễn đạt chưa xác thực được',
        'provider_unavailable': 'Dịch vụ diễn đạt chưa sẵn sàng',
        'provider_error': 'Dịch vụ diễn đạt chưa trả về định dạng hợp lệ',
    }.get(generation_status, 'Dịch vụ diễn đạt chưa trả lời')
    lines = [f'{status_label}. Tôi chưa tự kết luận; dưới đây là trích đoạn trực tiếp để đối chiếu:']
    for index, citation in enumerate((citations or [])[:3], start=1):
        excerpt = ' '.join(str(citation.get('excerpt') or '').split())
        if not excerpt:
            continue
        if len(excerpt) > 360:
            excerpt = excerpt[:357].rsplit(' ', 1)[0] + '…'
        title = citation.get('title') or citation.get('source') or 'Tài liệu UTT'
        locator = citation.get('locator_label') or citation.get('section') or 'trích đoạn'
        lines.append(f'[{index}] {title} — {locator}: {excerpt}')
    return '\n'.join(lines)


def _active_context(previous):
    context = (previous or {}).get('context')
    if not isinstance(context, dict):
        return {}
    expires = context.get('expires_at')
    if expires:
        try:
            if datetime.fromisoformat(str(expires).replace('Z', '+00:00')) <= datetime.now(timezone.utc):
                return {}
        except ValueError:
            return {}
    if context.get('mode') == 'memory' and int(context.get('turns_left', 0)) <= 0:
        return {}
    return context


def _context_payload(tool, *, mode, params=None, topic=None, anchor=None, turns_left=None):
    payload = {
        'mode': mode,
        'tool': tool,
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=CONTEXT_TTL_MINUTES)).isoformat(),
    }
    if params:
        payload['params'] = params
    if topic:
        payload['topic'] = topic
    if anchor:
        payload['anchor'] = anchor
    if mode == 'clarification':
        payload['rounds'] = 0
    else:
        payload['turns_left'] = CONTEXT_MAX_TURNS if turns_left is None else max(0, turns_left)
    return payload


def _ambiguous_reference(text):
    return any(term in text for term in (
        'quy dinh do', 'dieu kien do', 'dieu kien ay', 'cai dieu kien ay',
        'cai do', 'quy dinh nay', 'dieu kien nay',
    ))


def is_followup_text(text):
    value = canonical_student_text(text)
    if not re.fullmatch(r'[\w\s.,?!:=/-]+', value):
        return False
    return bool(
        re.fullmatch(NUMBER, value.strip()) or 'tin chi' in value
        or re.match(r'lan\s+\d+\b', value.strip())
        or value.strip() in {'khong biet', 'chua biet'}
        or value.startswith('y em la ')
        or re.fullmatch(r'[a-z][a-z0-9_-]*\d[\w -]*(?:[.,]\d+)?', value.strip())
    )


def rewrite_policy_query(message, text, *, topic, anchor=None):
    """Bounded query expansion; it never creates facts or changes corpus scope."""
    if anchor == 'scholarship' and 'hoc bong' not in text:
        return 'Về học bổng khuyến khích học tập: ' + message
    if anchor == 'graduation' and 'tot nghiep' not in text:
        return 'Về điều kiện công nhận tốt nghiệp: ' + message
    if anchor == 'retake' and 'hoc lai' not in text:
        return 'Về quy định học lại và cách tính điểm học lại: ' + message
    if 'ra truong' in text:
        return 'Điều kiện công nhận tốt nghiệp tại UTT.'
    if 'bao luu' in text and ('ket qua hoc tap' in text or 'nghi mot ky' in text):
        return 'Điều kiện và thủ tục xin nghỉ học tạm thời, bảo lưu kết quả học tập và tiếp tục học trở lại.'
    if topic == 'scholarship' and any(term in text for term in ('khong duoc xet', 'khong du dieu kien', 'bi loai')):
        return 'Điều kiện được xét học bổng khuyến khích học tập và các trường hợp không đủ điều kiện.'
    return message


def display_number(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return str(value)
    return format(number, 'f').rstrip('0').rstrip('.') or '0'


def letter_gpa(text):
    match = re.search(r'(?<!\w)(?:diem\s+|duoc\s+(?:diem\s+)?|duoc\s+toan\s+|dat\s+(?:diem\s+)?|deu\s+|toan\s+)(a|b\+|b|c\+|c|d\+|d|f)(?![+\-\w])', text)
    return (match[1].upper(), LETTER_GPA[match[1]], match.span()) if match else None


def future_average(text):
    credit = re.search(CREDIT, text)
    grade = letter_gpa(text)
    if not credit:
        return None
    remaining = text[:credit.start()] + text[credit.end():]
    if grade:
        # Re-find after removing credits because spans refer to the original.
        grade_remaining = letter_gpa(remaining)
        if grade_remaining:
            remaining = remaining[:grade_remaining[2][0]] + remaining[grade_remaining[2][1]:]
        return {'credits': credit[1].replace(',', '.'), 'value': grade[1], 'grade_label': grade[0]}
    values = re.findall(NUMBER, remaining)
    return {'credits': credit[1].replace(',', '.'), 'value': values[0].replace(',', '.')} if len(values) == 1 else None


def course_result(rows, text, clarify, result):
    courses = {}
    for row in rows:
        code, title = str(row.get('code') or '').strip(), str(row.get('title') or '').strip()
        if code:
            courses.setdefault((code, title), []).append(row)
    code_matches = [key for key in courses if re.search(r'(?<!\w)' + re.escape(normalize(key[0])) + r'(?!\w)', text)]
    title_matches = [key for key in courses if key[1] and normalize(key[1]) in text]
    matches = code_matches or title_matches
    if not matches:
        return clarify('Không tìm thấy môn trong bảng điểm của bạn. Hãy nhập đúng mã môn hoặc đầy đủ tên môn.')
    if len(matches) > 1:
        return clarify('Tên môn khớp nhiều kết quả. Hãy nhập mã môn: ' + ', '.join(sorted(key[0] for key in matches)))
    code, title = matches[0]
    attempts = sorted(courses[(code, title)], key=lambda row: int(row.get('attempt_no', row.get('attempt', 0))))
    requested_attempt = re.search(r'\blan\s+(\d+)\b', text)
    if requested_attempt:
        attempts = [row for row in attempts if int(row.get('attempt_no', row.get('attempt', 0))) == int(requested_attempt[1])]
        if not attempts:
            return clarify(f'Không tìm thấy lần học {requested_attempt[1]} của môn {code} trong bảng điểm của bạn.')
    details = []
    for row in attempts:
        attempt = row.get('attempt_no', row.get('attempt'))
        score = row.get('final_score', row.get('score'))
        term = row.get('semester_code', row.get('term'))
        status = row.get('status')
        shown_score = f"{display_number(score)}/10" if score is not None else ('chưa có điểm' if status == 'pending' else 'vắng/cấm thi')
        suffix = ' · '.join(part for part in (f'lần {attempt}' if attempt else None,
                            f'{display_number(row.get("credits"))} tín chỉ' if row.get('credits') is not None else None,
                            str(term) if term else None) if part)
        details.append(f'{shown_score}' + (f' · {suffix}' if suffix else ''))
    result.update(status='completed', answer=f'{code} — {title}: ' + '; '.join(details))
    result['context'] = _context_payload('course_result', mode='memory',
        params={'course_code': code}, anchor='course_result')
    return result


def dispatch(message, user, previous=None, corpus_scope='demo_academic'):
    # Lazy import allows API and chat to share services and authorization unchanged.
    from app import api as a
    tool, text = intent(message), canonical_student_text(message)
    context = _active_context(previous)
    clarification_context = context if context.get('mode') in (None, 'clarification') and (previous or {}).get('status') == 'needs_clarification' else {}
    memory_context = context if context.get('mode') == 'memory' else {}
    source_reply = text.strip() in {'tu khai', 'bang diem ca nhan', 'ho so demo', 'ho so mo phong'}
    followup = is_followup_text(text)
    if (source_reply or (tool == 'knowledge_search' and followup)) and clarification_context.get('tool') in TOOLS:
        tool = clarification_context['tool']
    elif memory_context and (_ambiguous_reference(text) or followup or text.startswith(('con ', 'neu '))):
        tool = memory_context.get('tool', tool)
    params_context = clarification_context if clarification_context.get('tool') == tool else memory_context
    params = dict(params_context.get('params', {})) if params_context.get('tool') == tool else {}
    if tool == 'course_result' and params.get('course_code') and not re.search(r'\b[a-z]{2,}[a-z0-9_-]*\d', text):
        text += ' ' + normalize(params['course_code'])
    result = {'turn_id': str(uuid4()), 'status': 'needs_clarification', 'answer': '',
              'cards': [], 'citations': [], 'provider_status': 'not_required', 'follow_up_question': None}

    def clarify(answer):
        rounds = int(clarification_context.get('rounds', 0)) + 1 if clarification_context.get('tool') == tool else 1
        if rounds > 4:
            result.update(answer='Chưa đủ thông tin sau 4 lượt làm rõ. Hãy gửi lại yêu cầu đầy đủ hoặc dùng biểu mẫu học vụ.', follow_up_question=None)
            return result
        payload = _context_payload(tool, mode='clarification', params=a.clean(params))
        payload['rounds'] = rounds
        result.update(answer=answer, follow_up_question=answer, context=payload)
        return result

    def done(kind, data, answer):
        kind = {'required_gpa': 'goal_analysis', 'target_score': 'goal_analysis',
                'simulate': 'simulation', 'prediction_explanation': 'prediction'}.get(kind, kind)
        result.update(status='completed', answer=answer, cards=[{'type': kind, 'data': a.clean(data)}])
        return result

    if text.strip() in {'huy', 'huy yeu cau', 'bat dau lai'}:
        result.update(status='completed', answer='Đã hủy yêu cầu đang làm rõ. Bạn muốn hỏi gì tiếp theo?')
        return result
    if re.search(r'bo qua quy tac|ignore previous instructions|student_id|diem cua (ban|sinh vien)', text):
        params.clear()
        return clarify('Hệ thống chỉ cung cấp dữ liệu học vụ của chính tài khoản bạn đã đăng nhập. Hãy hỏi về hồ sơ của bạn.')
    if tool == 'gpa_plan_ambiguous':
        return clarify('Câu hỏi có thể hiểu theo hai cách. Hãy ghi rõ một trong hai: “cần đạt trung bình bao nhiêu trong 45 tín chỉ để GPA đạt 3.2”, hoặc “nếu 45 tín chỉ đạt trung bình 3.2 thì GPA dự kiến là bao nhiêu”.')
    if tool == 'career':
        from app.career import career_matches, career_requirements, list_careers, resolve_career, student_skill_gap
        career_code = resolve_career(message) or params.get('career_code')
        personalized = any(term in text for term in (
            'toi', 'cua toi', 'em ', 'cua em', 'phu hop', 'thieu gi', 'con thieu',
            'nen hoc', 'khoang cach ky nang', 'skill gap',
        ))
        ranking = any(term in text for term in ('phu hop nghe nao', 'nghe nao phu hop', 'dinh huong nao phu hop'))
        with a.transaction() as db:
            careers = list_careers(db)
            if ranking:
                if user['role'] != 'student':
                    return clarify('Xếp hạng mức phù hợp cần hồ sơ sinh viên của chính tài khoản đăng nhập.')
                student = a.own_student(db, user)
                data = career_matches(db, student)
                if data['data_status'] == 'insufficient_evidence':
                    answer = ('Chưa có đủ điểm các học phần HTTT đã đạt để xếp hạng cá nhân. '
                              'Bạn có thể nhập điểm HTTT hoặc hỏi yêu cầu của một nghề cụ thể.')
                else:
                    top = data['matches'][:3]
                    answer = 'Mức phủ kỹ năng cao nhất theo dữ liệu demo: ' + '; '.join(
                        f"{item['career']['title']} {display_number(item['match_score'])}%" for item in top)
                    answer += '. Đây là mức phủ yêu cầu trong bộ dữ liệu đã duyệt, không phải xác suất tuyển dụng.'
                return done('career_matches', data, answer)
            if not career_code:
                params['career_choices'] = [row['career_code'] for row in careers]
                choices = '; '.join(f"{row['career_code']} — {row['title']}" for row in careers)
                return clarify('Hãy chọn một định hướng để xem kỹ năng: ' + choices + '.')
            params['career_code'] = career_code
            if personalized:
                if user['role'] != 'student':
                    return clarify('Phân tích khoảng cách kỹ năng chỉ dùng hồ sơ của sinh viên đang đăng nhập.')
                student = a.own_student(db, user)
                data = student_skill_gap(db, student, career_code)
                if not data:
                    return clarify('Không tìm thấy định hướng nghề nghiệp đã duyệt.')
                if data['data_status'] == 'insufficient_evidence':
                    answer = (f"Chưa có đủ điểm học phần HTTT đã đạt để chấm mức phủ cho {data['career']['title']}. "
                              'Hệ thống không coi dữ liệu chưa có là kỹ năng bằng 0.')
                else:
                    answer = (f"Mức phủ kỹ năng {data['career']['title']}: {display_number(data['match_score'])}%. "
                              f"Có bằng chứng cho {len(data['strong_skills'])} kỹ năng; còn {len(data['missing_skills'])} kỹ năng chưa có bằng chứng từ môn đã đạt. "
                              'Đây không phải xác suất được tuyển dụng.')
                return done('career_skill_gap', data, answer)
            data = career_requirements(db, career_code)
            if not data:
                return clarify('Không tìm thấy định hướng nghề nghiệp đã duyệt.')
            top = data['skills'][:4]
            answer = f"{data['career']['title']} cần các kỹ năng trọng tâm: " + '; '.join(
                f"{row['skill_name']} ({display_number(Decimal(str(row['importance_weight'])) * 100)}%)" for row in top)
            answer += '. Danh sách là dữ liệu demo đã được owner duyệt; RAG không tham gia tính toán.'
            return done('career_requirements', data, answer)
    if tool == 'knowledge_search':
        from app.knowledge import search, resolve_actor_scope
        prior_anchor = memory_context.get('anchor') if memory_context.get('tool') == 'knowledge_search' else None
        prior_topic = memory_context.get('topic') if memory_context.get('tool') == 'knowledge_search' else None
        if _ambiguous_reference(text) and not prior_anchor:
            return clarify('Bạn đang nói đến quy định hoặc điều kiện nào? Hãy nêu rõ chủ đề, ví dụ: học bổng, học lại, bảo lưu hay tốt nghiệp.')
        topic = prior_topic or knowledge_topic(message)
        anchor = prior_anchor or policy_anchor(message)
        search_query = rewrite_policy_query(message, text, topic=topic, anchor=prior_anchor)
        scope = resolve_actor_scope(user) if corpus_scope == 'utt_corpus' else {'major': None, 'cohort': None, 'resolved': True}
        student_major = scope['major'] if scope['resolved'] else None
        student_cohort = scope['cohort'] if scope['resolved'] else None

        # Check cross-major mismatch: student asks about a different major's specific regulation
        major_keywords = {
            'xay dung': 'Kỹ thuật Xây dựng',
            'logistics': 'Logistics & Quản lý Chuỗi cung ứng',
            'co khi': 'Kỹ thuật Cơ khí',
            'oto': 'Kỹ thuật Ô tô',
            'kinh te': 'Kinh tế / Kế toán',
            'dien tu': 'Điện tử Viễn thông',
        }
        detected_other_major = None
        if student_major and 'cntt' in student_major.lower():
            for kw, mname in major_keywords.items():
                if kw in text:
                    detected_other_major = mname
                    break

        try:
            evidence = {**search(search_query, corpus_scope=corpus_scope, major=scope['major'], cohort=scope['cohort']),
                        'topic': topic, 'query_rewrite_applied': search_query != message}
        except (TimeoutError, ConnectionError):
            result.update(status='failed', provider_status='provider_unavailable',
                answer='Kho tài liệu tạm thời không phản hồi. Chưa có bằng chứng để trả lời; bạn có thể thử lại. Các công cụ tính GPA vẫn độc lập.')
            return result
        if evidence.get('retrieval_status') == 'unavailable':
            result.update(status='failed', provider_status='retrieval_unavailable',
                answer='Kho tìm kiếm tài liệu tạm thời chưa sẵn sàng. Không thể kết luận tài liệu không có câu trả lời. Hãy thử lại sau; công cụ GPA vẫn dùng được.')
            return result
        answered = evidence['status'] == 'answered'
        fallback = {
            'timeout': 'Dịch vụ diễn đạt phản hồi chậm. Bạn có thể đọc trích đoạn bên dưới hoặc gửi lại câu hỏi sau.',
            'rate_limited': 'Dịch vụ diễn đạt đang hết hạn mức. Bạn vẫn có thể đọc các trích đoạn bên dưới.',
            'authentication_error': 'Dịch vụ diễn đạt chưa kết nối được. Vui lòng báo quản trị viên kiểm tra cấu hình.',
            'provider_unavailable': 'Dịch vụ diễn đạt chưa được bật. Bạn có thể tham khảo các trích đoạn bên dưới.',
            'provider_error': 'Chưa tạo được câu trả lời hợp lệ có trích dẫn. Bạn có thể đọc nguồn bên dưới hoặc thử lại.',
        }.get(evidence['generation_status'])

        topic_names = {'scholarship': 'học bổng', 'career': 'hướng nghiệp và kỹ năng',
                       'partner_jobs': 'đối tác, thực tập hoặc việc làm', 'university_policy': 'học vụ'}
        extractive_fallback = (
            retrieval_fallback_answer(evidence['citations'], evidence['generation_status'])
            if evidence.get('citations') and evidence.get('generation_status') in {
                'timeout', 'rate_limited', 'authentication_error', 'provider_unavailable',
                'provider_error', 'insufficient_evidence'
            } else None
        )
        answer_text = evidence['answer'] if answered else (extractive_fallback or fallback or (
            'Tìm thấy trích đoạn liên quan, nhưng chưa đủ để khẳng định câu trả lời.' if evidence['citations']
            else f'Chưa có bằng chứng về {topic_names[topic]} trong các tài liệu đã được admin kích hoạt.'))
        if answered and evidence.get('rag_mode') == 'approved_grounded_capstone_high_stakes':
            answer_text += ('\n\nLưu ý: Đây là nội dung học vụ quan trọng được tổng hợp từ tài liệu có dẫn nguồn. '
                            'Hãy mở văn bản gốc và liên hệ đơn vị phụ trách trước khi đưa ra quyết định.')
        if topic == 'career':
            answer_text += '\n\nĐây là tra cứu tài liệu hướng nghiệp. Hệ thống chưa tự chấm mức phù hợp hoặc khoảng cách kỹ năng cá nhân khi chưa có hồ sơ kỹ năng có cấu trúc.'

        # Cohort boundary guardrail: check if citation is K75+ while student is K72-K74
        cohort_guardrail_note = ""
        has_k75_citation = any(c.get('cohort') == 'K75+' or 'khóa 75' in str(c.get('excerpt', '')).lower() for c in evidence['citations'])
        if has_k75_citation and student_cohort and student_cohort in ('K72', 'K73', 'K74'):
            cohort_guardrail_note = f"[Lưu ý phạm vi khóa]: Tài liệu trích dẫn (Quy chế 1710) áp dụng từ Khóa 75 trở đi. Với sinh viên {student_cohort}, vui lòng đối chiếu quy chế áp dụng cho khóa của bạn để tránh áp dụng sai quy định.\n\n"

        if detected_other_major:
            major_guardrail_note = f"[Cảnh báo phạm vi ngành]: Bạn là sinh viên ngành {student_major}. Câu hỏi đề cập đến ngành {detected_other_major}. Quy định này không tự động áp dụng cho ngành của bạn.\n\n"
            answer_text = major_guardrail_note + cohort_guardrail_note + (answer_text or '')
        elif cohort_guardrail_note:
            answer_text = cohort_guardrail_note + (answer_text or '')

        result.update(status='completed' if (answered or evidence['citations']) else 'needs_clarification',
            answer=answer_text,
            citations=evidence['citations'], provider_status=evidence['generation_status'],
            cards=[{'type': 'evidence', 'data': evidence}])
        if extractive_fallback:
            result['response_mode'] = 'retrieval_fallback'
        remaining = int(memory_context.get('turns_left', CONTEXT_MAX_TURNS + 1)) - 1 if memory_context else CONTEXT_MAX_TURNS
        if anchor and remaining > 0:
            result['context'] = _context_payload('knowledge_search', mode='memory', topic=topic,
                                                 anchor=anchor, turns_left=remaining)
        return result
    if tool == 'explain':
        match = re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', text)
        if not match:
            return clarify('Cung cấp mã UUID của dự đoán nghiên cứu thuộc tài khoản bạn để xem giải thích đã lưu.')
        return done('prediction_explanation', a.prediction_explanation(UUID(match[0]), user)['data'], 'Giải thích của đúng phiên bản mô hình và snapshot đã lưu; không phải quan hệ nhân quả.')
    if tool == 'predict':
        return clarify('Mô hình OULAD chỉ áp dụng cho ca nghiên cứu OULAD đủ dữ liệu ngày 28. Không thể suy diễn rủi ro từ GPA/hồ sơ DEMO. Hãy dùng trang Nghiên cứu để chọn ca và tạo dự đoán.')
    if user['role'] != 'student':
        return clarify('Các công cụ học vụ cá nhân dành cho sinh viên. Cố vấn xem hồ sơ được phân công tại trang Sinh viên; chat không nhận student_id tùy ý.')
    # Resolve data source before the legacy synthetic student lookup. Never merge
    # the personal transcript into a research/demo profile or send it to Gemini.
    with a.transaction() as db:
        personal = a.one(db, 'SELECT revision FROM app.personal_transcripts WHERE user_id=:u', u=user['id'])
        demo = a.one(db, 'SELECT id FROM app.students WHERE user_id=:u', u=user['id'])
    explicit_personal = 'tu khai' in text or 'bang diem ca nhan' in text
    explicit_demo = 'ho so demo' in text or 'ho so mo phong' in text
    if explicit_personal and explicit_demo:
        params.pop('source', None)
        return clarify('Hãy chọn một nguồn: tự khai hoặc hồ sơ demo. Không trộn hai bảng điểm.')
    if explicit_personal or explicit_demo:
        params['source'] = 'personal' if explicit_personal else 'demo'
    if personal and demo and not params.get('source'):
        params['request'] = message
        return clarify('Bạn muốn dùng bảng điểm tự khai hay hồ sơ demo? Hãy ghi rõ nguồn cùng câu hỏi để tính đúng dữ liệu.')
    if source_reply and params.get('request'):
        text = normalize(params.pop('request'))
    if params.get('source') == 'personal' or (not demo and personal and params.get('source') != 'demo'):
        params['source'] = 'personal'
        from app import personal_academics as personal_service
        if tool == 'course_result':
            view = personal_service.get_transcript(user)['data']
            return course_result(view['transcript']['attempts'], text, clarify, result)
        if tool == 'academic_summary':
            data = personal_service.academic_summary(user)['data']
            summary = data['summary']
            card = {**data, 'cumulative_gpa': summary['gpa_4'], 'gpa_10': summary['gpa_10'],
                    'earned_credits': summary['earned_credits'], 'remaining_required_credits': data['remaining_credits']}
            answer = ('Chưa có kết quả tính GPA.' if summary['gpa_4'] is None else
                      f"GPA tự khai: {summary['gpa_4']}/4 và {summary['gpa_10']}/10.")
            return done('academic_summary', card, answer+' Theo quy tắc ACADEMIC-DEMO-2; chưa được trường xác minh.')
        if tool == 'required_gpa':
            credit = re.search(CREDIT, text)
            remaining = text[:credit.start()]+text[credit.end():] if credit else text
            values = re.findall(NUMBER, remaining)
            if credit:
                params['credits'] = credit[1].replace(',', '.')
            if len(values) == 1:
                params['value'] = values[0].replace(',', '.')
            if len(values) > 1 or params.get('credits') is None or params.get('value') is None:
                return clarify('Ghi rõ mục tiêu và tín chỉ học mới, ví dụ: GPA mục tiêu tự khai 3.2 với 30 tín chỉ.')
            try:
                request = personal_service.PersonalGoal(target_gpa=params['value'],
                    future_gpa_credits=params['credits'])
                data = personal_service.goal(request, user)['data']
            except (ValidationError, ValueError):
                params.pop('value', None)
                params.pop('credits', None)
                return clarify('GPA mục tiêu từ 0 đến 4, tín chỉ học mới từ 0 đến 500.')
            return done('required_gpa', data, 'Mục tiêu dựa trên bảng điểm tự khai đã lưu; chỉ tính tín chỉ học mới, không thay điểm học lại.')
        if tool == 'simulate':
            average = future_average(text)
            if average:
                try:
                    data = personal_service.project_average(user, average['value'], average['credits'])
                except (ValidationError, ValueError):
                    return clarify('GPA giả định phải từ 0 đến 4 và tín chỉ mới phải lớn hơn 0.')
                before = display_number(data['projection']['current_gpa'])
                after = display_number(data['projection']['projected_gpa'])
                label = f"{average.get('grade_label')} ({display_number(average['value'])})" if average.get('grade_label') else display_number(average['value'])
                return done('simulate', data, f'Nếu {display_number(average["credits"])} tín chỉ mới đều đạt {label}, GPA dự kiến là {after}/4 (hiện tại {before}/4). Kịch bản không được lưu.')
            from app.chat_personal import simulate_existing
            return simulate_existing(text, params, user, clarify, done)
        return clarify('Với bảng điểm tự khai, hãy mở “Bảng điểm cá nhân đã lưu” để sửa kịch bản và bấm “Tính what-if, không lưu”. Chưa đủ dữ liệu chương trình/tiên quyết để xác nhận môn được phép đăng ký.')
    if not demo:
        return clarify('Bạn chưa lưu bảng điểm. Mở “Bảng điểm cá nhân đã lưu”, nhập học kỳ và kết quả trước khi hỏi GPA.')
    with a.transaction() as db:
        student = a.own_student(db, user)
        history = a.transcript(db, student)
        if tool == 'course_result':
            return course_result(history, text, clarify, result)
        if tool == 'academic_summary':
            data = a.summary_service(db, student)
            if any(x in text for x in ('lich su', 'tung ky', 'xu huong', 'qua trinh')):
                return done('academic_summary', data, 'Lịch sử GPA theo thời điểm từng kỳ; không đưa điểm học lại ở kỳ sau vào kỳ trước.')
            if 'thieu bao nhieu tin' in text:
                remaining = data.get('remaining_required_credits')
                answer = ('Chưa xác định được số tín chỉ còn thiếu từ chương trình hiện tại.' if remaining is None else
                          f'Bạn còn {display_number(remaining)} tín chỉ bắt buộc theo chương trình demo hiện tại. '
                          'Đây chưa phải xác nhận đủ điều kiện tốt nghiệp.')
                return done('academic_summary', data, answer)
            gpa = data['cumulative_gpa']
            return done(tool, data, 'Chưa có điểm tính GPA.' if gpa is None else f"GPA tích lũy: {display_number(gpa)}/4. Kết quả từ hồ sơ demo theo policy đã cấu hình, không phải điểm trường xác nhận.")
        if tool == 'catalog':
            data = a.rows(db, '''SELECT c.code,c.title,cc.credits,cc.required,cc.recommended_term_no
                FROM app.curriculum_courses cc JOIN app.courses c ON c.id=cc.course_id
                WHERE cc.curriculum_id=:cid ORDER BY cc.recommended_term_no,c.code''', cid=student['curriculum_id'])
            result.update(status='completed', answer='Danh mục môn thuộc chương trình của bạn:\n' + '\n'.join(f"{c['code']} — {c['title']} ({c['credits']} TC)" for c in data))
            return result
        semesters = a.rows(db, 'SELECT id,code FROM app.semesters ORDER BY start_date')
        for semester in semesters:
            if re.search(r'(?<!\w)' + re.escape(normalize(semester['code'])) + r'(?!\w)', text):
                params['semester_id'] = str(semester['id'])
        if tool == 'course_recommendations':
            if not params.get('semester_id'):
                return clarify('Bạn muốn đăng ký học kỳ nào? Mã học kỳ: ' + ', '.join(s['code'] for s in semesters))
            return done(tool, a.recommend_service(db, student, UUID(params['semester_id'])), 'Gợi ý xác định đã kiểm tra môn đạt và tiên quyết; tối đa 18 tín chỉ. Chưa kiểm tra trùng lịch/sĩ số.')
        courses = a.rows(db, '''SELECT c.id,c.code FROM app.courses c JOIN app.curriculum_courses cc
                ON cc.course_id=c.id WHERE cc.curriculum_id=:cid''', cid=student['curriculum_id'])
        course_matches = [c for c in courses if re.search(r'(?<!\w)' + re.escape(normalize(c['code'])) + r'(?!\w)', text)]
        if len(course_matches) > 1:
            return clarify('Hãy mô phỏng/tính điểm một môn mỗi lượt, hoặc dùng biểu mẫu Mô phỏng nhiều môn.')
        if course_matches:
            params['course_id'] = str(course_matches[0]['id'])
        numbers_text = text
        for c in courses:
            numbers_text = re.sub(re.escape(normalize(c['code'])), '', numbers_text)
        for s in semesters:
            numbers_text = numbers_text.replace(normalize(s['code']), '')
        credit = re.search(CREDIT, numbers_text)
        if credit:
            params['credits'] = credit[1].replace(',', '.')
            numbers_text = numbers_text[:credit.start()] + numbers_text[credit.end():]
        values = re.findall(NUMBER, numbers_text)
        grade = letter_gpa(numbers_text) if tool == 'simulate' and not params.get('course_id') else None
        if grade:
            params['value'], params['grade_label'] = grade[1], grade[0]
        elif len(values) == 1:
            params['value'] = values[0].replace(',', '.')
        elif len(values) > 1:
            return clarify('Hãy cung cấp một điểm mục tiêu/giả định duy nhất và ghi rõ số tín chỉ. Ví dụ: mô phỏng GPA 3.5 với 15 tín chỉ.')
        if tool in ('required_gpa', 'simulate') and not params.get('course_id'):
            if params.get('value') is None or params.get('credits') is None:
                return clarify('Cần GPA (0–4) và số tín chỉ mới tính GPA. Ví dụ: mục tiêu GPA 3.2 với 30 tín chỉ, hoặc mô phỏng GPA 3.5 với 15 tín chỉ. Không tự coi tín chỉ chưa tích lũy là tín chỉ tính GPA.')
        elif not params.get('course_id') or params.get('value') is None:
            return clarify('Cung cấp mã môn và điểm tổng kết (0–10). Ví dụ: điểm thi CS101 để đạt 8; hoặc mô phỏng CS101 được 8.')
        offering_id = enrollment_id = unknown = None
        if params.get('course_id'):
            enrolled = [r for r in history if str(r['course_id']) == params['course_id'] and
                        (not params.get('semester_id') or str(r['semester_id']) == params['semester_id'])]
            if tool == 'target_score':
                enrolled = [r for r in enrolled if r['status'] in {'pending', 'incomplete'}]
                if len(enrolled) != 1:
                    return clarify('Cần đúng một lần đăng ký môn đang học. Hãy ghi thêm mã học kỳ hoặc kiểm tra bảng điểm.')
                enrollment_id = enrolled[0]['id']
                missing = a.rows(db, '''SELECT c.code FROM app.assessment_components c LEFT JOIN app.grade_components g
                    ON g.component_id=c.id AND g.enrollment_id=:eid WHERE c.offering_id=:oid AND g.score IS NULL''',
                    eid=enrollment_id, oid=enrolled[0]['offering_id'])
                if len(missing) != 1:
                    return clarify('Phép tính cần đúng một thành phần điểm chưa biết. Kiểm tra/nhập các điểm thành phần trước; không tự gán điểm thiếu bằng 0.')
                unknown = missing[0]['code']
            elif tool == 'simulate':
                offered = a.rows(db, 'SELECT id,semester_id FROM app.course_offerings WHERE course_id=:cid', cid=UUID(params['course_id']))
                offered = [r for r in offered if not params.get('semester_id') or str(r['semester_id']) == params['semester_id']]
                if len(offered) != 1:
                    return clarify('Môn có nhiều hoặc chưa có lớp mở. Hãy ghi mã học kỳ: ' + ', '.join(s['code'] for s in semesters))
                offering_id = offered[0]['id']
    try:
        if tool == 'required_gpa':
            data = a.required(a.Required(target_gpa=params['value'], future_gpa_credits=params['credits']), user)['data']
        elif tool == 'target_score':
            data = a.target(a.Target(enrollment_id=enrollment_id, target_total_score=params['value'], unknown_component_code=unknown), user)['data']
        elif offering_id:
            data = a.simulate(a.CourseSimulation(mode='course_scores', items=[a.CourseScore(offering_id=offering_id, assumed_final_score=params['value'])]), user)['data']
        else:
            data = a.simulate(a.Average(mode='semester_average', assumed_gpa=params['value'], gpa_credits=params['credits']), user)['data']
    except (ValidationError, ValueError):
        params.pop('value', None)
        params.pop('credits', None)
        return clarify('Tham số chưa hợp lệ: GPA 0–4, điểm tổng kết 0–10; tín chỉ 0–126 (mô phỏng phải lớn hơn 0), tối đa 6 chữ số thập phân. Vui lòng nhập lại.')
    if tool == 'simulate' and not params.get('course_id'):
        before = display_number(data['before']['cumulative_gpa'])
        after = display_number(data['after']['cumulative_gpa'])
        label = f"{params.get('grade_label')} ({display_number(params['value'])})" if params.get('grade_label') else display_number(params['value'])
        answer = (f'Nếu {display_number(params["credits"])} tín chỉ mới đều đạt {label}, GPA dự kiến là '
                  f'{after}/4 (hiện tại {before}/4). Kịch bản không được lưu.')
        return done(tool, data, answer)
    return done(tool, data, 'Kết quả từ bộ tính học vụ theo policy của hồ sơ demo. Đây là tính toán/mô phỏng, không thay đổi bảng điểm hay lưu mục tiêu.')
