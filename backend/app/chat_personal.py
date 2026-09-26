"""Bounded personal what-if. No inferred attempt, credit, date or database write."""
import re
from pydantic import ValidationError


def simulate_existing(text, params, user, clarify, done):
    from app import personal_academics as service
    from app.chat_service import display_number, normalize, NUMBER
    view = service.get_transcript(user)['data']
    revision = view['revision']
    if 'revision' in params and params['revision'] != revision:
        params.clear()
        return clarify('Bảng điểm đã thay đổi trong lúc làm rõ. Hãy gửi lại yêu cầu mô phỏng với bảng điểm mới.')
    params['revision'] = revision
    transcript = service.PersonalTranscript.model_validate(view['transcript'])
    codes = {a.code for a in transcript.attempts}
    matches = [code for code in codes if re.search(r'(?<!\w)'+re.escape(normalize(code))+r'(?!\w)', text)]
    if len(matches) > 1:
        return clarify('Mỗi lượt mô phỏng một môn; nhiều môn hãy dùng biểu mẫu what-if.')
    if matches:
        if params.get('course') != matches[0]:
            params.pop('attempt', None)
        params['course'] = matches[0]
        text = re.sub(r'(?<!\w)'+re.escape(normalize(matches[0]))+r'(?!\w)', '', text)
    attempt = re.search(r'\blan\s+(\d+)\b', text)
    if attempt:
        params['attempt'] = int(attempt[1])
        text = text[:attempt.start()]+text[attempt.end():]
    # NUMBER rejects a digit followed by ``.`` so it cannot extract the integer
    # part of 8.5. Remove only sentence punctuation immediately after a final
    # digit; the decimal boundary rule therefore remains fail-closed.
    numeric_text = re.sub(r'(?<=\d)[.!?]+$', '', text.strip())
    values = re.findall(NUMBER, numeric_text)
    if len(values) > 1:
        return clarify('Ghi một điểm giả định, ví dụ: mô phỏng tự khai CS1 lần 2 được 8.')
    if values:
        params['score'] = values[0].replace(',', '.')
    if not params.get('course') or 'score' not in params:
        return clarify('Ghi mã môn đã lưu và điểm giả định 0–10, ví dụ: mô phỏng tự khai CS1 lần 2 được 8.')
    candidates = [a for a in transcript.attempts if a.code == params['course'] and
                  ('attempt' not in params or a.attempt == params['attempt'])]
    if len(candidates) != 1:
        return clarify('Hãy chỉ rõ lần học đã có trong bảng điểm, ví dụ: CS1 lần 2 được 8. Muốn thêm lần học mới hãy dùng biểu mẫu.')
    chosen = candidates[0]
    payload = transcript.model_dump(mode='json')
    for row in payload['attempts']:
        if row['code'] == chosen.code and row['attempt'] == chosen.attempt:
            row.update(status='graded', score=params['score'])
    try:
        request = service.PersonalSimulation(expected_revision=revision, transcript=payload)
    except ValidationError:
        params.pop('score', None)
        return clarify('Điểm giả định phải từ 0 đến 10, tối đa 6 chữ số thập phân.')
    data = service.simulate(request, user)['data']
    before_score = 'chưa có điểm' if chosen.score is None else f'{display_number(chosen.score)}/10'
    after_score = f'{display_number(params["score"])}/10'
    before_gpa = display_number(data['before']['summary']['gpa_4']) or 'chưa có'
    after_gpa = display_number(data['after']['summary']['gpa_4']) or 'chưa có'
    answer = (f'Mô phỏng {chosen.code} lần {chosen.attempt}: {before_score} → {after_score}; '
              f'GPA {before_gpa} → {after_gpa}/4. Kịch bản không được lưu hoặc thay bảng điểm. '
              'Không tạo ngày công bố giả; nếu sửa lần cũ đã bị thay, GPA hiện tại có thể không đổi.')
    return done('simulate', data, answer)
