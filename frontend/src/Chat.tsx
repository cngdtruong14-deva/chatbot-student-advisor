import { useEffect, useState } from 'react';
import { api } from './api';
import type { ChatTurn as WireChatTurn } from './generated-api';
import { PRODUCT_CONFIG } from './product-config';

type Card = { type: string; data: any };
type Turn = { client_turn_id: string; content: string; result: WireChatTurn & { cards: Card[] } };
type Session = { id: string; created_at: string; corpus_scope?: 'demo_academic' | 'utt_test' | 'utt_corpus' };
type FeedbackLabel = 'helpful' | 'not_helpful' | 'incorrect_citation';
type FeedbackState = { saving?: boolean; saved?: boolean; label?: FeedbackLabel; expiresAt?: string; error?: string };
type EvidenceFeedback = {
  state?: FeedbackState;
  onSubmit?: (label: FeedbackLabel) => void;
};
const number = (v: unknown) => v == null ? 'Chưa có dữ liệu' : Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 3 });
const feasibility: Record<string, string> = { achievable: 'Khả thi theo giả định', impossible: 'Không khả thi', insufficient_data: 'Thiếu dữ liệu', completed_target_met: 'Đã đạt mục tiêu', completed_target_not_met: 'Chưa đạt, không còn tín chỉ mới để tính' };

function evidenceMode(card: Card): string {
  const value = card.data?.response_mode ?? card.data?.rag_mode ?? (card as any).response_mode ?? (card as any).rag_mode;
  return typeof value === 'string' ? value.toLowerCase() : '';
}

function isControlledEvidence(card: Card): boolean {
  return card.type === 'evidence' && (
    evidenceMode(card) === 'controlled_retrieval' ||
    evidenceMode(card) === 'retrieval_only' ||
    String(card.data?.rag_mode ?? '').toLowerCase() === 'beta_controlled'
  );
}

function isCapstoneGeneratedEvidence(card: Card): boolean {
  return card.type === 'evidence' && ['approved_grounded_capstone', 'approved_grounded_capstone_high_stakes']
    .includes(String(card.data?.rag_mode ?? '').toLowerCase());
}

function controlledReason(data: any): string {
  const reason = String(data?.controlled_reason ?? data?.reason_code ?? data?.reason ?? '').toLowerCase();
  if (reason.includes('insufficient') || reason.includes('low_confidence')) return 'Chưa tìm thấy đủ thông tin chắc chắn trong tài liệu hiện có.';
  if (reason.includes('high_stakes')) return 'Nội dung có ảnh hưởng học vụ quan trọng, hệ thống ưu tiên cung cấp trích dẫn để bạn đối chiếu văn bản gốc.';
  if (reason.includes('provider') || reason.includes('generation')) return 'Hệ thống hiện cung cấp thông tin dựa trên trích dẫn trực tiếp từ tài liệu.';
  if (reason.includes('quality') || reason.includes('release')) return 'Tài liệu đang được kiểm soát theo quy trình phát hành của kho pilot.';
  return 'Thông tin được trích dẫn trực tiếp từ tài liệu chính thức của trường để bạn thuận tiện tra cứu.';
}

function formatFeedbackExpiry(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date.toLocaleString('vi-VN');
}

function formatCitationLocator(c: any): string {
  if (c.locator_label) return c.locator_label;
  if (c.page_number != null && c.page_number >= 0) {
    return `Trang ${c.page_number}${c.section ? ` · ${c.section}` : ''}`;
  }
  if (c.section) return `${c.section} (Không có số trang gốc)`;
  return 'Văn bản không phân trang';
}

function EvidenceFeedbackControls({ feedback }: { feedback?: EvidenceFeedback }) {
  if (!feedback?.onSubmit) return null;
  const savedExpiry = formatFeedbackExpiry(feedback.state?.expiresAt);
  if (feedback.state?.saved) return <p role="status" style={{ margin: '10px 0 0', fontSize: '0.88em', color: '#166534' }}>Đã lưu phản hồi{savedExpiry ? `; dữ liệu phản hồi được giữ đến ${savedExpiry}.` : '.'}</p>;
  return <div style={{ marginTop: '12px', borderTop: '1px solid #e2e8f0', paddingTop: '10px' }}>
    <small style={{ display: 'block', color: '#475569', marginBottom: '7px' }}>Trích đoạn này có giúp bạn tra cứu không?</small>
    <div style={{ display: 'flex', gap: '7px', flexWrap: 'wrap' }}>
      <button type="button" className="chip-btn" disabled={feedback.state?.saving} onClick={() => feedback.onSubmit?.('helpful')}>Hữu ích</button>
      <button type="button" className="chip-btn" disabled={feedback.state?.saving} onClick={() => feedback.onSubmit?.('not_helpful')}>Chưa hữu ích</button>
      <button type="button" className="chip-btn" disabled={feedback.state?.saving} onClick={() => feedback.onSubmit?.('incorrect_citation')}>Trích dẫn chưa đúng</button>
    </div>
    {feedback.state?.saving && <small role="status" style={{ display: 'block', marginTop: '7px', color: '#475569' }}>Đang lưu phản hồi…</small>}
    {feedback.state?.error && <small role="alert" className="error" style={{ display: 'block', marginTop: '7px' }}>{feedback.state.error}</small>}
  </div>;
}

export function ChatCard({ card, feedback }: { card: Card; feedback?: EvidenceFeedback }) {
  const d = card.data;
  switch (card.type) {
    case 'academic_summary': return <div className="numeric-card">GPA: {number(d.cumulative_gpa)} / 4 · Đạt {number(d.earned_credits)} tín chỉ · Còn {number(d.remaining_required_credits)} tín chỉ bắt buộc{d.semester_history?.length > 0 && <details><summary>Lịch sử từng kỳ</summary><ChatCard card={{ type: 'semester_history', data: d.semester_history }} /></details>}</div>;
    case 'goal_analysis': return <ChatCard card={{ type: 'required_score' in d ? 'target_score' : 'required_gpa', data: d }} />;
    case 'required_gpa': return <div className="numeric-card">GPA cần đạt: {number(d.required_future_gpa)} / 4<p>{feasibility[d.feasibility] || d.feasibility}</p></div>;
    case 'target_score': return <div className="numeric-card">Điểm thành phần cần đạt: {number(d.required_score)} / 10<p>{feasibility[d.feasibility] || d.feasibility}</p></div>;
    case 'simulation':
    case 'simulate': {
      const projection = d.projection;
      const currentGpa4 = projection?.current_gpa ?? d.before.summary?.gpa_4 ?? d.before.cumulative_gpa;
      const projectedGpa4 = projection?.projected_gpa ?? d.after.summary?.gpa_4 ?? d.after.cumulative_gpa;
      const currentGpa10 = d.before.summary?.gpa_10 ?? d.before.gpa_10;
      const projectedGpa10 = d.after.summary?.gpa_10 ?? d.after.gpa_10;
      const scale10Unavailable = currentGpa10 != null && projectedGpa10 == null;
      return <div className="numeric-card">
        <div>GPA hiện tại: {number(currentGpa4)} / 4</div>
        {projection?.assumed_gpa != null && <div>Giả định: đạt {number(projection.assumed_gpa)} / 4 cho {number(projection.future_gpa_credits)} tín chỉ mới</div>}
        <div>→ GPA dự kiến: {number(projectedGpa4)} / 4</div>
        {currentGpa10 != null && <p>Thang 10 hiện tại: {number(currentGpa10)} / 10{!scale10Unavailable && projectedGpa10 != null && <> → dự kiến: {number(projectedGpa10)} / 10</>}</p>}
        {scale10Unavailable && <p><small>Không quy đổi GPA dự kiến sang thang 10 vì quy tắc quy đổi theo bậc, không tuyến tính.</small></p>}
        <p>Không ghi thay đổi vào bảng điểm.</p>
      </div>;
    }
    case 'semester_history': return <table><thead><tr><th>Học kỳ</th><th>GPA kỳ</th><th>GPA tích lũy</th><th>Tín chỉ đạt kỳ</th><th>Độ đầy đủ</th></tr></thead><tbody>{d.map((s: any) => <tr key={s.code || s.semester_id}><td>{s.code || s.semester_code || s.semester_id}</td><td>{number(s.term?.gpa_4 ?? s.term_gpa)}</td><td>{number(s.cumulative?.gpa_4 ?? s.cumulative_gpa)}</td><td>{number(s.term?.earned_credits ?? s.term_earned_credits)}</td><td>{s.coverage === 'partial' ? 'Thiếu ngày/kết quả' : s.coverage === 'complete' ? 'Đủ theo dữ liệu tự khai' : 'Theo hồ sơ'}</td></tr>)}</tbody></table>;
    case 'course_recommendations': return <div><p>Tổng: {number(d.total_credits)} tín chỉ</p>{d.selected.length ? <ul>{d.selected.map((c: any) => <li key={c.id}>{c.code} — {c.title} · {number(c.credits)} TC{c.retake ? ' · học lại' : ''}</li>)}</ul> : <p>Không có môn đủ điều kiện.</p>}<details><summary>Các môn loại và lý do</summary><ul>{d.excluded.map((c: any, i: number) => <li key={i}>{c.code}: {c.reason}{c.missing?.length ? ` (${c.missing.length} tiên quyết chưa đủ)` : ''}</li>)}</ul></details></div>;
    case 'curriculum_summary': return <details><summary>{d.length} môn trong chương trình</summary><ul>{d.map((c: any) => <li key={c.code}>{c.code} — {c.title} · {number(c.credits)} TC</li>)}</ul></details>;
    case 'career_requirements': return <div className="numeric-card">
      <strong>{d.career.title}</strong><p>{d.career.description}</p>
      <ul>{d.skills.map((s: any) => <li key={s.skill_id}>{s.skill_name} · {number(Number(s.importance_weight) * 100)}%</li>)}</ul>
      <details><summary>Môn HTTT liên quan</summary><ul>{d.skills.flatMap((s: any) => (s.courses || []).map((c: any) => <li key={`${s.skill_id}-${c.course_code}`}>{c.course_code} — {c.course_title} → {s.skill_name}</li>))}</ul></details>
      <small>Phiên bản {d.mapping_version} · Dữ liệu demo đã duyệt.</small>
    </div>;
    case 'career_skill_gap': return <div className="numeric-card">
      <strong>{d.career.title}</strong><p>Mức phủ kỹ năng: {number(d.match_score)}%</p>
      {d.data_status === 'insufficient_evidence' ? <p>Chưa có đủ điểm môn HTTT đã đạt để phân tích cá nhân.</p> : <>
        <details open><summary>Kỹ năng đã có bằng chứng ({d.strong_skills.length})</summary><ul>{d.strong_skills.map((s: any) => <li key={s.skill_id}>{s.skill_name}{s.proficiency_5 ? ` · mức suy ra ${number(s.proficiency_5)}/5` : ''}</li>)}</ul></details>
        <details open><summary>Kỹ năng chưa có bằng chứng ({d.missing_skills.length})</summary><ul>{d.missing_skills.map((s: any) => <li key={s.skill_id}>{s.skill_name}</li>)}</ul></details>
        <details><summary>Môn nên tham khảo</summary><ul>{d.recommended_courses.map((c: any) => <li key={c.course_code}>{c.course_code} — {c.course_title} · {number(c.credits)} TC</li>)}</ul></details>
        {d.recommended_certifications.length > 0 && <details><summary>Chứng chỉ tham khảo</summary><ul>{d.recommended_certifications.map((c: any) => <li key={c.cert_code}>{c.name} — {c.skill_name}</li>)}</ul></details>}
      </>}
      <small>Điểm này không phải xác suất tuyển dụng. Phiên bản {d.mapping_version}.</small>
    </div>;
    case 'career_matches': return <div className="numeric-card">
      <strong>So sánh định hướng HTTT</strong>
      {d.data_status === 'insufficient_evidence' ? <p>Chưa đủ dữ liệu điểm HTTT đã đạt.</p> : <ol>{d.matches.slice(0, 6).map((m: any) => <li key={m.career.career_code}>{m.career.title}: {number(m.match_score)}%</li>)}</ol>}
      <small>Chỉ phản ánh mức phủ kỹ năng trong bộ demo đã duyệt.</small>
    </div>;
    case 'evidence': {
      const controlled = isControlledEvidence(card);
      const capstoneGenerated = isCapstoneGeneratedEvidence(card);
      const citations = Array.isArray(d.citations) ? d.citations : [];
      const releaseId = d.release_id ?? d.corpus_release_id ?? d.release?.id;
      return <div>
      {controlled && <div role="status" style={{ margin: '0 0 10px', padding: '10px 12px', borderRadius: '6px', border: '1px solid #fbbf24', background: '#fffbeb', color: '#78350f' }}>
        <strong>{PRODUCT_CONFIG.CHAT.SOURCE_TITLE}</strong>
        <p style={{ margin: '5px 0 0' }}>{controlledReason(d)} {PRODUCT_CONFIG.CORPUS_DISCLOSURE} Không coi đây là quyết định học vụ tự động; bạn nên mở tài liệu gốc để kiểm chứng.</p>
      </div>}
      {capstoneGenerated && <div role="status" style={{ margin: '0 0 10px', padding: '10px 12px', borderRadius: '6px', border: '1px solid #60a5fa', background: '#eff6ff', color: '#1e3a8a' }}>
        <strong>{PRODUCT_CONFIG.CHAT.ANSWER_FALLBACK_LABEL}</strong>
        <p style={{ margin: '5px 0 0' }}>Câu trả lời được tổng hợp từ kho tài liệu đang chọn và có dẫn nguồn. Vui lòng mở nguồn gốc khi cần đối chiếu quyết định học vụ.</p>
      </div>}
      {d.claims?.length > 0 && !controlled && <details><summary>Đối chiếu từng ý với nguồn</summary><ul>{d.claims.map((claim: any, i: number) => <li key={i}>{claim.text} {claim.citation_ids.map((id: string) => { const n = citations.findIndex((c: any) => c.chunk_id === id); return n >= 0 ? <span key={id}>[{n + 1}] </span> : null; })}</li>)}</ul></details>}
      {controlled && <p style={{ margin: '8px 0', color: '#475569', fontSize: '0.92em' }}>{citations.length ? `Top ${citations.length} trích đoạn đã truy xuất để đối chiếu:` : 'Không có trích đoạn đủ điều kiện để hiển thị.'}</p>}
      {(controlled || releaseId) && <small style={{ display: 'block', margin: '8px 0', color: '#64748b' }}>
        Bản phát hành: {releaseId || PRODUCT_CONFIG.CORPUS_NAME} · {PRODUCT_CONFIG.CORPUS_DISCLOSURE}
      </small>}
      {citations.map((c: any, i: number) => {
        const locator = formatCitationLocator(c);
        const effectivity = c.is_effective_date_verified
          ? `Hiệu lực: ${c.effective_from || '—'} đến ${c.effective_until || '—'}`
          : 'Chưa xác minh ngày hiệu lực';
        const sourceUrl = /^https?:\/\//i.test(c.source)
          ? c.source
          : (typeof c.source === 'string' && c.source.startsWith('gdrive:') ? `https://drive.google.com/file/d/${c.source.slice(7)}/view` : null);
        return (
          <details key={c.chunk_id} style={{ marginBottom: '8px', padding: '6px 10px', border: '1px solid #e2e8f0', borderRadius: '6px', background: '#ffffff' }}>
            <summary style={{ cursor: 'pointer', fontWeight: 500, color: '#0f172a' }}>
              [{i + 1}] {c.title || 'Tài liệu UTT'} · {locator}
            </summary>
            <p style={{ whiteSpace: 'pre-wrap', margin: '8px 0', fontSize: '0.92em', color: '#334155' }}>{c.excerpt}</p>
            <small style={{ color: '#64748b', display: 'block' }}>
              {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer" style={{ color: '#0284c7', textDecoration: 'underline' }}>Mở tài liệu gốc ↗</a> : <span>Nguồn: {c.source}</span>}
              {c.version || c.version_id ? ` · Phiên bản: ${c.version || c.version_id}` : ''}
              {' · '}{effectivity}
              {c.major && c.major !== 'all' ? ` · Ngành: ${c.major}` : ''}
              {c.cohort && c.cohort !== 'all' ? ` · Khóa: ${c.cohort}` : ''}
            </small>
          </details>
        );
      })}
      <EvidenceFeedbackControls feedback={feedback} />
      </div>;
    }
    default: return <details><summary>Kết quả có cấu trúc: {card.type}</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(d, null, 2)}</pre></details>;
  }
}

const SUGGESTIONS = [
  'Điều kiện để sinh viên được xét công nhận tốt nghiệp và cấp bằng tốt nghiệp?',
  'Đối tượng nào không được xét học bổng khuyến khích học tập?',
  'Những kỹ năng nào cần có cho định hướng nghề nghiệp của ngành tôi?',
  'Trường có thông tin đối tác hoặc cơ hội việc làm nào đang được công bố?',
  'Sinh viên ngành Công nghệ thông tin có được miễn chuẩn đầu ra tin học không?',
  'Sinh viên được xin nghỉ học tạm thời và bảo lưu kết quả trong trường hợp nào?',
  'GPA của tôi hiện tại là bao nhiêu?'
];

export function Chat({ isAdmin = false, isStudent = false, studentProfileLinked = false }: { isAdmin?: boolean; isStudent?: boolean; studentProfileLinked?: boolean }) {
  const [sessions, setSessions] = useState<Session[]>([]), [sid, setSid] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]), [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [pending, setPending] = useState<{ message: string; client_turn_id: string } | null>(null);
  const [feedback, setFeedback] = useState<Record<string, FeedbackState>>({});
  const [selectedEvidenceTurnId, setSelectedEvidenceTurnId] = useState('');
  const [personalAcademicState, setPersonalAcademicState] = useState<'loading' | 'empty' | 'ready'>('loading');
  const [corpusScope, setCorpusScope] = useState<'demo_academic' | 'utt_test' | 'utt_corpus'>(
    (isAdmin || isStudent) ? 'utt_corpus' : 'demo_academic'
  );
  useEffect(() => { let alive = true; api<{ items: Session[] }>('/chat/sessions').then(r => { if (alive) setSessions(r.items); }).catch(e => { if (alive) setError(e.message); }); return () => { alive = false; }; }, []);
  useEffect(() => {
    if (!isStudent) { setPersonalAcademicState('empty'); return; }
    let alive = true;
    api<any>('/account/transcript')
      .then(view => {
        if (!alive) return;
        const attempts = Array.isArray(view?.transcript?.attempts) ? view.transcript.attempts : [];
        setPersonalAcademicState(view?.revision > 0 && attempts.length > 0 ? 'ready' : 'empty');
      })
      .catch(() => { if (alive) setPersonalAcademicState('empty'); });
    return () => { alive = false; };
  }, [isStudent]);
  async function open(id: string) {
    setBusy(true); setError('');
    try {
      let cursor: string | null = null; const loaded: Turn[] = [];
      if (id) do {
        const r: { items: Turn[]; next_cursor: string | null } = await api(`/chat/sessions/${id}/messages?limit=100${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`);
        loaded.push(...r.items); cursor = r.next_cursor;
      } while (cursor);
      const evidenceTurns = loaded.filter(turn => turn.result.cards?.some(card => card.type === 'evidence'));
      setSid(id); setTurns(loaded); setSelectedEvidenceTurnId(evidenceTurns[evidenceTurns.length - 1]?.client_turn_id || ''); setPending(null); setMessage('');
      const session = sessions.find(s => s.id === id); if (session?.corpus_scope) setCorpusScope(session.corpus_scope);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function send(customMessage?: string) {
    const textToSend = (customMessage || message).trim();
    if (busy || (!textToSend && !pending)) return;
    setBusy(true); setError('');
    const payload = pending || { message: textToSend, client_turn_id: crypto.randomUUID() };
    setPending(payload);
    try {
      let id = sid;
      if (!id) {
        const created = await api<Session>('/chat/sessions', { corpus_scope: corpusScope }); id = created.id;
        setSid(id); setSessions(old => [created, ...old]);
      }
      const result = await api<Turn['result']>(`/chat/sessions/${id}/messages`, payload);
      setTurns(old => [...old.filter(t => t.client_turn_id !== payload.client_turn_id), { client_turn_id: payload.client_turn_id, content: payload.message, result }]);
      if (result.cards?.some(card => card.type === 'evidence')) setSelectedEvidenceTurnId(payload.client_turn_id);
      setPending(null); setMessage('');
    } catch (e) { setError((e as Error).message + ' — Thử lại giữ nguyên mã lượt, không tạo kết quả trùng. Nếu phiên đã hết hạn, bắt đầu cuộc trò chuyện mới.'); }
    finally { setBusy(false); }
  }
  async function submitFeedback(sessionId: string, turnId: string, label: FeedbackLabel) {
    const key = `${sessionId}:${turnId}`;
    if (feedback[key]?.saving || feedback[key]?.saved) return;
    setFeedback(old => ({ ...old, [key]: { saving: true, label } }));
    try {
      const saved = await api<{ saved: true; expires_at?: string; label?: FeedbackLabel }>(
        `/chat/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(turnId)}/feedback`,
        { label },
        'POST',
      );
      setFeedback(old => ({ ...old, [key]: { saved: saved.saved === true, label: saved.label || label, expiresAt: saved.expires_at } }));
    } catch {
      setFeedback(old => ({ ...old, [key]: { label, error: 'Không thể lưu phản hồi lúc này. Bạn có thể thử lại sau.' } }));
    }
  }
  const selectedEvidenceTurn = turns.find(turn => turn.client_turn_id === selectedEvidenceTurnId);
  const selectedEvidenceCards = selectedEvidenceTurn?.result.cards?.filter(card => card.type === 'evidence') || [];
  const selectedFeedbackKey = sid && selectedEvidenceTurn ? `${sid}:${selectedEvidenceTurn.client_turn_id}` : '';

  return <section className="panel chat">
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
      <div>
        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>{PRODUCT_CONFIG.CHAT.TITLE}</h2>
        <small style={{ color: '#64748b' }}>{PRODUCT_CONFIG.TAGLINE}</small>
      </div>
    </div>
    <div className="chat-workspace">
    <div className="chat-main">
      {isStudent && !studentProfileLinked && personalAcademicState === 'ready' && <p role="status" className="chat-profile-status chat-profile-status-personal"><strong>Hồ sơ tự khai đang hoạt động.</strong> Chatbot có thể đọc bảng điểm đã lưu, tính GPA và mô phỏng cho chính tài khoản này. Dữ liệu trường và tài liệu giới hạn theo ngành/khóa vẫn chưa được liên kết hoặc xác minh.</p>}
      {isStudent && !studentProfileLinked && personalAcademicState === 'empty' && <p role="status" className="error"><strong>Chưa có hồ sơ học tập cá nhân.</strong> Bạn vẫn có thể tra cứu tài liệu UTT phạm vi chung. Để dùng GPA và mô phỏng, hãy mở “Hồ sơ học tập” → “Bảng điểm cá nhân”, lưu thông tin cá nhân và ít nhất một kết quả. Chỉ cần quản trị viên liên kết khi bạn muốn dùng dữ liệu trường hoặc tài liệu giới hạn theo ngành/khóa.</p>}
      {isStudent && studentProfileLinked && <p role="status" className="chat-profile-status"><strong>Hồ sơ trường đã liên kết.</strong> Chatbot có thể dùng dữ liệu học vụ gắn với tài khoản của bạn. Nếu đồng thời có bảng điểm tự khai, hãy ghi rõ nguồn muốn sử dụng trong câu hỏi.</p>}
      {turns.length === 0 && (
      <div style={{ margin: '14px 0', padding: '12px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <small style={{ display: 'block', marginBottom: '8px', color: '#475569', fontWeight: 600 }}>Gợi ý câu hỏi học vụ thường gặp trong phạm vi pilot (bấm để hỏi ngay):</small>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {SUGGESTIONS.map((s, idx) => (
            <button
              key={idx}
              type="button"
              className="chip-btn"
              disabled={busy || !!pending}
              onClick={() => { setMessage(s); void send(s); }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      )}

    <p style={{ marginTop: '10px', fontSize: '13px', color: '#64748b' }}>
      {corpusScope === 'utt_test'
        ? 'Tra cứu văn bản thử nghiệm đã nạp và kiểm tra trích đoạn đối chiếu.'
        : corpusScope === 'utt_corpus'
        ? 'Tra cứu quy chế đào tạo tín chỉ, chuẩn đầu ra, điểm rèn luyện, học bổng và thủ tục học vụ trong kho tài liệu UTT của pilot.'
        : 'Ví dụ: “GPA của tôi hiện tại là bao nhiêu?”, “mục tiêu GPA 3.2 với 30 tín chỉ”, “mô phỏng GPA 3.5”, “điểm thi cần đạt”.'}
    </p>

      <div className="messages" aria-live="polite">
      {turns.map(t => {
        const cards: Card[] = Array.isArray(t.result.cards) ? t.result.cards as Card[] : [];
        const controlled = cards.some(isControlledEvidence);
        const sourceCount = cards.filter(card => card.type === 'evidence').reduce((total, card) => total + (Array.isArray(card.data?.citations) ? card.data.citations.length : 0), 0);
        return <div key={t.client_turn_id}><article className="bubble user"><small>BẠN</small><p>{t.content}</p></article><article className="bubble assistant">
          <small>CỐ VẤN AI · {controlled ? PRODUCT_CONFIG.CHAT.SOURCE_TITLE : ['timeout', 'rate_limited', 'authentication_error', 'provider_unavailable', 'provider_error', 'insufficient_evidence'].includes(t.result.provider_status || '') ? 'Trích đoạn trực tiếp' : t.result.status === 'completed' ? PRODUCT_CONFIG.CHAT.ANSWER_FALLBACK_LABEL : t.result.status === 'failed' ? 'Dịch vụ tạm thời không khả dụng' : PRODUCT_CONFIG.CHAT.INSUFFICIENT_EVIDENCE_LABEL}</small>
          <p>{t.result.answer}</p>
          {cards.filter(card => card.type !== 'evidence').map((card, i) => <ChatCard key={i} card={card} />)}
          {sourceCount > 0 && <button type="button" className="source-link" aria-label={`Xem ${sourceCount} nguồn tham khảo của câu trả lời`} onClick={() => setSelectedEvidenceTurnId(t.client_turn_id)}>{sourceCount} nguồn tham khảo →</button>}
        </article></div>;
      })}
      {busy && (
        <div className="typing-indicator" role="status">
          <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#0284c7', animation: 'pulse 1.5s infinite' }}></span>
          <span>Cố vấn AI đang tra cứu và đối chiếu kho tài liệu...</span>
        </div>
      )}
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      <form onSubmit={e => { e.preventDefault(); void send(); }}><input aria-label="Tin nhắn" value={message} disabled={busy || !!pending} onChange={e => setMessage(e.target.value)} maxLength={2000} placeholder="Gõ câu hỏi của bạn…" /><button disabled={busy || (!message.trim() && !pending)}>{busy ? 'Đang xử lý…' : pending ? 'Thử lại' : 'Gửi ↗'}</button></form>

      <div style={{ marginTop: '12px', padding: '10px 14px', background: '#f8fafc', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '12px', color: '#64748b' }}>
      <p style={{ margin: '0 0 4px', fontWeight: 500 }}>ℹ️ {PRODUCT_CONFIG.CHAT.RETENTION_NOTICE}</p>
      <p style={{ margin: 0, color: '#94a3b8' }}>⚠️ {PRODUCT_CONFIG.CHAT.HIGH_STAKES_WARNING}</p>
      </div>
    </div>

    <aside className="chat-sidebar" aria-label="Lịch sử và tài liệu truy xuất">
      <section className="chat-side-section" aria-labelledby="chat-history-title">
        <div className="chat-side-heading"><h3 id="chat-history-title">Lịch sử trò chuyện</h3><button type="button" className="chip-btn" disabled={busy} onClick={() => void open('')}>+ Mới</button></div>
        <div className="chat-history-list">
          {sessions.length === 0 && <p className="chat-side-empty">Chưa có cuộc trò chuyện đã lưu.</p>}
          {sessions.map(session => <button type="button" key={session.id} className={`chat-history-item${sid === session.id ? ' active' : ''}`} aria-current={sid === session.id ? 'page' : undefined} aria-label={`Mở cuộc trò chuyện ${session.created_at ? new Date(session.created_at).toLocaleString('vi-VN') : session.id.slice(0, 8)}`} disabled={busy || !!pending} onClick={() => void open(session.id)}>
            <strong>{session.corpus_scope === 'utt_corpus' ? 'Tài liệu UTT' : session.corpus_scope === 'utt_test' ? 'Tài liệu thử nghiệm' : 'Học vụ'}</strong>
            <small>{session.created_at ? new Date(session.created_at).toLocaleString('vi-VN') : session.id.slice(0, 8)}</small>
          </button>)}
        </div>
      </section>

      <section className="chat-side-section" aria-labelledby="chat-source-title">
        <h3 id="chat-source-title">Tài liệu truy xuất</h3>
        {(isAdmin || isStudent) && !sid && <label>Kho tri thức<select aria-label="Kho tài liệu" value={corpusScope} disabled={busy || !!pending} onChange={e => setCorpusScope(e.target.value as 'demo_academic' | 'utt_test' | 'utt_corpus')}><option value="utt_corpus">Tài liệu UTT · kho pilot</option><option value="demo_academic">Học vụ mẫu</option>{isAdmin && <option value="utt_test">Tài liệu thử nghiệm</option>}</select></label>}
        {corpusScope === 'utt_test' && <p className="error">Nguồn thử nghiệm; cần đối chiếu văn bản gốc.</p>}
        {corpusScope === 'utt_corpus' && <p className="chat-source-disclosure"><strong>Nguồn hiện tại: tài liệu UTT.</strong> {PRODUCT_CONFIG.CORPUS_DISCLOSURE} {PRODUCT_CONFIG.PILOT_DISCLOSURE}</p>}
        {selectedEvidenceCards.length === 0
          ? <p className="chat-side-empty">Khi câu trả lời sử dụng tài liệu, tên nguồn, trang/điều và trích đoạn sẽ xuất hiện tại đây.</p>
          : selectedEvidenceCards.map((card, index) => <ChatCard key={index} card={card} feedback={index === selectedEvidenceCards.length - 1 && sid && selectedEvidenceTurn ? { state: feedback[selectedFeedbackKey], onSubmit: label => void submitFeedback(sid, selectedEvidenceTurn.client_turn_id, label) } : undefined} />)}
      </section>
    </aside>
    </div>
  </section>;
}
