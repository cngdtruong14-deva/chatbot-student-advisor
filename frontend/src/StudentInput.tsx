import React, { useState } from 'react';
import { api } from './api';

type Row = { key: number; code: string; credits: string; score: string; attempt: string };
const blank = (key: number): Row => ({ key, code: '', credits: '3', score: '', attempt: '1' });
const format = (value: unknown) => value == null ? 'Chưa đủ dữ liệu' : Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 3 });
const states: Record<string, string> = { achievable: 'Có thể đạt', impossible: 'Vượt giới hạn GPA 4', insufficient_data: 'Chưa đủ dữ liệu', completed_target_met: 'Đã đạt mục tiêu', completed_target_not_met: 'Chưa đạt; cần thêm tín chỉ hoặc kịch bản học lại' };

export function StudentInput() {
  const [policy, setPolicy] = useState('ACADEMIC-DEMO-2.0.0');
  const [rows, setRows] = useState<Row[]>([blank(1)]);
  const [target, setTarget] = useState('3.2'), [future, setFuture] = useState('0');
  const [result, setResult] = useState<any>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  function change(key: number, field: keyof Omit<Row, 'key'>, value: string) {
    setRows(previous => previous.map(row => row.key === key ? { ...row, [field]: value } : row)); setResult(null);
  }
  async function calculate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setResult(null);
    try {
      setResult(await api('/academic/self-reported/preview', {
        courses: rows.map(({ key, ...row }) => ({ ...row, code: row.code.trim().toUpperCase(), attempt: Number(row.attempt) })),
        target_gpa: target, future_gpa_credits: future,
        policy,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel">
    <h2>Nhập điểm & tín chỉ để tính thử</h2>
    <p>Dữ liệu tự khai · Hiển thị GPA thang 10 và thang 4 theo quy tắc bạn chọn.</p>
    <p className="muted">Không ghi vào bảng điểm chính thức. Dữ liệu chỉ giữ trên màn hình này, rời trang sẽ mất. Không nhập tên hoặc mã sinh viên.</p>
    <form onSubmit={event => void calculate(event)}>
      <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
        <label>Quy tắc tính thử<select value={policy} onChange={e => { setPolicy(e.target.value); setResult(null); }}>
          <option value="ACADEMIC-DEMO-2.0.0">ACADEMIC-DEMO-2 · Luồng demo hiện tại</option>
          <option value="POL-01-demo">POL-01 demo · Quy đổi từng môn theo bậc</option>
          <option value="DEMO-1">DEMO-1 · Quy đổi tuyến tính × 0,4</option>
        </select></label>
        {policy === 'ACADEMIC-DEMO-2.0.0' && <p className="muted">Học lại lấy lần mới nhất, kể cả khi điểm thấp hơn. PE101/PE201/PE301/GEN402 chỉ xét đạt hoặc không đạt, không tính GPA. Điểm 4 trở lên là đạt; việc vắng/cấm thi chỉ có thể được ghi nhận trong bảng điểm chính thức.</p>}
        {policy === 'POL-01-demo' && <p className="muted">Mốc điểm: 4 → 1; 5 → 1,5; 5,5 → 2; 6,5 → 2,5; 7 → 3; 8 → 3,5; 8,5 → 4. Dưới 4 → 0. Mọi môn trong biểu mẫu đều tính GPA.</p>}
        {rows.map((row, index) => <div className="panel" key={row.key}>
          <h3>Học phần {index + 1}</h3>
          <div className="grid-two">
            <label>Mã môn <input required maxLength={40} pattern="[A-Za-z0-9_\-]+" placeholder="VD: CNTT101" value={row.code} onChange={e => change(row.key, 'code', e.target.value)} /></label>
            <label>Tín chỉ <input required type="number" min="0.000001" max="30" step="0.000001" value={row.credits} onChange={e => change(row.key, 'credits', e.target.value)} /></label>
            <label>Điểm tổng kết / 10 <input required type="number" min="0" max="10" step="0.000001" value={row.score} onChange={e => change(row.key, 'score', e.target.value)} /></label>
            <label>Lần học <input required type="number" min="1" max="20" step="1" value={row.attempt} onChange={e => change(row.key, 'attempt', e.target.value)} /></label>
          </div>
          <button type="button" className="secondary" disabled={rows.length === 1} onClick={() => { setRows(rows.filter(item => item.key !== row.key)); setResult(null); }}>Bỏ dòng {index + 1}</button>
        </div>)}
        <button type="button" className="secondary" disabled={rows.length >= 200} onClick={() => { setRows([...rows, blank(Math.max(...rows.map(row => row.key)) + 1)]); setResult(null); }}>+ Thêm học phần</button>
        <div className="grid-two">
          <label>GPA mục tiêu / 4 <input required type="number" min="0" max="4" step="0.01" value={target} onChange={e => { setTarget(e.target.value); setResult(null); }} /></label>
          <label>Tín chỉ GPA dự kiến học mới <input required type="number" min="0" max="126" step="0.000001" value={future} onChange={e => { setFuture(e.target.value); setResult(null); }} /></label>
        </div>
        <button>{busy ? 'Đang tính…' : 'Tính GPA & mục tiêu'}</button>
      </fieldset>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {result && <div role="status">
      <h3>Kết quả tự khai — không thay đổi hồ sơ</h3>
      <p>GPA: <strong>{format(result.summary.cumulative_gpa)} / 4</strong></p>
      <p>Điểm trung bình: <strong>{format(result.summary.gpa_10)} / 10</strong></p>
      <p>Tín chỉ tính GPA: {format(result.summary.gpa_credits)} · Đã đạt: {format(result.summary.earned_credits)}</p>
      <p>GPA cần đạt ở các tín chỉ mới: {format(result.goal.required_future_gpa)}</p>
      <p>{states[result.goal.feasibility] || result.goal.feasibility}</p>
      {result.warnings.map((warning: string) => <p className="muted" key={warning}>{warning}</p>)}
    </div>}
  </section>;
}
