import React, { useEffect, useState } from 'react';
import { api } from './api';
import { PRODUCT_CONFIG } from './product-config';
import type { PersonalTranscript_Input as PersonalTranscript, PersonalAttempt_Input as PersonalAttempt, TranscriptView, PersonalSummary, PersonalSimulationResult, PersonalGoalResult, PersonalTargetResult } from './generated-api';

const fmt = (v: string | null | undefined) => v == null ? 'Chưa có' : Number(v).toLocaleString('vi-VN', {maximumFractionDigits: 3});
const empty = (): PersonalTranscript => ({policy_version: 'ACADEMIC-DEMO-2.0.0', terms: [], attempts: [], required_credits: null});

export function PersonalAcademics({ officialProfileLinked = false }: { officialProfileLinked?: boolean }) {
  const [draft, setDraft] = useState<PersonalTranscript>(empty);
  const [revision, setRevision] = useState(0), [busy, setBusy] = useState(true);
  const [message, setMessage] = useState(''), [dirty, setDirty] = useState(false);
  const [summary, setSummary] = useState<PersonalSummary | null>(null);
  const [simulation, setSimulation] = useState<PersonalSimulationResult | null>(null);
  const [goal, setGoal] = useState<PersonalGoalResult | null>(null);
  const [scoreGoal, setScoreGoal] = useState<PersonalTargetResult | null>(null);
  const [target, setTarget] = useState('3.2'), [future, setFuture] = useState('0');
  const terms = draft.terms || [], attempts = draft.attempts || [];
  function change(next: PersonalTranscript) { setDraft(next); setDirty(true); setSimulation(null); setGoal(null); }
  function attemptChange(i: number, patch: Partial<PersonalAttempt>) {
    change({...draft, attempts: attempts.map((a,j) => j === i ? {...a, ...patch} : a)});
  }
  async function reload() {
    const [v, s] = await Promise.all([api<TranscriptView>('/account/transcript'), api<PersonalSummary>('/account/academic-summary')]);
    setDraft(v.transcript); setRevision(v.revision); setSummary(s); setDirty(false); setSimulation(null); setGoal(null);
  }
  useEffect(() => { let alive = true;
    Promise.all([api<TranscriptView>('/account/transcript'), api<PersonalSummary>('/account/academic-summary')]).then(([v,s]) => {
      if (alive) { setDraft(v.transcript); setRevision(v.revision); setSummary(s); }
    }).catch(e => { if (alive) setMessage(e.message); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, []);
  async function task(fn: () => Promise<void>) { setBusy(true); setMessage('');
    try { await fn(); } catch(e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel">
    <h2>Bảng điểm cá nhân tự khai báo</h2>
    <div className="academic-profile-status" role="status">
      <div><strong>1. Tài khoản:</strong> Đã đăng nhập</div>
      <div><strong>2. Hồ sơ tự khai:</strong> {revision > 0 && attempts.length > 0 ? `Đang hoạt động · phiên bản ${revision} · chatbot có thể dùng để tính GPA` : 'Chưa hoàn tất · hãy lưu thông tin cá nhân và bảng điểm'}</div>
      <div><strong>3. Dữ liệu trường:</strong> {officialProfileLinked ? 'Đã liên kết với hồ sơ học vụ' : 'Chưa liên kết/xác minh · không ảnh hưởng việc dùng bảng điểm tự khai'}</div>
    </div>
    <div style={{ padding: '8px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', margin: '8px 0 14px', fontSize: '13px', color: '#92400e' }}>
      <strong>Lưu ý:</strong> {PRODUCT_CONFIG.ACADEMICS.SELF_REPORTED_DISCLOSURE} Bạn có thể tạo, sửa và lưu bảng điểm này mà không cần liên kết hoặc phê duyệt từ quản trị viên. {PRODUCT_CONFIG.ACADEMICS.POLICY_DEMO_DISCLOSURE}
    </div>
    <p style={{ fontSize: '13px', color: dirty ? '#b45309' : '#64748b' }}>
      {dirty ? '● Có thay đổi chưa lưu. Kết quả tính toán bên dưới chưa bao gồm các thay đổi này.' : 'Đang xem dữ liệu đã lưu trong hồ sơ cá nhân.'}
    </p>
    <button disabled={busy} onClick={() => { if (!dirty || window.confirm('Bỏ thay đổi chưa lưu và tải lại?')) void task(reload); }}>Tải lại bảng điểm</button>
    <form onSubmit={e => { e.preventDefault(); void task(async () => {
      const view = await api<TranscriptView>('/account/transcript', {expected_revision: revision, transcript: draft}, 'PUT');
      setRevision(view.revision); setDraft(view.transcript); setDirty(false); setSimulation(null); setGoal(null);
      setMessage('Đã lưu bảng điểm.');
      setSummary(await api<PersonalSummary>('/account/academic-summary'));
    }); }}>
      <fieldset disabled={busy} style={{border: 0}}>
        <label>Tổng tín chỉ chương trình (nếu biết)<input type="number" min="0.000001" max="500" step="0.000001" value={draft.required_credits ?? ''}
          onChange={e => change({...draft, required_credits: e.target.value || null})} /></label>
        <h3>Bước 2 — Khai báo học kỳ</h3>
        {terms.map((t,i) => <div className="grid-two" key={i}>
          <label>Mã kỳ<input required pattern="[A-Za-z0-9_-]{1,40}" value={t.code} onChange={e => {
            const code=e.target.value; change({...draft, terms: terms.map((x,j)=>j===i?{...x,code}:x), attempts: attempts.map(a=>a.term===t.code?{...a,term:code}:a)});
          }} /></label>
          <label>Bắt đầu<input type="date" required value={t.start_date} onChange={e => change({...draft, terms: terms.map((x,j)=>j===i?{...x,start_date:e.target.value}:x)})} /></label>
          <label>Kết thúc<input type="date" required value={t.end_date} onChange={e => change({...draft, terms: terms.map((x,j)=>j===i?{...x,end_date:e.target.value}:x)})} /></label>
          <button type="button" disabled={attempts.some(a=>a.term===t.code)} onClick={()=>change({...draft,terms:terms.filter((_,j)=>j!==i)})}>Bỏ kỳ trống</button>
        </div>)}
        <button type="button" disabled={terms.length>=50} onClick={()=>change({...draft,terms:[...terms,{code:'',start_date:'',end_date:''}]})}>Thêm học kỳ</button>
        <h3>Bước 3 — Nhập môn học và kết quả</h3>
        <p>Học lại giữ nguyên mã môn và tăng số lần học. PE101/PE201/PE301/GEN402 không tính GPA; vẫn phải đạt. Vắng/cấm thi có điểm hiệu lực 0 cho đến khi có lần học mới.</p>
        {attempts.map((a,i)=><div className="panel" key={i}>
          <div className="grid-two">
            <label>Mã môn<input required pattern="[A-Za-z0-9_-]{1,40}" value={a.code} onChange={e=>attemptChange(i,{code:e.target.value.toUpperCase()})} /></label>
            <label>Tên môn<input required maxLength={160} value={a.title} onChange={e=>attemptChange(i,{title:e.target.value})} /></label>
            <label>Học kỳ<select required value={a.term} onChange={e=>attemptChange(i,{term:e.target.value})}><option value="">Chọn kỳ</option>{terms.map((t,k)=><option key={k} value={t.code}>{t.code}</option>)}</select></label>
            <label>Lần học<input type="number" required min={1} max={30} step={1} value={a.attempt} onChange={e=>attemptChange(i,{attempt:Number(e.target.value)})} /></label>
            <label>Tín chỉ<input type="number" required min="0.000001" max="30" step="0.000001" value={a.credits} onChange={e=>attemptChange(i,{credits:e.target.value})} /></label>
            <label>Kết quả<select value={a.status} onChange={e=>attemptChange(i,{status:e.target.value as PersonalAttempt['status'],score:null,available_on:null})}>
              <option value="pending">Chưa có điểm</option><option value="graded">Đã có điểm</option><option value="absent_or_barred">Vắng/cấm thi</option></select></label>
            {a.status==='graded' && <label>Điểm /10<input required type="number" min="0" max="10" step="0.000001" value={a.score ?? ''} onChange={e=>attemptChange(i,{score:e.target.value || null})} /></label>}
            {a.status!=='pending' && <label>Ngày biết kết quả (để trống nếu không rõ)<input type="date" value={a.available_on ?? ''} onChange={e=>attemptChange(i,{available_on:e.target.value || null})} /></label>}
          </div><button type="button" onClick={()=>change({...draft,attempts:attempts.filter((_,j)=>j!==i)})}>Bỏ dòng</button>
        </div>)}
        <button type="button" disabled={!terms.length || attempts.length>=500} onClick={()=>change({...draft,attempts:[...attempts,{code:'',title:'',term:terms[0]?.code || '',credits:'3',attempt:1,status:'pending',score:null,available_on:null}]})}>Thêm lần học</button>
        <button type="submit">Lưu bảng điểm cá nhân</button>
        <button type="button" onClick={()=>void task(async()=>setSimulation(await api<PersonalSimulationResult>('/account/simulations',{expected_revision:revision,transcript:draft})))}>Tính what-if, không lưu</button>
      </fieldset>
    </form>
    {summary && <><h3>Bước 4 — Kết quả đã lưu</h3><p>GPA {fmt(summary.summary.gpa_4)}/4 · {fmt(summary.summary.gpa_10)}/10</p>
      <p>Tín chỉ GPA: {fmt(summary.summary.gpa_credits)} · Tín chỉ đạt: {fmt(summary.summary.earned_credits)} · Còn lại theo tổng tự khai: {fmt(summary.remaining_credits)}</p>
      <p>Môn chưa đạt: {summary.summary.incomplete_courses.join(', ') || 'Không có kết quả chưa đạt'}. Lần học đang chờ: {summary.summary.pending_attempts}.</p>
      <p>Thay đổi GPA tích lũy giữa hai kỳ liền nhau có đủ ngày kết quả: {fmt(summary.trend_4)} /4; {fmt(summary.trend_10)} /10.</p>
      <h3>Lịch sử học kỳ</h3><table><thead><tr><th>Kỳ</th><th>GPA kỳ /4</th><th>GPA kỳ /10</th><th>Tích lũy /4</th><th>Tích lũy /10</th><th>Lũy kế thiếu ngày / đang chờ</th></tr></thead><tbody>
      {summary.semester_history.map(t=><tr key={t.code}><td>{t.code}</td><td>{fmt(t.term.gpa_4)}</td><td>{fmt(t.term.gpa_10)}</td><td>{fmt(t.cumulative.gpa_4)}</td><td>{fmt(t.cumulative.gpa_10)}</td><td>{t.unknown_result_dates} / {t.pending_results}</td></tr>)}</tbody></table>
      <p className="muted">GPA kỳ được nhóm theo học kỳ đã khai. “Thiếu ngày” không làm mất điểm khỏi bảng kỳ, nhưng kỳ đó vẫn mang trạng thái chưa đầy đủ và không được dùng làm lịch sử ML theo thời gian.</p>
      {summary.warnings.map(w=><p className="muted" key={w}>{w}</p>)}</>}
    {simulation && <section role="status"><h3>What-if — chưa lưu</h3><p>GPA /4: {fmt(simulation.before.summary.gpa_4)} → {fmt(simulation.after.summary.gpa_4)}; /10: {fmt(simulation.before.summary.gpa_10)} → {fmt(simulation.after.summary.gpa_10)}</p></section>}
    <form onSubmit={e=>{e.preventDefault();void task(async()=>setGoal(await api<PersonalGoalResult>('/account/required-gpa',{expected_revision:revision,target_gpa:target,future_gpa_credits:future})));}}>
      <h3>Mục tiêu từ bảng điểm đã lưu</h3><label>GPA mục tiêu /4<input required type="number" min="0" max="4" step="0.01" value={target} onChange={e=>setTarget(e.target.value)} /></label>
      <label>Tín chỉ GPA học mới<input required type="number" min="0" max="500" step="0.000001" value={future} onChange={e=>setFuture(e.target.value)} /></label>
      <button disabled={busy || dirty}>Tính mục tiêu</button>
    </form>
    {goal && <p role="status">GPA cần đạt: {fmt(goal.required_future_gpa)} /4. {({achievable:'Có thể đạt',impossible:'Vượt giới hạn 4',insufficient_data:'Chưa đủ dữ liệu',completed_target_met:'Đã đạt',completed_target_not_met:'Chưa đạt, không còn tín chỉ mới'} as Record<string,string>)[goal.feasibility] || goal.feasibility}. Chỉ dự kiến tín chỉ học mới, không thay thế điểm học lại.</p>}
    <details><summary>Tính điểm thành phần còn thiếu</summary>
      <p>Nhập điểm trung bình có trọng số của phần đã biết và trọng số của phần đó. Phần còn lại phải là một thành phần duy nhất.</p>
      <form onSubmit={e=>{e.preventDefault(); const f = new FormData(e.currentTarget);
        const weight = Number(f.get('weight'));
        setScoreGoal(null);
        void task(async()=>setScoreGoal(await api<PersonalTargetResult>('/account/target-score',{
          target_score: String(f.get('target')), minimum_unknown_score: String(f.get('minimum')),
          components:[{weight: String(weight), score: String(f.get('known'))}, {weight: (1-weight).toFixed(6), score:null}]
        })));
      }}>
        <label>Điểm tổng kết mong muốn /10<input name="target" type="number" min="0" max="10" step="0.01" required /></label>
        <label>Điểm phần đã biết /10<input name="known" type="number" min="0" max="10" step="0.01" required /></label>
        <label>Trọng số phần đã biết (0–1)<input name="weight" type="number" min="0.000001" max="0.999999" step="0.000001" required /></label>
        <label>Điểm sàn phần còn thiếu (nếu có)<input name="minimum" type="number" min="0" max="10" step="0.01" defaultValue="0" required /></label>
        <button disabled={busy}>Tính điểm cần đạt</button>
      </form>
      {scoreGoal && <div role="status"><p>Cần {scoreGoal.required_score}/10. {scoreGoal.feasibility==='impossible'?'Không khả thi với điểm tối đa 10.':'Khả thi theo các giả định đã nhập.'}</p>{scoreGoal.assumptions.map(a=><p key={a}>{a}</p>)}</div>}
    </details>
    {message && <p role="status">{message}</p>}
  </section>;
}
